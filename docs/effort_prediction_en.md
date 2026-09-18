# DID Individual Effort Prediction: Technical Guide

This document explains how `effort_prediction.py` retrieves data from Neo4j, prepares training samples, constructs individual-efficiency and task-similarity features, trains a regression model, and predicts the total individual effort for DIDs that have not yet been delivered.

## 1. Prediction Target

The current model predicts:

> The total hands-on hours required for a person to complete their assigned tasks in a Planned or Ongoing DID.

Each sample has the following granularity:

```text
Person × Delivery
```

The training label is:

```text
actual_hours = the person's total hours recorded against the DID through TIME_ON
```

The current model does not predict:

- calendar days from start to delivery;
- the effort required by the team to complete the entire DID;
- remaining effort from today onward;
- separate Generation or QC effort.

Predicting remaining effort requires historical snapshots of task scope and cumulative effort at specific dates, together with a separately trained remaining-hours model.

## 2. End-to-End Processing Flow

```text
Neo4j
  │
  │ read-only Cypher
  ▼
Raw Person × Completed DID records
  │
  ├─ Data-quality report
  ├─ Training-eligibility filtering
  └─ Field normalization
  ▼
Sort by actual completion date
  │
  ├─ Historical individual efficiency
  ├─ Historical team efficiency
  ├─ TLF/ADaM/SDTM similarity
  └─ DID/Study categorical features
  ▼
Ridge Regression
  │
  ├─ 70% of DIDs: training
  ├─ 15% of DIDs: P80/P90 calibration
  └─ 15% of DIDs: final testing
  ▼
Save joblib model file
  │
  ▼
Read Planned/Ongoing DIDs
  │
  ▼
Return P50/P80/P90 hours and similar historical DIDs
```

## 3. Configuring Neo4j

The program uses `neo4j_client.load_env()` to load `.env` automatically from the project root:

```dotenv
NEO4J_URI=bolt://your-neo4j-host:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
NEO4J_DATABASE=neo4j
```

Do not put real passwords in Python, the README, or Git commits. The project `.gitignore` excludes `.env`.

The connection flow is:

1. `load_env()` reads `.env`;
2. `get_driver()` creates the Neo4j Driver;
3. `_read_query()` creates a Session for the configured database;
4. `session.execute_read()` runs the query in a read-only transaction;
5. the Driver is closed after the query completes.

## 4. Extracting Training Data from Neo4j

Run:

```powershell
py .\effort_prediction.py extract `
  --output .\data\did_effort_training.json
```

The entry point calls the following in order:

```text
main()
  └─ load_training_records()
       ├─ _read_query(TRAINING_PEOPLE_QUERY)
       ├─ run _read_query(TRAINING_QUERY) separately for each person
       └─ _normalize_record()
```

Training data is extracted per person through multiple independent read-only transactions rather than aggregating the entire database in one transaction. This significantly reduces peak Neo4j transaction memory. If one person still has a very large history, extraction can be batched further by person and completion year. If other concurrent queries have already exhausted the Neo4j memory pool, wait for those transactions to finish or ask the database administrator to adjust server resources.

### 4.1 Training Record Scope

The training query starts with:

```cypher
MATCH (p:Person)-[wo:WORKS_ON]->(d:Delivery)
WHERE toLower(toString(d.DID_Status)) = 'completed'
```

Only Completed DIDs can provide a final total-effort label. Current cumulative effort for Planned and Ongoing DIDs is not a final outcome and therefore cannot be used as an ordinary regression label.

### 4.2 Individual Task Volume

The program reads these properties from the `WORKS_ON` relationship:

- `Task_Num_Total`
- `Task_Num_Generation`
- `Task_Num_QC`
- `TLF_Num_Total`
- `TLF_Num_Generation`
- `TLF_Num_QC`
- `ADaM_Num_Total`
- `ADaM_Num_Generation`
- `ADaM_Num_QC`
- `SDTM_Num_Total`
- `SDTM_Num_Generation`
- `SDTM_Num_QC`

Some records in the actual graph use a `CSR_` prefix, such as `CSR_TLF_Num_Total`. The query uses `coalesce()` to support both unprefixed and `CSR_`-prefixed properties, preferring the unprefixed property:

```cypher
coalesce(wo.TLF_Num_Total, wo.CSR_TLF_Num_Total)
```

The query also counts `workOnRelCount`. Normally, there should be only one `WORKS_ON` relationship between a Person and a Delivery. Records with duplicate relationships are excluded during cleaning.

### 4.3 Actual-Effort Label

Actual effort comes from:

```cypher
(Person)-[TIME_ON]->(DIDN_Month)-[:BELONGS_TO]->(Delivery)
```

The query calculates the following in a separate subquery:

```cypher
sum(toFloat(time.Hour)) AS actualHours
```

This ultimately maps to the Python field:

```text
actual_hours
```

`TIME_ON` must be aggregated in a separate subquery. Directly matching `TIME_ON`, `HAS_TLF`, `HAS_ADAM`, and `HAS_SDTM` in sequence would produce a Cartesian product and count the same hours multiple times.

### 4.4 Study and Delivery Properties

The program reads these categorical properties:

- `Study_Info.TA`
- `Study_Info.Study_Type`
- `Delivery.Reporting_Event`
- `Delivery.Draft_or_Final`

These fields represent effort differences that may arise across therapeutic areas, Study types, and delivery scenarios.

The model does not use these post-outcome fields:

- `Actual_Delivery_Date` as a numeric feature;
- final `Quality`;
- information that can only be confirmed after completion.

`Actual_Delivery_Date` is used only for ordering, temporal splitting, and preventing future-information leakage.

### 4.5 TLF, ADaM, and SDTM Details

The program reads the three detail types in separate subqueries:

```text
(Delivery)-[HAS_TLF]->(TLF)
(Delivery)-[HAS_ADAM]->(ADAM)
(Delivery)-[HAS_SDTM]->(SDTM)
```

Node labels in the actual database are case-sensitive and use `ADaM`; consequently, the implementation's Cypher uses:

```cypher
(Delivery)-[:HAS_ADAM]->(item:ADaM)
```

Writing `(item:ADAM)` will not match these nodes.

Each detail contains:

- name;
- Category;
- Type;
- TLF Source;
- Generation assignee;
- QC assignee.

These details are not used directly as a large collection of one-hot features. Instead, they are used to calculate overlap and similarity between the person's current and historical tasks.

### 4.6 Export File Structure

The exported JSON contains:

```json
{
  "extracted_at": "2026-09-10T20:00:00+08:00",
  "quality": {},
  "records": []
}
```

Running `extract` and `train` separately has these benefits:

- the data can be reviewed manually before training;
- a reproducible data snapshot can be retained;
- model experiments do not need to query Neo4j every time;
- different model versions are easier to compare.

`data/` is excluded by `.gitignore`.

## 5. Data-Quality Checks and Cleaning

### 5.1 Data-Quality Report

`quality_report()` outputs:

- total record count;
- unique person count;
- unique DID count;
- count with missing completion dates;
- count with missing effort;
- count with non-positive effort;
- duplicate Person-DID count;
- duplicate `WORKS_ON` relationship count;
- count of Deliveries associated with multiple Studies;
- count with no `TIME_ON` records;
- count of records with negative task counts.

The data-quality report does not modify Neo4j automatically; it is used only to identify problems.

### 5.2 Training-Eligibility Rules

`clean_training_records()` retains only records where:

- Person is not empty;
- DID is not empty;
- `completion_date` exists and can be parsed;
- `actual_hours > 0`;
- the Person-DID has exactly one `WORKS_ON` relationship;
- the Delivery is associated with at most one Study.

This ensures that zero effort, missing effort, and duplicate relationships are not silently treated as valid training samples.

### 5.3 Numeric Normalization

`_number()` converts Neo4j integers, floating-point numbers, or numeric strings into Python `float` values.

The following values raise errors:

- nonnumeric strings;
- `NaN`;
- positive or negative infinity.

Missing task counts are currently converted to `0.0`. This is appropriate when null means “no task of this type.” If null actually means “unknown” in the database, perform data governance first or add a dedicated missing indicator in a future version.

## 6. Time-Safe Feature Engineering

Features are generated by `build_feature_row()`.

For a target record, usable history must satisfy:

```text
historical completion_date < target date
```

The comparison is strictly less than; records completed on the same day or in the future are not allowed.

During training, the target date is the training sample's own `completion_date`. During prediction, it is the user-provided `as_of_date`, which defaults to the current date.

### 6.1 Current DID Workload Features

The model directly uses twelve task-volume fields:

```text
task_count
task_generation_count
task_qc_count
tlf_count
tlf_generation_count
tlf_qc_count
adam_count
adam_generation_count
adam_qc_count
sdtm_count
sdtm_generation_count
sdtm_qc_count
```

Task volume is the most fundamental explanatory variable for predicting effort. Similarity cannot be used independently of task scale; otherwise, “large DIDs have many overlapping items” could be misinterpreted as “large DIDs require less effort.”

### 6.2 Individual Historical Efficiency

Only DIDs completed by the person before the target date are used:

```text
person_completed_count
person_median_hours
person_recent_median_hours
person_median_hours_per_task
```

Meanings:

- `person_completed_count`: the person's number of previously eligible DIDs;
- `person_median_hours`: median total effort across the person's historical DIDs;
- `person_recent_median_hours`: median effort across the person's five most recent historical DIDs;
- `person_median_hours_per_task`: the person's historical median effort per task.

Medians are used instead of means to reduce the effect of a small number of DIDs with exceptionally high effort.

### 6.3 Team Historical Efficiency

The model also calculates:

```text
global_completed_count
global_median_hours
global_median_hours_per_task
```

When a person has little or no history, the model can still rely on overall team experience rather than being unable to predict.

### 6.4 Person-Specific Task Sets

`_item_set()` first checks the Generation and QC assignees on the TLF/ADaM/SDTM relationships.

If the person can be identified in the detail records, only items actually assigned to that person are retained. If usable assignment information is unavailable on the relationships, the program falls back to the entire DID detail set; this should be recognized as a weaker approximation when interpreting results.

Names are normalized by `_normalized_name()`:

```text
convert to uppercase → remove spaces and non-alphanumeric characters
```

For example:

```text
Table 14.1-1
TABLE_14_1_1
```

Both produce similar normalized forms. Exact set matching remains as an
interpretable baseline feature.

### 6.5 Jaccard Similarity

The target DID is compared separately with each of the person's historical DIDs:

```text
Jaccard(A, B) = |A ∩ B| / |A ∪ B|
```

This produces:

```text
tlf_similarity
adam_similarity
sdtm_similarity
```

The mean is then calculated across types for which task sets exist:

```text
overall_similarity
```

The model uses these features:

```text
max_tlf_similarity
max_adam_similarity
max_sdtm_similarity
max_overall_similarity
```

They represent this person's maximum similarity to historical DIDs.

### 6.6 TLF Title Semantic Approximation

Model v2 adds local title approximation alongside exact Jaccard matching. It
does not call an LLM or external API:

```text
Normalize titles
→ Character 3–5 gram hashing vectors
→ Cosine similarity
→ Combine Type and Source
→ Greedy one-to-one matching at a minimum score of 0.70
```

Each TLF-pair score is primarily title-based:

```text
80% title character n-gram similarity
10% Type match
10% Source match
```

When Type or Source is missing, the score is renormalized over available
fields. A historical TLF can match at most one target TLF, preventing duplicate
credit. The DID-level score divides the sum of matched scores by the larger TLF
count, so unmatched tasks reduce the score.

New features:

```text
max_tlf_semantic_similarity
max_tlf_semantic_coverage
max_combined_similarity
top3_combined_similarity_mean
top5_combined_similarity_mean
similar_did_count_ge_70
similar_did_count_ge_85
weighted_similar_hours
weighted_similar_hours_per_task
latest_similar_hours
similar_hours_trend
```

Historical cases in prediction output include both exact TLF similarity and
title similarity. This is an interpretable lexical-semantic approximation, not
a language-model embedding; truly synonymous titles with entirely different
wording may still be missed.

The repeated-similar-work features mean:

- `top3_combined_similarity_mean` and `top5_combined_similarity_mean`: mean combined similarity of the top 3/5 candidate DIDs;
- `similar_did_count_ge_70` and `similar_did_count_ge_85`: counts of historical DIDs with combined similarity at least 0.70/0.85;
- `weighted_similar_hours`: similarity-weighted mean actual hours among historical DIDs with similarity at least 0.70;
- `weighted_similar_hours_per_task`: weighted mean hours per task for the same history;
- `latest_similar_hours`: actual hours of the most recently completed DID with similarity at least 0.70;
- `similar_hours_trend`: linear hours-per-repeated-experience slope after ordering similar history by completion date. Negative values indicate decreasing historical effort; positive values indicate increasing effort. It is zero with fewer than two similar DIDs.

### 6.7 v2-fast Candidate Filtering and Persistent Cache

Expensive item-by-item TLF title matching now compares the union of:

- the 50 most recent historical DIDs;
- the 100 most recent DIDs in the same Study;
- the 100 most recent DIDs with any exact TLF/ADaM/SDTM overlap;
- the 25 most recent DIDs in the same TA.

This restriction applies only to expensive DID-pair similarity and the repeated-similar-work features above. Personal median effort, historical counts, and prior-item unions still use all eligible personal history before the prediction date.

TLF semantic pair results are keyed by content hashes of the target and historical TLF lists and persisted in `artifacts/did_effort_similarity_cache.joblib`. The cache includes an algorithm version, so changes to the matching algorithm or threshold invalidate old entries. Training checkpoints the cache every 2,000 records, allowing most completed work to survive an interrupted run. Every 500 records, the console reports progress, cache hits/misses, candidate comparisons, and skipped comparisons.

### 6.8 Historical Overlap and Time Interval

The model also uses:

```text
tlf_prior_overlap_count
adam_prior_overlap_count
sdtm_prior_overlap_count
tlf_prior_coverage
adam_prior_coverage
sdtm_prior_coverage
overall_prior_coverage
tlf_unseen_count
adam_unseen_count
sdtm_unseen_count
days_since_similar_work
```

The first three features indicate how many items in the target tasks the person has encountered in historical DIDs.

The `*_prior_coverage` features use the union of that person's tasks across all
historical DIDs. They therefore recognize cases where several historical DIDs
collectively cover the target task set. The `*_unseen_count` features count
target tasks that have never appeared in the person's history.

`days_since_similar_work` is the number of days since the most similar historical DID was completed. Similar work performed recently may have a different reuse value from similar work performed several years ago.

Similarity is not hard-coded as an effort discount. Ridge regression learns from historical data whether similarity reduces, increases, or has little effect on effort.

## 7. Regression Model

### 7.1 Why Ridge Regression Is Used

The current version uses:

```python
Ridge(alpha=1.0)
```

Ridge is linear regression with L2 regularization:

```text
Minimize:

Σ(yᵢ - ŷᵢ)² + αΣβⱼ²
```

where:

- `yᵢ` is the actual label;
- `ŷᵢ` is the model prediction;
- `βⱼ` is a feature coefficient;
- `α` controls regularization strength.

Ridge was selected because it:

- handles correlation among task-count fields better than ordinary linear regression;
- is generally more stable than complex tree models when the sample size is limited;
- provides a clear and reproducible first-version baseline;
- is fast to train and predict;
- can later be compared fairly with Gradient Boosting, CatBoost, or hierarchical models.

### 7.2 Label Transformation

Before training, the model applies:

```python
log1p(actual_hours)
```

That is:

```text
model_target = log(1 + actual_hours)
```

After prediction, it applies:

```python
expm1(prediction)
```

Effort is typically right-skewed: most DIDs have moderate effort, while a small number have very high effort. The logarithmic transformation reduces the dominance of extreme values in squared error.

The final prediction is constrained to be nonnegative with `max(0, prediction)`.

### 7.3 Numeric Preprocessing

Numeric features pass through:

```text
SimpleImputer(strategy="median")
StandardScaler()
```

The process is:

1. fill missing numeric values with the training-set median;
2. transform values to a scale with mean approximately 0 and standard deviation approximately 1;
3. pass them to Ridge.

Standardization is important because Ridge regularization acts directly on coefficients. Without standardization, features with very different scales would be penalized unfairly.

### 7.4 Categorical Preprocessing

The following fields use One-Hot Encoding:

```text
ta
study_type
reporting_event
draft_or_final
```

Unknown categories use:

```python
OneHotEncoder(handle_unknown="ignore")
```

Consequently, a new TA or Reporting Event not seen during training will not cause production prediction to fail.

### 7.5 Pipeline

The preprocessor and Ridge model are stored in the same scikit-learn `Pipeline`:

```text
Raw features
  → Numeric imputation/standardization
  → Categorical One-Hot
  → Ridge Regression
```

This ensures that training and prediction use the same field order, imputation rules, scaling parameters, and categorical encoding, avoiding inconsistencies from manual processing.

### 7.6 Robust Prediction Policy

Version 3 does not use unconstrained Ridge output directly. Using only the
calibration split, it selects:

- the Ridge prediction weight;
- the personal historical-median baseline weight;
- an optional residual offset;
- an optional prediction cap derived from a training-label quantile.

The selected policy minimizes calibration WAPE. The test split is not involved
in policy selection, preventing test leakage. For a person with no history, the
baseline falls back to the global median available before the prediction date.

The training output reports `benchmark_metrics` for:

```text
raw_ridge
person_history_baseline
robust_blend
```

A new model should be promoted only when `robust_blend` beats the simple
baseline.

## 8. Temporal Splitting and Data-Leakage Control

`_grouped_time_split()` first determines the completion date of each DID and then sorts the DIDs by date.

Split proportions:

```text
First 70% of DIDs: training set
Middle 15% of DIDs: interval-calibration set
Last 15% of DIDs: test set
```

The split unit is DID, not an individual Person-DID record. This ensures that records for different people within the same DID cannot appear in both the training and test sets.

At least six distinct Completed DIDs are required for the three-way split. By default, at least twenty eligible Person-DID training records are also required.

The current implementation prevents the following leakage:

- future completed DIDs are not used to calculate individual efficiency;
- same-day completed records are not used as history;
- time order is not randomly shuffled;
- the same DID does not cross partitions;
- numeric imputation, standardization, and category encoding are fitted only on the training set;
- post-outcome information such as final Quality is not used as a model feature.

Note:

> If Neo4j stores only the current final task list for a DID and has no historical scope snapshot, an old sample's task scope may include subsequent changes that were unknown at prediction time.

The current backtest is therefore an approximation based on the existing graph state. Strict production backtesting should retain historical snapshots of every assignment and task-scope change.

## 9. P50, P80, and P90

Ridge first produces a central prediction:

```text
P50 ≈ Ridge point prediction
```

On the calibration set, the model calculates:

```text
residual = actual_hours - predicted_hours
```

It then takes the 80th and 90th percentiles of the residuals:

```text
p80_adjustment = max(0, quantile(residual, 0.80))
p90_adjustment = max(0, quantile(residual, 0.90))
```

Production predictions are:

```text
P80 = P50 + p80_adjustment
P90 = P50 + p90_adjustment
```

Their meanings are:

- P50: the model's central estimate;
- P80: an upper bound for more conservative resource planning;
- P90: a still more conservative resource-planning value.

The current intervals use global residual calibration and do not automatically vary in width by person or task size. When sufficient data becomes available, this can be upgraded to Quantile Regression or conformal prediction.

## 10. Model Evaluation Metrics

The training command reports:

### MAE

```text
MAE = mean(|prediction - actual|)
```

This is the easiest metric to explain to the business: the average number of hours by which predictions differ.

### Median AE

The median absolute error is less sensitive than MAE to a small number of extreme DIDs.

### RMSE

```text
RMSE = sqrt(mean((prediction - actual)²))
```

It penalizes large errors more heavily and is useful for identifying serious underestimation or overestimation.

### WAPE

```text
WAPE = Σ|prediction - actual| / Σactual
```

This is suitable for evaluating the aggregate error in resource planning across the team.

### Bias

```text
Bias = mean(prediction - actual)
```

- Bias greater than zero: overall overestimation;
- Bias less than zero: overall underestimation.

### P80/P90 Coverage

```text
coverage = proportion of test samples whose actual effort is less than or equal to the predicted upper bound
```

Ideally, for example, P80 coverage should be close to 80%. Coverage fluctuates when the test dataset is small, so the test sample size must also be reported.

## 11. Training and Model Persistence

Run:

```powershell
py .\effort_prediction.py train `
  --input .\data\did_effort_training.json `
  --model .\artifacts\did_effort_model.joblib `
  --cache .\artifacts\did_effort_similarity_cache.joblib
```

If `--input` is omitted, the program reads training records directly from Neo4j:

```powershell
py .\effort_prediction.py train `
  --model .\artifacts\did_effort_model.joblib `
  --cache .\artifacts\did_effort_similarity_cache.joblib
```

For production, retaining the two-stage `extract → manual review → train` process is recommended.

The saved joblib artifact contains:

- model version;
- training time;
- complete scikit-learn Pipeline;
- eligible historical records;
- numeric and categorical feature lists;
- P80/P90 adjustments;
- the calibrated Ridge/personal-baseline blend and prediction-cap policy;
- test metrics for raw Ridge, the personal baseline, and the robust blend;
- test metrics;
- train/calibration/test sample and DID counts.

`artifacts/` is excluded by `.gitignore`.

## 12. Predicting an Undelivered DID

Run:

```powershell
py .\effort_prediction.py predict `
  --model .\artifacts\did_effort_model.joblib `
  --person "Chen, Sizhen" `
  --did "DID123"
```

To specify a historical prediction date:

```powershell
py .\effort_prediction.py predict `
  --model .\artifacts\did_effort_model.joblib `
  --person "Chen, Sizhen" `
  --did "DID123" `
  --as-of-date "2026-09-10"
```

### 12.1 Target Query

The target must satisfy:

```text
DID_Status ∈ {Planned, Ongoing}
```

Neo4j must also contain:

```text
(Person)-[:WORKS_ON]->(Delivery)
```

The target query reads the same fields as the training stage:

- twelve task-volume fields;
- TA and Study Type;
- Reporting Event;
- Draft/Final;
- TLF, ADaM, and SDTM details.

It does not read the target's final effort.

### 12.2 Historical Scope at Prediction Time

The model file stores the training history. During prediction, it is filtered again:

```text
completion_date < as_of_date
```

Therefore, even if the model file contains history later than the specified `as_of_date`, those records are not used for that prediction's dynamic individual-efficiency and similarity features.

Note that the model coefficients are still fitted using the complete training set available before the model's training date. Thus, `--as-of-date` controls the feature-history scope but cannot turn the current model into a strict historical point-in-time model. Strict historical backtesting requires retraining the model at every historical cutoff.

### 12.3 Returned Result

Example:

```json
{
  "person": "Chen, Sizhen",
  "did": "DID123",
  "prediction_type": "total_hours",
  "as_of_date": "2026-09-10",
  "p50_hours": 42.0,
  "p80_hours": 56.0,
  "p90_hours": 63.0,
  "model_version": "did-effort-ridge-v1",
  "person_completed_did_count": 8,
  "similar_historical_dids": [],
  "warnings": []
}
```

The program returns up to five of the person's most similar historical DIDs, including:

- DID;
- Study;
- completion date;
- actual effort;
- TLF/ADaM/SDTM similarity;
- overall similarity.

### 12.4 Prediction Warnings

A warning is produced when:

- the person has fewer than five Completed DIDs before the prediction date;
- global history before the prediction date contains fewer than twenty records;
- the target DID has no usable TLF/ADaM/SDTM details.

The business presentation layer should not hide these warnings.

## 13. Agent Integration

An Agent or another Python module can call the function directly:

```python
from effort_prediction import predict_effort

result = predict_effort(
    person="Chen, Sizhen",
    did="DID123",
    as_of_date="2026-09-10",
)
```

Recommended separation of responsibilities:

```text
LLM Agent
  ├─ Identify person name, DID, and as-of date
  ├─ Call predict_effort()
  └─ Explain the returned result and warnings in business language

Python model
  ├─ Query data
  ├─ Calculate features
  ├─ Run regression
  └─ Return predictions and similar cases
```

The LLM must not calculate the regression itself, modify P50/P80/P90, or fabricate a prediction value if the model fails.

### 13.1 The Q&A Agent Is Now Integrated

The `ask()` function in `agent.py` now includes prediction routing. Questions
that explicitly contain prediction intent such as `predict`, `forecast`, `预测`,
or `预计` use the effort model. Ordinary historical-hours questions continue
through the existing Text-to-Cypher flow.

For example, enter this directly in the Streamlit chat:

```text
Predict Riven's effort for C5001001_59.
```

Processing flow:

```text
Detect prediction intent
→ Extract Person, DID, and optional as-of date
→ Read the current Planned/Ongoing DID scope from Neo4j
→ Load and cache artifacts/did_effort_model.joblib
→ Compute P50/P80/P90 in Python
→ Render the result with a fixed Agent response template
```

Common Chinese and English requests are parsed locally without consuming LLM
tokens. Complex wording falls back to Vox for parameter extraction. The model
cache is keyed by the file modification time, so a newly published model is
loaded automatically.

## 14. Recommended First-Run Procedure

### Step 1: Confirm the Connection

Verify that `.env` is in the project root and that its filename is not `.env.txt`.

### Step 2: Export Data

```powershell
py .\effort_prediction.py extract `
  --output .\data\did_effort_training.json
```

### Step 3: Review the Quality Report

Pay particular attention to:

- `record_count`
- `missing_actual_hours`
- `non_positive_actual_hours`
- `duplicate_person_did`
- `duplicate_work_on_relationships`
- `multiple_studies`
- `no_time_records`

If many records are excluded, fix the data or clarify the business rules first; do not simply weaken the cleaning criteria.

### Step 4: Train

```powershell
py .\effort_prediction.py train `
  --input .\data\did_effort_training.json `
  --model .\artifacts\did_effort_model.joblib `
  --cache .\artifacts\did_effort_similarity_cache.joblib
```

### Step 5: Review Metrics

At minimum, check:

- whether MAE outperforms the “global historical median” baseline;
- whether WAPE meets resource-planning needs;
- whether Bias is materially negative;
- whether P80/P90 coverage is close to the targets;
- whether the numbers of test DIDs and test records are sufficient.

### Step 6: Predict a Real Case

Choose a Planned/Ongoing DID with a known task scope, run a prediction, and ask business experts to verify:

- whether task volumes are correct;
- whether similar historical DIDs are reasonable;
- whether the person's historical record count is correct;
- whether P50 and P80 are interpretable for the business.

## 15. Current Limitations and Next Improvements

### Current Limitations

1. When `TIME_ON` does not distinguish Generation from QC, only combined effort can be predicted.
2. Monthly effort may not be divisible precisely by task completion date.
3. Without scope snapshots, strict historical backtesting is limited.
4. TLF title approximation uses character n-grams rather than embeddings and cannot fully understand deep semantics.
5. Current P80/P90 values use global residual adjustments, so interval width does not vary with sample uncertainty.
6. The current model uses aggregated Person-DID labels and cannot determine how much effort a specific TLF consumed.
7. Individual-history features do not share records completed on the same day; this is a conservative anti-leakage strategy.

### Recommended Improvement Order

1. Establish snapshots of task scope and prediction points in time;
2. record task-level Generation/QC effort;
3. establish standard cross-Study IDs for TLF/ADaM/SDTM;
4. add fields for spec changes, rework, data delays, and code reuse;
5. compare against simple business rules and a global-median baseline;
6. compare CatBoost, Gradient Boosting, and hierarchical models when enough data is available;
7. improve intervals with Quantile Regression or conformal prediction;
8. establish model versioning, drift monitoring, and periodic retraining.

## 16. File Locations

```text
effort_prediction.py             Main program
test_effort_prediction.py        Unit tests
neo4j_client.py                  Neo4j connection and .env loading
requirements.txt                 Python dependencies
data/                            Exported training data; not committed to Git
artifacts/                       Trained models; not committed to Git
docs/effort_prediction.md        Chinese documentation
docs/effort_prediction_en.md     English documentation
```

Run tests:

```powershell
py -m unittest -v .\test_effort_prediction.py
```
