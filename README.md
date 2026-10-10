# RSC FastAPI app — Neo4j natural-language Q&A

Self-contained package for **Posit Connect / RStudio Connect (RSC)**.
Uses network Neo4j + Pfizer Vox GenAI, with the **DID Insight2** chat UI.

**Recommended production path:** push this folder to GitHub, then **Import from Git** on Connect. See [`GITHUB_DEPLOY.md`](GITHUB_DEPLOY.md).

## Contents

| File | Role |
|------|------|
| `app.py` | FastAPI entry (`app:app`) serving the Insight2 UI and JSON API |
| `web/static/index.html` | DID Insight2 single-page chat UI |
| `agent.py` | NL → Cypher → answer (loads domain docs/examples for few-shot prompting) |
| `result_presentation.py` | Validates a constrained, post-query table/chart selection |
| `example_memory.py` | Thumbs-up example library used for positive few-shot training |
| `export.py` | CSV / JSON table download |
| `neo4j_client.py` | Read-only Neo4j access |
| `vox_client.py` | Vox OAuth + chat completions + model listing |
| `docs/skill.md` | DID query skill rules |
| `docs/schema.md` | DID graph schema reference |
| `docs/examples/*.md` | Reusable DID Cypher few-shot examples |
| `.github/agents/did-neo4j-qa.agent.md` | Copilot CLI custom agent template (optional) |
| `requirements.txt` | Python deps |
| `manifest.json` | Required for Git-backed Connect deploy (`python-fastapi`) |
| `GITHUB_DEPLOY.md` | GitHub + Import from Git instructions |
| `.env.example` | Env var template (no secrets) |
| `.env` | Local test secrets (**do not commit**) |

## Local smoke test

```cmd
cd rsc-app
py -m pip install -r requirements.txt
py -m uvicorn app:app --host 127.0.0.1 --port 8010
```

Open http://127.0.0.1:8010

## DID effort prediction

The project includes a read-only Neo4j-to-model pipeline for forecasting the
total hands-on hours for a person assigned to a planned or ongoing DID.

Detailed technical documentation: [Chinese](docs/effort_prediction.md) | [English](docs/effort_prediction_en.md).
For a Chinese v1-to-v3 reporting summary, see [model evolution](docs/effort_prediction_model_evolution.md).

The published model is bundled and ready to use; do not retrain or refresh
production artifacts to deploy this migration. The following commands are for
an explicit future, offline model-development workflow, not deployment.
Install dependencies, then export completed DID history:

```cmd
py effort_prediction.py extract --output data\did_effort_training.json
```

Review the printed data-quality report before training. Train with a grouped
time split (70% train, 15% interval calibration, 15% test):

```cmd
py effort_prediction.py train --input data\did_effort_training.json --model data\new_did_effort_model.joblib --cache data\new_did_effort_similarity_cache.joblib
```

The training command reports MAE, median absolute error, RMSE, WAPE, bias, and
P80/P90 coverage. It saves the fitted preprocessing pipeline, model, interval
adjustments, and eligible history in one versioned artifact.

Model v3-robust keeps exact TLF-name Jaccard features and local character 3–5
gram title similarity with Type/Source weighting and one-to-one matching. It
reduces expensive comparisons to relevant/recent historical candidates and
persists semantic pair results in the `--cache` file. Later retraining runs
reuse unchanged pairs. Training progress and cache hit/miss counts are written
to the console.

The model also learns from repeated similar work through top-3/top-5 similarity,
similar-DID counts, similarity-weighted hours and hours-per-task, latest similar
hours, and the historical similar-hours trend. Cross-DID union coverage measures
whether multiple historical DIDs collectively cover the target task set.

To prevent extreme Ridge extrapolation, the calibration split selects a blend
between Ridge and the person's historical median plus an optional historical
effort cap. Training reports raw Ridge, personal-baseline, and robust-blend
metrics. After updating from an older version, retrain the model; the existing
extracted JSON and semantic cache can be reused.

Predict a planned or ongoing assignment:

```cmd
py effort_prediction.py predict --model artifacts\did_effort_model.joblib --person "Chen, Sizhen" --did "DID123"
```

Export a dated CSV snapshot for every assigned DID whose current Neo4j status is
`ongoing`:

```cmd
py effort_prediction.py export-ongoing --output data\ongoing_did_predictions.csv --model artifacts\did_effort_model.joblib
```

The CSV contains one `Person x DID` row per assignment, the V3 P50/P80/P90
forecast, planned delivery date, model version, and key similarity diagnostics.

Validate a preserved ongoing snapshot once assignments become completed:

```cmd
py validate_effort_predictions.py --input data\ongoing_did_predictions.csv --output data\prediction_actual_comparison_YYYY-MM-DD.csv --report data\prediction_validation_report_YYYY-MM-DD.md
```

This keeps every completed comparison row in the CSV for audit, but formal
accuracy metrics include only rows with at least one recorded `TIME_ON` entry.
The command also writes a self-contained HTML dashboard beside the report,
including a P50-versus-actual scatter plot and long-tail error diagnostics.
Use `--visualization path\to\dashboard.html` to select another dashboard path.

Use `--as-of-date YYYY-MM-DD` for a historical/current-state forecast. Only
completed records strictly before that date contribute to personal efficiency
and similarity features. Generated exports are gitignored; the four published
model/cache/snapshot files under `artifacts` are explicitly tracked with Git LFS.

### Natural-language Agent integration

After a trained model exists at `artifacts/did_effort_model.joblib`, the chat UI
automatically routes explicit prediction questions to the model:

```text
预测 Riven 完成 C5001001_59 需要多少工时？
Predict Riven's effort for C5001001_59.
```

Explicit effort-prediction requests use a constrained intent and parameter
extraction flow. Every other graph-data question uses the existing generic,
read-only Text-to-Cypher flow: Vox generates Cypher, Neo4j returns rows, and a
separate constrained Vox call may select a table or safe chart from those exact
returned fields. A validated presentation is visual-only by default, avoiding a
duplicate Markdown row list and a third answer call; Vox may explicitly request
a concise summary only when needed. Python rejects unknown fields, transformed
values, and charts with missing, non-numeric, or non-finite numeric data. A
chart always includes a table fallback; a selection failure simply omits
presentation and never fails an otherwise successful Q&A response. See
[`docs/post_query_presentation.md`](docs/post_query_presentation.md).

The `/api/query` response includes `elapsed_ms` for end-to-end latency and a
`timings_ms` object with the applicable pipeline stages, such as intent routing,
prompt preparation, Cypher generation, Neo4j execution, repair, presentation,
and answer generation. The chat UI exposes these values under **Stage timings**.
When the app is started with `python app.py` or Uvicorn, each completed query
also writes the same stage breakdown to the server console without logging the
question text.

Prediction requests continue with their separate LLM-first parameter extraction,
Neo4j validation, and V3 model calculation. Python computes P50/P80/P90; the
LLM does not calculate or alter prediction values.

### Recommend Team

**Recommend Team** and **Allocate TLF People** are integrated into the existing
DID Insight2 FastAPI UI alongside **Ask Neo4j**. Chat, identity disambiguation,
feedback, org/graph/chart/table and existing exports are unchanged.

Python ranks current `Person.Team_Lead_Name` groups using a manually refreshed local
published v4 snapshot of completed-DID scope evidence and active workload.
The searchable TA Lead selection is restricted to snapshot-backed **Shen, Henry**
and **Iyer, Priya Venkatesan**; there is no Group selector. All eligible teams
across the selected TA's current groups are compared, using 37/18/10/35 weights
and the selected eligible teams' maximum workload as denominator. The top three
include total candidate count, group metadata, actual Generation/QC-owned
historical TLF coverage evidence and similar completed DIDs.

The UI never queries Neo4j during a recommendation; it reads this snapshot and
the shared `did_effort_similarity_cache.joblib`. Recommendations are decision
support only; review the displayed snapshot time, scope gaps, and similar
historical DIDs before assigning work. Set `DU_TEAM_HISTORY_SNAPSHOT_PATH` to
use another explicit snapshot location in RSC. When using the default
Git-tracked snapshot, RSC automatically downloads its full Git LFS content on
first use. `DU_TEAM_HISTORY_SNAPSHOT_URL` can override its download URL.
See the full [DU Team recommendation metric definition](docs/du_team_recommendation.md).

### TLF-only person allocation

The **Allocate TLF People** tab accepts a single TLF CSV or Excel workbook with a
`TLF` sheet, and recommends distinct Generation/QC
primaries plus backups from the published Person × TLF evidence snapshot. Select
an exact complete Team Lead name from the searchable, unrestricted snapshot list.
There is no LLM matching. Group constraints, flagged same-person fallback,
role evidence, workload and run-local balancing match the source implementation.
Results include primary/backup scores, workload, evidence, warnings and Excel download.

It never queries Neo4j at UI runtime. See [TLF person allocation](docs/tlf_person_allocation.md)
for snapshot schema, exact snapshot Team Lead validation, scoring, and balancing.

Recommendation uses a normal single-select TA Lead dropdown with an explicit
placeholder and the two snapshot-backed Henry/Priya names. Upload an `.xlsx`
workbook with a `TLF` sheet or a TLF CSV; no separate Data CSV is used.
Allocation keeps the searchable Team Lead list and has only one upload entry:
a single TLF CSV or an `.xlsx` workbook with a `TLF` sheet. `Source Datasets`
groups related TLFs without any separate Data upload. Missing sources remain
individual TLF groups; no ADaM-to-SDTM mapping is inferred.
An existing embedded `Data` sheet remains optional: its `SDTM/ADaM` and
`Domain/Dataset Name` columns preserve direct SDTM source/domain grouping,
not ADaM/SDTM recommendation scoring.
Use **Download example workbook** to obtain `docs/C5001001_61.xlsx`.
Each upload is limited to 20 MB. Changing selections/files or pressing Reset
clears stale results; a running request shows elapsed progress and clear errors.

Planning API (all paths retain existing Q&A endpoints):

| Method / path | Purpose |
|---|---|
| `GET /api/planning/recommend/options` | Snapshot-backed Henry/Priya names |
| `GET /api/planning/allocate/options` | Complete snapshot Team Lead list |
| `GET /api/planning/example` | Example workbook |
| `POST /api/planning/recommend` | Multipart `ta_lead_name`, `primary_file` (TLF only) |
| `POST /api/planning/allocate` | Multipart `team_lead_name`, `primary_file` (single TLF CSV or workbook; embedded Data optional) |
| `POST /api/planning/allocate/excel` | JSON `{"result": <allocation response>}` → Excel |
| `POST /api/planning/jobs/recommend` / `jobs/allocate` | Same multipart inputs → 202 + `job_id` |
| `GET /api/planning/jobs/{job_id}` | Queued/running/completed/error state, elapsed time and result |

The UI uses short upload + polling requests rather than keeping a long HTTP
request open: cold, large-workbook comparisons can take minutes with the exact
source business logic. Results are memory-only, expire after one hour, and the
queue is bounded to eight runs. Reset discards the UI state, not already-running
server work. Server restarts expire runs; deployments with multiple workers need
sticky routing to the same worker (or use the direct synchronous APIs).

The presentation layer labels only unambiguous returned fields: `hours`,
`recorded_hours`, and `time_on_hours` mean recorded `TIME_ON` hours;
`task_count` means assigned task count. It does not infer units for other
fields.

### RSC model artifact loading

The v3 model and similarity cache are tracked in GitHub with Git LFS. Git-backed
RSC deployments may receive only their small LFS pointer files. On the first
prediction request, the app detects that condition and downloads both artifacts
from **this FastAPI repository's pinned `published-artifacts-26af6b5` tag**
to a writable local cache. Missing default files use the same fallback; missing
custom paths fail explicitly. Downloaded bytes are verified against published
SHA-256/size provenance. Later requests
reuse the cached copies within that RSC runtime.

Exactly four source LFS artifacts were migrated from
[`26af6b5`](https://github.com/LUM16/DID_QA/commit/26af6b5b8ebf5c106da582dca7bc4c33eb9a258d),
without retraining or Neo4j refresh. Historical effort data is **embedded in the
model** (32,705 historical rows), not a fifth missing file. The shared similarity
cache contains 355,638 pairs; team v4 has 15,663 history rows; person allocation
v1 has 1,049,456 history rows. Exact OIDs, sizes and provenance are recorded in
[`artifacts/provenance.json`](artifacts/provenance.json).
Scikit-learn is pinned to **1.9.1**, matching the saved pipeline.

Published artifacts are never mutated at request time. Similarity additions
are written to a separate `.artifact-cache/published-artifacts-26af6b5` copy
(or `DID_EFFORT_ARTIFACT_CACHE_DIR`), excluded from Git/deployment. Cache writes
and initial download/copy use atomic, unique staged files; planning calls are
serialized to protect shared in-memory business indexes. Neo4j's shared driver
is only closed by FastAPI lifespan shutdown.

The default artifact URLs work for this repository. These optional RSC Vars can
override them or configure a private repository:

- `DID_EFFORT_MODEL_URL`
- `DID_EFFORT_SIMILARITY_CACHE_URL`
- `DID_EFFORT_ARTIFACT_CACHE_DIR`
- `DU_TEAM_HISTORY_SNAPSHOT_URL`
- `TLF_PERSON_ALLOCATION_SNAPSHOT_URL`
- `GITHUB_TOKEN` (only when the artifact URLs require authentication)

Configure URL overrides only for the same verified published bytes. On Connect,
ensure a writable artifact-cache directory, trusted HTTPS access to GitHub media,
adequate memory for the million-row allocation snapshot, and Python ≥3.11 with
the pinned dependencies. First-use downloads total approximately 599 MiB when
all four LFS objects are needed. Repository publication does not itself deploy or
configure the existing Connect instance.

### Regression validation

```powershell
python -m unittest test_planning_api test_app test_agent_templates test_agent_prediction test_neo4j_client test_vox_client test_effort_prediction test_du_team_recommendation test_tlf_person_allocation test_result_presentation test_example_memory test_validate_effort_predictions
# Optional, after git lfs pull; this never calls Neo4j/LLM or retrains:
$env:DID_RUN_ARTIFACT_SMOKE = "1"
python -m unittest test_published_artifacts
```

Person input is matched against Neo4j names without requiring exact punctuation
or name order. A unique parenthesized alias is also accepted, such as `Riven`
for `Chen, Zhenchao (Riven)`. Ambiguous short names produce an explicit error
instead of selecting an arbitrary person.

Important limitations:

- The label is total recorded hands-on hours, not calendar duration.
- Training excludes incomplete DID records and invalid/zero labels.
- If `TIME_ON` cannot distinguish Generation from QC, the model predicts the
  combined Person x DID effort.
- TLF/ADaM/SDTM similarity is person-specific where assignment metadata is
  available. Similarity is a learned feature, not a hard-coded discount.
- Strict historical backtesting requires versioned scope snapshots. With only
  the current graph state, evaluation is a current-state approximation.

## Prompt knowledge reuse (from previous CLI agent)

- The app now reuses the existing DID prompt library under `docs/`.
- For each user question, `agent.py` loads:
  - `docs/skill.md`
  - `docs/schema.md`
  - the most relevant example files from `docs/examples/*.md`
  - 👍 user-endorsed Q+Cypher pairs from `data/memory/` (local, not committed)
- After an answer, download the result table as CSV/JSON, or mark 👍 to grow that
  positive example library. 👎 excludes a case from future few-shot use.
- This keeps existing examples usable after you push to GitHub and deploy on RSC.

## Deploy to Posit Connect

### Option A — GitHub (Git-backed, recommended)

1. Push this folder to a **private** GitHub repo (never include `.env`).
2. On Connect: **Publish → Import from Git**, branch `main`, directory that contains `manifest.json`.
3. Set **Vars** (same list as below). Do not upload `.env`.

Full steps (create repo, `git add` list, Connect UI, Vars): **[`GITHUB_DEPLOY.md`](GITHUB_DEPLOY.md)**.

### Option B — CLI (`rsconnect`)

```cmd
cd rsc-app
py -m pip install rsconnect-python
rsconnect add --name pfizer-connect --server https://YOUR-CONNECT-HOST --api-key YOUR_API_KEY
rsconnect deploy fastapi . --name "DID Insight" --entrypoint app:app
```

### Option C — Push-button publish from IDE

Publish as a **FastAPI / Python API** content item; set the ASGI entrypoint to **`app:app`**.

If Connect already has this repo as a Streamlit app, **Import from Git again** as FastAPI (or create a new content item). Git-backed Streamlit content cannot switch appmode in place.

### Environment variables on Connect (recommended)

Do **not** rely on uploading `.env` in production. Set Connect **Vars**:

- `NEO4J_URI` = `bolt://10.109.17.64:7687`
- `NEO4J_USERNAME` = `neo4j`
- `NEO4J_PASSWORD` = *(secret)*
- `NEO4J_DATABASE` = `neo4j`
- `VOX_GENAI_API` = `https://mule4api-comm-amer.pfizer.com/vox-genai-api-v2`
- `VOX_TOKEN_GEN_URL` = `https://prodfederate.pfizer.com/as/token.oauth2`
- `VOX_CLIENT_ID` = *(secret)*
- `VOX_CLIENT_SECRET` = *(secret)*
- `VOX_MODEL` = `gpt-4o`

`.rscignore` excludes `.env` from CLI publishes — set the **Vars** above on Connect.
For local testing, keep secrets in `rsc-app/.env` (already gitignored).

## Network checklist

From the **Connect server**, these must be reachable:

1. Neo4j Bolt: `10.109.17.64:7687`
2. Vox token: `https://prodfederate.pfizer.com`
3. Vox API: `https://mule4api-comm-amer.pfizer.com`
4. GitHub artifact URL: `https://media.githubusercontent.com` (needed on the
   first effort-prediction request when RSC did not fetch Git LFS objects)

If schema load fails after publish, it is almost always firewall / routing between RSC and Neo4j.

## Security

- Prefer Connect Vars for passwords and client secrets.
- Rotate credentials after testing if they were shared in chat or committed by mistake.
