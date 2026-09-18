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

## test
```cmd
C:\DID_QA\.venv\Scripts\python.exe -m streamlit run C:\DID_QA\app.py --server.headless true --browser.gatherUsageStats false --server.port 8501
```

```
http://127.0.0.1:8501/
```

```
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
