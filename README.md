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

Install dependencies, then export completed DID history:

```cmd
py effort_prediction.py extract --output data\did_effort_training.json
```

Review the printed data-quality report before training. Train with a grouped
time split (70% train, 15% interval calibration, 15% test):

```cmd
py effort_prediction.py train --input data\did_effort_training.json --model artifacts\did_effort_model.joblib --cache artifacts\did_effort_similarity_cache.joblib
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
and similarity features. Generated exports and model artifacts are gitignored.

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

Prediction requests continue with their separate LLM-first parameter extraction,
Neo4j validation, and V3 model calculation. Python computes P50/P80/P90; the
LLM does not calculate or alter prediction values.

### DU Team recommendation

The **Recommend DU Team** and **Allocate TLF People** pipelines remain available
as Python modules (`du_team_recommendation.py`, `tlf_person_allocation.py`).
The published RSC UI matches DID Insight2 (chat + org/graph/chart/table).

Python ranks current `Person.Team_Lead_Name` groups using a manually refreshed local
snapshot of completed-DID scope evidence and active workload. Refresh it after
each Neo4j update:

```cmd
py du_team_recommendation.py refresh-history
```

The UI never queries Neo4j during a recommendation; it reads this snapshot and
the shared `did_effort_similarity_cache.joblib`. Recommendations are decision
support only; review the displayed snapshot time, scope gaps, and similar
historical DIDs before assigning work. Set `DU_TEAM_HISTORY_SNAPSHOT_PATH` to
use a persistent writable snapshot location in RSC. When using the default
Git-tracked snapshot, RSC automatically downloads its full Git LFS content on
first use. `DU_TEAM_HISTORY_SNAPSHOT_URL` can override its download URL.
See the full [DU Team recommendation metric definition](docs/du_team_recommendation.md).

### TLF-only person allocation

The **Allocate TLF People** tab uses the same Excel/CSV upload format but only
its TLF rows, and recommends distinct Generation/QC primaries plus backups from
a separate manually refreshed Person × TLF evidence snapshot:

```cmd
py tlf_person_allocation.py refresh-snapshot
```

It never queries Neo4j at UI runtime. See [TLF person allocation](docs/tlf_person_allocation.md)
for snapshot schema, strict LLM Team Lead validation, scoring, and balancing.

The presentation layer labels only unambiguous returned fields: `hours`,
`recorded_hours`, and `time_on_hours` mean recorded `TIME_ON` hours;
`task_count` means assigned task count. It does not infer units for other
fields.

### RSC model artifact loading

The v3 model and similarity cache are tracked in GitHub with Git LFS. Git-backed
RSC deployments may receive only their small LFS pointer files. On the first
prediction request, the app detects that condition and downloads both artifacts
from this repository's `main` branch to a writable local cache. Later requests
reuse the cached copies within that RSC runtime.

The default artifact URLs work for this repository. These optional RSC Vars can
override them or configure a private repository:

- `DID_EFFORT_MODEL_URL`
- `DID_EFFORT_SIMILARITY_CACHE_URL`
- `DID_EFFORT_ARTIFACT_CACHE_DIR`
- `GITHUB_TOKEN` (only when the artifact URLs require authentication)

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
