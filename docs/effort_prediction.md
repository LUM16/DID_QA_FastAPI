# DID 个人工时预测技术说明

本文说明 `effort_prediction.py` 如何从 Neo4j 获取数据、整理训练样本、构造个人效率与任务相似度特征、训练回归模型，以及预测尚未交付 DID 的个人总工时。

## 1. 预测目标

当前模型预测：

> 某个人完成某个 Planned 或 Ongoing DID 中已分配任务所需的总 hands-on hours。

一个样本的粒度是：

```text
Person × Delivery
```

训练标签是：

```text
actual_hours = 该人员通过 TIME_ON 记录在该 DID 上的总工时
```

当前模型预测的不是：

- 从开始到交付的日历天数；
- 团队完成整个 DID 的工时；
- 从今天开始的剩余工时；
- 独立的 Generation 或 QC 工时。

如果需要预测剩余工时，应保存历史日期上的任务范围和累计工时快照，并单独训练 remaining-hours 模型。

## 2. 完整处理流程

```text
Neo4j
  │
  │ 只读 Cypher
  ▼
Person × Completed DID 原始记录
  │
  ├─ 数据质量报告
  ├─ 训练资格过滤
  └─ 字段标准化
  ▼
按实际完成日期排序
  │
  ├─ 历史个人效率
  ├─ 历史团队效率
  ├─ TLF/ADaM/SDTM 相似度
  └─ DID/Study 类别特征
  ▼
Ridge Regression
  │
  ├─ 70% DID：训练
  ├─ 15% DID：P80/P90 校准
  └─ 15% DID：最终测试
  ▼
保存 joblib 模型文件
  │
  ▼
读取 Planned/Ongoing DID
  │
  ▼
返回 P50/P80/P90 工时和相似历史 DID
```

## 3. 配置 Neo4j

程序通过 `neo4j_client.load_env()` 自动读取项目根目录的 `.env`：

```dotenv
NEO4J_URI=bolt://your-neo4j-host:7687
NEO4J_USERNAME=neo4j
NEO4J_PASSWORD=your-password
NEO4J_DATABASE=neo4j
```

不要把真实密码写进 Python、README 或提交到 Git。项目的 `.gitignore` 已排除 `.env`。

连接流程如下：

1. `load_env()` 读取 `.env`；
2. `get_driver()` 创建 Neo4j Driver；
3. `_read_query()` 创建指定数据库的 Session；
4. `session.execute_read()` 在只读事务中运行查询；
5. 查询结束后关闭 Driver。

## 4. 从 Neo4j 抽取训练数据

运行：

```powershell
py .\effort_prediction.py extract `
  --output .\data\did_effort_training.json
```

入口依次调用：

```text
main()
  └─ load_training_records()
       ├─ _read_query(TRAINING_PEOPLE_QUERY)
       ├─ 按人员逐个运行 _read_query(TRAINING_QUERY)
       └─ _normalize_record()
```

训练数据按人员使用多个独立只读事务抽取，而不是在一个事务中聚合整个数据库。
这样可以显著降低 Neo4j transaction memory 的峰值。如果单个人员仍拥有非常大的
历史范围，可继续改为按人员和完成年份分批。Neo4j 的内存池若已被其他并发查询占满，
则仍需等待其他事务结束或由数据库管理员调整服务器资源。

### 4.1 训练记录范围

训练查询从以下关系开始：

```cypher
MATCH (p:Person)-[wo:WORKS_ON]->(d:Delivery)
WHERE toLower(toString(d.DID_Status)) = 'completed'
```

只有 Completed DID 可以提供最终总工时标签。Planned 和 Ongoing DID 的当前累计工时不是最终结果，因此不能作为普通回归标签。

### 4.2 个人任务量

程序从 `WORKS_ON` 关系读取：

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

实际图中部分记录使用 `CSR_` 前缀，例如 `CSR_TLF_Num_Total`。
查询通过 `coalesce()` 同时兼容无前缀和 `CSR_` 前缀的属性，并优先使用无前缀字段：

```cypher
coalesce(wo.TLF_Num_Total, wo.CSR_TLF_Num_Total)
```

查询同时统计 `workOnRelCount`。正常情况下，一个 Person 和一个 Delivery 之间应只有一条 `WORKS_ON` 关系。存在重复关系的记录会在清洗时被排除。

### 4.3 实际工时标签

实际工时来自：

```cypher
(Person)-[TIME_ON]->(DIDN_Month)-[:BELONGS_TO]->(Delivery)
```

查询在独立子查询中计算：

```cypher
sum(toFloat(time.Hour)) AS actualHours
```

最终对应 Python 字段：

```text
actual_hours
```

`TIME_ON` 必须在独立子查询中聚合。如果直接把 `TIME_ON`、`HAS_TLF`、`HAS_ADAM` 和 `HAS_SDTM` 连续 MATCH 在一起，会产生笛卡尔积，使相同工时被重复相加。

### 4.4 Study 和 Delivery 属性

程序读取以下类别属性：

- `Study_Info.TA`
- `Study_Info.Study_Type`
- `Delivery.Reporting_Event`
- `Delivery.Draft_or_Final`

这些字段用于表示不同治疗领域、Study 类型和交付场景可能带来的工时差异。

模型没有使用以下事后字段：

- `Actual_Delivery_Date` 作为数值特征；
- 最终 `Quality`；
- 完成后才能确认的信息。

`Actual_Delivery_Date` 只用于排序、时间切分和防止未来信息泄漏。

### 4.5 TLF、ADaM 和 SDTM 明细

程序分别使用三个独立子查询读取：

```text
(Delivery)-[HAS_TLF]->(TLF)
(Delivery)-[HAS_ADAM]->(ADAM)
(Delivery)-[HAS_SDTM]->(SDTM)
```

实际数据库中的节点标签为大小写敏感的 `ADaM`，因此实现中的 Cypher 使用：

```cypher
(Delivery)-[:HAS_ADAM]->(item:ADaM)
```

写成 `(item:ADAM)` 将不会匹配这些节点。

每条明细包含：

- 名称；
- Category；
- Type；
- TLF Source；
- Generation 人员；
- QC 人员。

这些明细不会直接作为大量 one-hot 特征，而是用于计算此人与历史任务之间的重合和相似度。

### 4.6 导出文件结构

导出的 JSON 包含：

```json
{
  "extracted_at": "2026-09-10T20:00:00+08:00",
  "quality": {},
  "records": []
}
```

分开执行 `extract` 和 `train` 有以下好处：

- 可以在训练前人工检查数据；
- 可以保留一次可复现的数据快照；
- 模型实验不需要每次重新查询 Neo4j；
- 更容易比较不同模型版本。

`data/` 已被 `.gitignore` 排除。

## 5. 数据质量检查和清洗

### 5.1 数据质量报告

`quality_report()` 输出：

- 总记录数；
- 唯一人员数；
- 唯一 DID 数；
- 缺失完成日期数量；
- 缺失工时数量；
- 非正工时数量；
- 重复 Person-DID；
- 重复 `WORKS_ON` 关系数量；
- 一个 Delivery 关联多个 Study 的数量；
- 没有 `TIME_ON` 记录的数量；
- 存在负任务数的记录数量。

数据质量报告不会自动修改 Neo4j，只用于发现问题。

### 5.2 训练资格规则

`clean_training_records()` 只保留：

- Person 不为空；
- DID 不为空；
- `completion_date` 存在且可解析；
- `actual_hours > 0`；
- Person-DID 只有一条 `WORKS_ON`；
- Delivery 最多关联一个 Study。

这意味着零工时、缺失工时和重复关系不会被静默当成正常训练样本。

### 5.3 数值标准化

`_number()` 把 Neo4j 整数、浮点数或数字字符串转成 Python `float`。

以下值会报错：

- 非数字字符串；
- `NaN`；
- 正无穷或负无穷。

缺失任务数当前转换为 `0.0`。这适合表示“没有该类型任务”，但如果数据库中 null 实际表示“未知”，应先进行数据治理，或者在以后版本增加专门的 missing indicator。

## 6. 时间安全的特征工程

特征由 `build_feature_row()` 生成。

对于目标记录，其可用历史必须满足：

```text
historical completion_date < target date
```

这里使用严格小于，不允许使用同一天完成或未来完成的记录。

训练时，目标日期是该训练样本自己的 `completion_date`。预测时，目标日期是用户提供的 `as_of_date`，默认是当天。

### 6.1 当前 DID 工作量特征

模型直接使用十二个任务量字段：

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

任务量是预测工时最基础的解释变量。相似度不能脱离任务规模单独使用，否则“大 DID 因为重合项多”可能被错误解释成“更省工时”。

### 6.2 个人历史效率

只使用该人员在目标日期之前完成的 DID：

```text
person_completed_count
person_median_hours
person_recent_median_hours
person_median_hours_per_task
```

含义：

- `person_completed_count`：此人此前符合资格的 DID 数量；
- `person_median_hours`：此人历史 DID 总工时中位数；
- `person_recent_median_hours`：此人最近五个历史 DID 的工时中位数；
- `person_median_hours_per_task`：此人历史每任务工时中位数。

使用中位数而不是平均数，是为了降低少量异常高工时 DID 的影响。

### 6.3 团队历史效率

模型同时计算：

```text
global_completed_count
global_median_hours
global_median_hours_per_task
```

当某人的历史很少或完全没有历史时，模型仍可依赖团队整体经验，而不是无法预测。

### 6.4 人员相关的任务集合

`_item_set()` 首先检查 TLF/ADaM/SDTM 关系上的 `Generation` 和 `QC` 人员。

如果明细中能够识别该人员，则只保留该人员实际承担的项目。如果关系上没有可用的人员分配信息，程序退回到整个 DID 的明细集合，并在解释时应认识到这是较弱的近似。

名称通过 `_normalized_name()` 标准化：

```text
转成大写 → 删除空格和非字母数字字符
```

例如：

```text
Table 14.1-1
TABLE_14_1_1
```

都会得到接近的标准形式。精确集合匹配仍保留，作为可解释的基准特征。

### 6.5 Jaccard 相似度

目标 DID 与每一个个人历史 DID 分别计算：

```text
Jaccard(A, B) = |A ∩ B| / |A ∪ B|
```

分别得到：

```text
tlf_similarity
adam_similarity
sdtm_similarity
```

再对存在任务集合的类型求平均：

```text
overall_similarity
```

模型特征使用：

```text
max_tlf_similarity
max_adam_similarity
max_sdtm_similarity
max_overall_similarity
```

也就是此人与历史 DID 的最大相似度。

### 6.6 TLF 标题语义近似

模型 v2 在精确 Jaccard 之外增加本地标题近似，不调用 LLM 或外部 API：

```text
标题标准化
→ 字符 3–5 gram 哈希向量
→ Cosine similarity
→ 结合 Type 和 Source
→ 相似度至少 0.70 的一对一贪心匹配
```

单个 TLF 对的分数以标题为主：

```text
80% 标题字符 n-gram 相似度
10% Type 匹配
10% Source 匹配
```

当 Type 或 Source 缺失时，仅在可用字段上重新归一化。一个历史 TLF 最多只能匹配
一个目标 TLF，避免同一项目被重复计算。DID 级分数用匹配得分总和除以两侧较大的
TLF 数量，因此未匹配的任务会降低总体分数。

新增特征：

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

预测结果中的历史案例同时展示精确 TLF 相似度和标题近似度。这属于可解释的词面语义
近似，并不等同于语言模型 embedding；名称完全不同的真正同义标题仍可能漏匹配。

其中重复相似工作特征的含义是：

- `top3_combined_similarity_mean`、`top5_combined_similarity_mean`：最相似 3/5 个候选 DID 的平均综合相似度；
- `similar_did_count_ge_70`、`similar_did_count_ge_85`：综合相似度分别达到 0.70/0.85 的历史 DID 数；
- `weighted_similar_hours`：以综合相似度为权重，对相似度至少 0.70 的历史实际工时求加权平均；
- `weighted_similar_hours_per_task`：同一批历史 DID 的每任务工时加权平均；
- `latest_similar_hours`：最近一个相似度至少 0.70 的历史 DID 实际工时；
- `similar_hours_trend`：按完成时间排列相似历史 DID 后，每多一次相似经历对应的实际工时线性斜率。负值表示历史上逐次减少，正值表示逐次增加；少于两个相似 DID 时为 0。

### 6.7 v2-fast 候选筛选和持久缓存

昂贵的 TLF 标题逐项匹配不再遍历某人的全部历史，而是比较以下候选的并集：

- 最近 50 个历史 DID；
- 最近 100 个同 Study DID；
- 最近 100 个存在精确 TLF/ADaM/SDTM 重合的 DID；
- 最近 25 个同 TA DID。

限制只作用于昂贵的 DID 间相似度和上述重复相似工作特征。个人中位工时、历史数量以及历史任务并集仍使用预测日期之前的全部合格个人历史。

TLF 语义匹配结果按目标/历史 TLF 清单的内容哈希保存到
`artifacts/did_effort_similarity_cache.joblib`。缓存包含算法版本；匹配算法或阈值升级后，旧缓存会自动失效。训练期间每 2,000 条记录检查点保存一次，因此中断后也可以复用大部分已完成计算。控制台每 500 条记录报告进度、cache hit/miss、候选比较数和跳过数。

### 6.8 历史重合和时间间隔

模型还使用：

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

前三个特征表示目标任务中有多少项曾经由此人在历史 DID 中遇到。

`*_prior_coverage` 使用该人员全部历史 DID 的任务并集作为分母，能够识别“目标
TLF 分别出现在多个历史 DID 中”的组合覆盖场景。`*_unseen_count` 表示目标中从未
出现过的任务数量。

`days_since_similar_work` 表示距离最相似历史 DID 完成的天数。近期做过相似任务和多年以前做过相似任务可能具有不同复用价值。

相似度没有被硬编码成工时折扣。Ridge 回归根据历史数据学习相似度究竟降低、增加还是基本不影响工时。

## 7. 回归模型

### 7.1 为什么使用 Ridge Regression

当前版本使用：

```python
Ridge(alpha=1.0)
```

Ridge 是带 L2 正则化的线性回归：

```text
最小化：

Σ(yᵢ - ŷᵢ)² + αΣβⱼ²
```

其中：

- `yᵢ` 是真实标签；
- `ŷᵢ` 是模型预测；
- `βⱼ` 是各特征系数；
- `α` 控制正则化强度。

选择 Ridge 的原因：

- 比普通线性回归更能处理任务数字段之间的相关性；
- 在样本量有限时通常比复杂树模型稳定；
- 可作为清晰、可重复的第一版基准；
- 训练和预测速度快；
- 后续可与 Gradient Boosting、CatBoost 或层级模型公平比较。

### 7.2 标签变换

训练模型前执行：

```python
log1p(actual_hours)
```

即：

```text
model_target = log(1 + actual_hours)
```

预测后执行：

```python
expm1(prediction)
```

原因是工时通常右偏：大多数 DID 工时适中，少数 DID 工时非常大。对数变换能够降低极端值对平方误差的支配。

最终预测通过 `max(0, prediction)` 限制为非负数。

### 7.3 数值预处理

数值特征通过：

```text
SimpleImputer(strategy="median")
StandardScaler()
```

处理流程：

1. 缺失数值以训练集中的中位数填充；
2. 转换成均值约为 0、标准差约为 1 的尺度；
3. 送入 Ridge。

标准化很重要，因为 Ridge 的正则化直接作用于系数。如果不同特征量纲差异很大，未标准化会导致不公平的惩罚。

### 7.4 类别预处理

以下字段通过 One-Hot Encoding：

```text
ta
study_type
reporting_event
draft_or_final
```

未知类别使用：

```python
OneHotEncoder(handle_unknown="ignore")
```

因此生产预测出现训练时未见过的新 TA 或 Reporting Event 时，不会导致程序崩溃。

### 7.5 Pipeline

预处理器和 Ridge 被保存在同一个 scikit-learn `Pipeline`：

```text
原始特征
  → 数值填充/标准化
  → 类别 One-Hot
  → Ridge Regression
```

这样训练与预测一定使用相同的字段顺序、填充规则、标准化参数和类别编码，避免手工处理不一致。

### 7.6 稳健预测策略

v3 不直接使用未经约束的 Ridge 输出。程序仅使用校准集自动选择：

- Ridge 预测权重；
- 个人历史中位数基准权重；
- 可选的残差偏移；
- 根据训练标签分位数确定的预测上限。

选择目标是校准集 WAPE 最低。测试集不参与策略选择，因此不会泄漏测试结果。
若某人没有历史记录，个人基准自动回退到预测日期前的全局中位工时。

训练输出中的 `benchmark_metrics` 同时报告：

```text
raw_ridge
person_history_baseline
robust_blend
```

只有 `robust_blend` 优于简单基准时，才应将新模型用于正式预测。

## 8. 时间切分和数据泄漏控制

`_grouped_time_split()` 先找出每个 DID 的完成日期，再按日期排序。

切分比例：

```text
前 70% DID：训练集
中间 15% DID：区间校准集
最后 15% DID：测试集
```

切分单位是 DID，不是单条 Person-DID 记录。这保证同一个 DID 中不同人员的记录不会同时出现在训练集和测试集。

至少需要六个不同的 Completed DID 才能进行三段切分。默认还要求至少二十条符合资格的 Person-DID 训练记录。

当前实现防止以下泄漏：

- 不使用未来完成 DID 计算个人效率；
- 不使用同日完成记录作为历史；
- 不随机打乱时间；
- 同一 DID 不跨分区；
- 数值填充、标准化和类别编码只由训练集拟合；
- 不把最终 Quality 等事后信息作为模型特征。

需要注意：

> 如果 Neo4j 只保存 DID 当前最终任务清单，而没有历史 scope snapshot，旧样本的任务范围可能包含预测当时尚不知道的后续变化。

因此当前回测属于基于现有图状态的近似。严格的生产回测应保存每次分配和任务范围变化的历史快照。

## 9. P50、P80 和 P90

Ridge 先产生中心预测：

```text
P50 ≈ Ridge point prediction
```

校准集上计算：

```text
residual = actual_hours - predicted_hours
```

然后取 residual 的第 80 和第 90 百分位：

```text
p80_adjustment = max(0, quantile(residual, 0.80))
p90_adjustment = max(0, quantile(residual, 0.90))
```

生产预测：

```text
P80 = P50 + p80_adjustment
P90 = P50 + p90_adjustment
```

这里的含义是：

- P50：模型中心估计；
- P80：用于较保守资源规划的上界；
- P90：更保守的资源规划值。

当前区间是全局残差校准，不会针对每个人或任务规模自动改变宽度。后续数据量足够时，可升级为 Quantile Regression 或 conformal prediction。

## 10. 模型评估指标

训练命令报告：

### MAE

```text
MAE = mean(|prediction - actual|)
```

最容易向业务解释：平均预测相差多少小时。

### Median AE

绝对误差的中位数，比 MAE 更不容易受少量极端 DID 影响。

### RMSE

```text
RMSE = sqrt(mean((prediction - actual)²))
```

它会更严重地惩罚大误差，适合检查是否存在严重低估或高估。

### WAPE

```text
WAPE = Σ|prediction - actual| / Σactual
```

适合评估整个团队资源规划的总体偏差。

### Bias

```text
Bias = mean(prediction - actual)
```

- Bias 大于零：整体偏高估；
- Bias 小于零：整体偏低估。

### P80/P90 Coverage

```text
coverage = 实际工时小于等于预测上界的测试样本比例
```

例如理想情况下，P80 coverage 应接近 80%。测试数据较少时 coverage 会波动，因此必须同时报告测试样本量。

## 11. 训练和模型保存

运行：

```powershell
py .\effort_prediction.py train `
  --input .\data\did_effort_training.json `
  --model .\artifacts\did_effort_model.joblib `
  --cache .\artifacts\did_effort_similarity_cache.joblib
```

如果省略 `--input`，程序会直接从 Neo4j 读取训练记录：

```powershell
py .\effort_prediction.py train `
  --model .\artifacts\did_effort_model.joblib `
  --cache .\artifacts\did_effort_similarity_cache.joblib
```

建议生产中保留 `extract → 人工检查 → train` 两阶段流程。

保存的 joblib artifact 包含：

- 模型版本；
- 训练时间；
- 完整 scikit-learn Pipeline；
- 符合资格的历史记录；
- 数值和类别特征列表；
- P80/P90 调整量；
- 校准得到的 Ridge/个人基准融合及预测上限策略；
- 原始 Ridge、个人基准和稳健融合的测试指标；
- 测试指标；
- train/calibration/test 样本和 DID 数量。

`artifacts/` 已被 `.gitignore` 排除。

## 12. 如何预测待交付 DID

运行：

```powershell
py .\effort_prediction.py predict `
  --model .\artifacts\did_effort_model.joblib `
  --person "Chen, Sizhen" `
  --did "DID123"
```

指定历史预测日期：

```powershell
py .\effort_prediction.py predict `
  --model .\artifacts\did_effort_model.joblib `
  --person "Chen, Sizhen" `
  --did "DID123" `
  --as-of-date "2026-09-10"
```

### 12.1 目标查询

目标必须满足：

```text
DID_Status ∈ {Planned, Ongoing}
```

而且 Neo4j 中必须存在：

```text
(Person)-[:WORKS_ON]->(Delivery)
```

目标查询读取与训练阶段一致的：

- 十二个任务量字段；
- TA 和 Study Type；
- Reporting Event；
- Draft/Final；
- TLF、ADaM 和 SDTM 明细。

它不读取目标的最终工时。

### 12.2 预测时历史范围

模型文件中保存了训练历史。预测时再次过滤：

```text
completion_date < as_of_date
```

因此即使模型文件包含晚于指定 `as_of_date` 的历史，也不会把这些记录用于该次预测的动态个人效率和相似度特征。

注意：模型系数本身仍然由模型训练日期之前的完整训练集拟合。因此 `--as-of-date` 适合控制特征历史范围，但不能把当前模型变成严格的历史时点模型。严格历史回测需要在每个历史 cutoff 上重新训练模型。

### 12.3 返回结果

示例：

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

程序会返回最多五个最相似的个人历史 DID，包括：

- DID；
- Study；
- 完成日期；
- 实际工时；
- TLF/ADaM/SDTM 相似度；
- 总体相似度。

### 12.4 预测警告

以下情况会产生 warning：

- 此人在预测日期之前少于五个 Completed DID；
- 预测日期之前的全局历史少于二十条；
- 目标 DID 没有可用的 TLF/ADaM/SDTM 明细。

业务展示层不应隐藏这些警告。

## 13. Agent 如何调用

Agent 或其他 Python 模块可以直接调用：

```python
from effort_prediction import predict_effort

result = predict_effort(
    person="Chen, Sizhen",
    did="DID123",
    as_of_date="2026-09-10",
)
```

推荐职责分工：

```text
LLM Agent
  ├─ 识别人名、DID 和 as-of date
  ├─ 调用 predict_effort()
  └─ 用业务语言解释返回结果和 warning

Python 模型
  ├─ 查询数据
  ├─ 计算特征
  ├─ 执行回归
  └─ 返回预测和相似案例
```

LLM 不应自行计算回归、修改 P50/P80/P90，或者在模型失败时编造预测值。

### 13.1 当前问答 Agent 已接入

`agent.py` 的 `ask()` 已包含预测路由。明确包含“预测”“预计”
或 `predict`、`forecast` 等意图的问题会走工时模型；普通历史工时问题继续走原有
Text-to-Cypher 流程。

例如，可直接在 Streamlit 聊天框输入：

```text
预测 Riven 完成 C5001001_59 需要多少工时？
```

处理顺序：

```text
识别预测意图
→ LLM 提取 Person、DID 和可选 as-of date
→ 从 Neo4j Person.Name 生成相近正式姓名候选，并约束 LLM 选择
→ Python 对返回姓名执行唯一匹配验证
→ 从 Neo4j 读取 Planned/Ongoing DID 当前范围
→ 加载并缓存 artifacts/did_effort_model.joblib
→ Python 计算 P50/P80/P90
→ Agent 用固定模板展示结果
```

当前预测路由采用 LLM-first 参数提取：只要请求已判定为工时预测，LLM 都会解析
自然语言中的人员、DID 和日期，而不是由正则直接决定人名。候选姓名来自当前 Neo4j
数据库，LLM 必须选用其中一个正式 `Person.Name`；Python 随后再次验证唯一匹配，避免
名称拼写、空格、别名或词序差异导致把整句误当作人名。

因此，每个预测请求至少会消耗一次 LLM 调用；对于意图不明确的 DID 问题，系统会先做
一次预测/普通图查询意图分类，因此可能消耗两次 LLM 调用。LLM 只负责路由和参数提取，
不会计算、修改或解释 P50/P80/P90 数值。模型文件按修改时间缓存，重新发布新模型后会
自动加载新版本。

## 14. 推荐的首次运行步骤

### 步骤一：确认连接

检查 `.env` 位于项目根目录，且文件名不是 `.env.txt`。

### 步骤二：导出数据

```powershell
py .\effort_prediction.py extract `
  --output .\data\did_effort_training.json
```

### 步骤三：检查质量报告

特别关注：

- `record_count`
- `missing_actual_hours`
- `non_positive_actual_hours`
- `duplicate_person_did`
- `duplicate_work_on_relationships`
- `multiple_studies`
- `no_time_records`

如果大量记录被排除，应先修复数据或明确业务规则，不应简单降低清洗标准。

### 步骤四：训练

```powershell
py .\effort_prediction.py train `
  --input .\data\did_effort_training.json `
  --model .\artifacts\did_effort_model.joblib `
  --cache .\artifacts\did_effort_similarity_cache.joblib
```

### 步骤五：检查指标

至少检查：

- MAE 是否优于“全局历史中位数”基准；
- WAPE 是否满足资源规划需要；
- Bias 是否明显为负；
- P80/P90 coverage 是否接近目标；
- test DID 和 test record 数量是否足够。

### 步骤六：预测真实案例

选择已知任务范围的 Planned/Ongoing DID，运行预测并让业务专家检查：

- 任务量是否正确；
- 相似历史 DID 是否合理；
- 人员历史数量是否正确；
- P50 和 P80 是否具有业务可解释性。

## 15. 当前限制和下一步改进

### 当前限制

1. `TIME_ON` 没有拆分 Generation 和 QC 时，只能预测合并工时。
2. 月度工时可能无法精确切分到任务完成日。
3. 没有 scope snapshot 时，严格历史回测存在限制。
4. TLF 标题近似使用字符 n-gram，不是 embedding，不能完全理解深层语义。
5. 当前 P80/P90 使用全局残差调整，区间宽度不会随样本不确定性变化。
6. 当前模型使用 Person-DID 汇总标签，无法判断具体哪个 TLF 消耗多少工时。
7. 个人历史特征在同一天不共享记录，这是保守的防泄漏策略。

### 推荐改进顺序

1. 建立任务范围和预测时点快照；
2. 记录任务级 Generation/QC 工时；
3. 为 TLF/ADaM/SDTM 建立跨 Study 的标准 ID；
4. 增加 spec change、返工、数据延迟和代码复用字段；
5. 与简单业务规则和全局中位数 baseline 比较；
6. 数据量足够后比较 CatBoost、Gradient Boosting 和层级模型；
7. 使用 Quantile Regression 或 conformal prediction 改善区间；
8. 建立模型版本、漂移监控和定期重训机制。

## 16. 文件位置

```text
effort_prediction.py          主程序
test_effort_prediction.py     单元测试
neo4j_client.py               Neo4j 连接和 .env 读取
requirements.txt              Python 依赖
data/                         导出训练数据，不提交 Git
artifacts/                    训练模型，不提交 Git
docs/effort_prediction.md     本文档
```

运行测试：

```powershell
py -m unittest -v .\test_effort_prediction.py
```
