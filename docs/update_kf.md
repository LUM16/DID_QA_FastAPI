# KongF Update Log

## Update records

## 2026-09-16 16:18 - Agent workflow synchronization

### Scope

This update synchronizes the core workflow and prompt-budget improvements from
`agent_update.py` into `agent.py`, while preserving the existing effort
prediction and post-query result-presentation capabilities used by the
application.

### Changes

### 1. LangGraph workflow for standard Neo4j queries

Standard graph Q&A now runs through an explicit workflow:

```text
START -> prepare -> generate -> execute
                           -> repair -> execute
                           -> answer/failure -> END
```

- `prepare`: loads the live schema and relevant business context.
- `generate`: produces a read-only Cypher query.
- `execute`: runs the query and records the outcome.
- `repair`: makes one focused repair after the first failed or empty query.
- `answer`: creates the result presentation and optional natural-language
  answer.
- `failure`: returns the final query failure after the repair opportunity has
  been used.

Effort-prediction requests are still identified and handled before entering
this standard-query workflow.

### 2. Prompt budget controls

The following limits now prevent long conversations, large result sets, and
unrelated examples from increasing prompt size without bound:

| Input | Current limit |
|---|---:|
| Conversation history | Latest 4 messages |
| Each history message | 500 characters |
| Query-result JSON | 6,000 characters |
| Business rule document | 6,000 characters |
| Each selected example | 5,000 characters |
| Relevant examples | At most 3 |

### 3. Smaller schema and example context

- Cypher prompts now include only live `labels`, `relationshipTypes`, and
  `propertyKeys`, serialized as compact JSON.
- The static schema document is no longer duplicated in every Cypher prompt.
- Only examples relevant to the user question are loaded, with
  `query_index.md` and `study_delivery.md` as fallbacks.

### 4. Focused query repair and empty-result handling

- A failed or empty first query gets one focused repair request containing the
  live schema, question, previous Cypher, and execution outcome.
- The repair request no longer repeats the full conversation, business
  examples, or unused previous-row input.
- If the repaired query is still empty, the agent returns a local Chinese or
  English no-data message instead of making an unnecessary LLM answer call.

### 5. Dependency

`langgraph>=0.2.0` was added to `requirements.txt`.

### Before-and-after comparison

| Area | Before | After |
|---|---|---|
| Standard-query orchestration | Generation, execution, repair, retries, and answers were concentrated in `ask()`. | The LangGraph workflow separates preparation, generation, execution, repair, answer, and failure paths. |
| Retry behavior | Up to three broad attempts could regenerate the full query context after different kinds of failures. | One explicit repair is allowed after the first failed or empty execution; later failures return a clear error. |
| Schema prompt | Full formatted schema was provided, including fields not needed for Cypher construction. | Compact live query-relevant schema only: labels, relationship types, and property keys. |
| Business context | Static schema documentation and all safe examples were appended to prompts. | Business rules plus no more than three relevant examples are supplied. |
| Conversation history | The latest six messages were sent without per-message length limits. | The latest four messages are sent, each limited to 500 characters. |
| Query results in prompts | Up to 80 rows were serialized, which could still be very large when rows contained nested or long values. | Complete rows are accumulated only up to a 6,000-character JSON budget. |
| Query repair prompt | Repeated schema, history, long rules, and an unused `previous_rows` parameter. | Contains only the minimal data needed to diagnose and correct the failed query. |
| Empty results | Could invoke the LLM to describe an empty result set. | Returns a local bilingual no-data response after the repair path is exhausted. |
| Effort prediction | Existing dedicated forecast routing and formatting. | Preserved; prediction requests remain outside the standard Cypher graph workflow. |
| Result presentation | Existing chart/table selection and application response fields. | Preserved and executed in the workflow answer node, maintaining `visualization`, `table`, and warning fields. |

## 2026-09-17 14:29 - Langfuse tracing integration

### Scope

Added optional Langfuse tracing for all Vox GenAI chat completions by
instrumenting the shared `vox_client.chat()` wrapper. Updated environment
configuration examples and Python dependencies.

### Changes

- Added optional Langfuse generation tracing around each `chat()` call.
- A trace is created only when both `LANGFUSE_PUBLIC_KEY` and
  `LANGFUSE_SECRET_KEY` are configured.
- Each generation records:
  - provider metadata: `vox-genai-v2`
  - model name
  - temperature
  - system/user messages
  - model output
  - prompt, completion, and total token usage
- If Langfuse credentials are configured but the package is missing, startup
  surfaces a clear dependency error instead of silently disabling tracing.
- If only one Langfuse credential is configured, startup surfaces a clear
  configuration error instead of silently disabling tracing.
- Added optional Langfuse variables to `.env.example`.
- Added `langfuse>=4.0.0` to `requirements.txt`.

### Before-and-after comparison

| Area | Before | After |
|---|---|---|
| LLM observability | Vox chat calls returned text and token usage only inside the application. | Every configured Vox chat call is also recorded as a Langfuse generation. |
| Enablement | No Langfuse configuration existed. | Setting `LANGFUSE_PUBLIC_KEY` and `LANGFUSE_SECRET_KEY` enables tracing; leaving them empty disables it. |
| Instrumentation location | No central tracing hook. | Tracing is implemented once in `vox_client.chat()`, covering all agent LLM calls. |
| Token tracking | Token usage was accumulated only in app state. | Token usage is still returned to the app and is also attached to the Langfuse generation. |
| Missing or incomplete tracing setup | Not applicable. | If credentials are incomplete or the package is missing after credentials are configured, a clear runtime error is raised. |

## 2026-09-20 10:20 - Query stage timing observability

### Scope

Added end-to-end and stage-level latency measurements for the standard Neo4j
Q&A workflow and effort-prediction workflow. Timing data is available in the
API response, the chat UI, and the server console when the application is
started directly with `python app.py` or through Uvicorn.

### Changes

### 1. Standard-query stage timings

The LangGraph workflow records the time spent in each applicable stage:

| Stage | Meaning |
|---|---|
| `intent` | Prediction-versus-standard-query routing |
| `prepare` | Live schema and business-context preparation |
| `cypher_generation` | Vox generation of the read-only Cypher query |
| `neo4j` | Neo4j query execution; repeated executions are accumulated |
| `cypher_repair` | Optional Vox repair of a failed or empty query |
| `presentation` | Table/chart presentation selection |
| `answer_generation` | Optional natural-language answer generation |
| `total` | End-to-end `/api/query` request time |

Only stages that actually run are included. For example, a visual-only result
does not include `answer_generation`, and a successful first query does not
include `cypher_repair`.

### 2. Effort-prediction stage timings

Prediction requests report the applicable prediction pipeline stages:

| Stage | Meaning |
|---|---|
| `intent` | Effort-prediction intent routing |
| `prediction_parameters` | Person, DID, and as-of-date extraction |
| `prediction_model` | Model loading, feature construction, and prediction |
| `answer_generation` | Local formatting of the prediction response |
| `total` | End-to-end `/api/query` request time |

### 3. API and chat UI

- `/api/query` keeps the existing `elapsed_ms` field for compatibility.
- The response now also includes `timings_ms`, containing each measured stage
  and the end-to-end `total`.
- The chat result metadata includes an expandable **Stage timings** section.
- Stage values are non-negative integer milliseconds.

Example response fragment:

```json
{
  "elapsed_ms": 5342,
  "timings_ms": {
    "intent": 0,
    "prepare": 4,
    "cypher_generation": 3150,
    "neo4j": 128,
    "presentation": 2050,
    "total": 5342
  }
}
```

### 4. Direct-run and server-console logging

When the application is run locally:

```powershell
cd C:\Users\KONGF06\Documents\DID_QA_FastAPI
.\.venv\Scripts\python.exe app.py
```

each completed query writes one structured line to the Uvicorn console:

```text
DID query timings | intent=0ms | prepare=4ms | cypher_generation=3150ms | neo4j=128ms | presentation=2050ms | total=5342ms | rows=5 | status=ok
```

The log records stage durations, row count, and success/error status. It does
not record the user's question text, reducing the risk of business content
being copied into local or Posit Connect logs.

### Before-and-after comparison

| Area | Before | After |
|---|---|---|
| API latency | Only one end-to-end `elapsed_ms` value. | `elapsed_ms` remains, and `timings_ms` identifies the applicable pipeline stages. |
| Chat UI | Displayed total latency and token usage. | Also exposes an expandable stage-by-stage timing breakdown. |
| Direct `app.py` execution | Uvicorn logged HTTP access information only. | Each completed query also emits one structured timing line. |
| Posit Connect logs | No query-pipeline latency breakdown. | The same structured timing line is available in server logs. |
| Privacy | No timing-specific logs. | Timing logs deliberately omit question text and returned row contents. |
| Prediction diagnostics | Prediction latency was included only in total request time. | Parameter extraction, model execution, and response formatting are measured separately. |

### Validation status

- 21 timing, prediction-routing, and result-presentation tests passed.
- The complete local suite ran 65 tests: 64 passed, and one unrelated existing
  export test could not find
  `artifacts/did_effort_similarity_cache.joblib` in the local environment.
- Starting the application with `python app.py` returned HTTP 200 from
  `http://127.0.0.1:8010/`.
- The local page contained the expected DID Insight application content.
- Pylance/editor diagnostics reported no errors in the changed Python files.
- `git diff --check` completed without whitespace errors.
- Production deployment checksums in `manifest.json` were updated for the
  changed application and documentation files included in the deployment.

## Local test

```powershell
cd C:\Users\KONGF06\Documents\DID_QA_FastAPI
.\.venv\Scripts\python.exe app.py
```

Open:

```text
http://127.0.0.1:8010/
```

Optional Langfuse trace review:

```text
https://cloud.langfuse.com
```

### Validation status

- Installed direct tracing dependencies `openai>=1.40.0` and `langfuse>=4.0.0`
  in both the active Python 3.10 environment and the project `.venv`.
- Installed the existing `neo4j>=5.0.0` dependency needed to import
  `vox_client.py` for validation.
- `vox_client.py` passed Python syntax validation.
- Pylance reported no diagnostics for `vox_client.py`.
- Langfuse tracing smoke tests passed for both disabled and configured modes
  using local test doubles in the project `.venv`.
- `git diff --check` completed without whitespace errors.
