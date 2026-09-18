# DID 个人工时预测模型演进汇报（v1 至 v3）

## 1. 汇报摘要

本项目建立了一个以 Neo4j 历史数据为基础的 DID 个人工时预测模型。预测单位是：

```text
Person x DID
```

模型预测某位人员完成 Planned 或 Ongoing DID 所需的总 hands-on hours，并同时提供：

- P50：中心预测；
- P80：用于常规资源预留的较保守上界；
- P90：用于高风险规划的更保守上界。

模型从 v1 演进到 v3 的核心方向是：

1. 从“任务名称完全相同”升级为“可识别标题近似的相似任务”；
2. 从“只看单个最相似 DID”升级为“学习多次相似任务的工时和趋势”；
3. 从“只看单个历史 DID”升级为“识别多个历史 DID 合起来对目标任务的覆盖”；
4. 从“Ridge 直接输出”升级为“经过历史基准融合和极端预测保护的稳健输出”；
5. 从一次性慢速计算升级为可复用的相似度缓存和更快的时间安全特征构造。

在相同的 32,705 条合格 Person-DID 记录、相同的时间切分下，v3 的测试 WAPE 从 v1 的 87.27% 降至 71.30%，RMSE 从 164.28 小时降至 67.97 小时。

## 2. 数据与评估原则

### 2.1 训练数据

数据来自 Neo4j：

- `WORKS_ON`：人员在 DID 中负责的任务数量；
- `TIME_ON`：人员在 DID 中登记的实际工时；
- `HAS_TLF`、`HAS_ADAM`、`HAS_SDTM`：DID 的工作内容；
- Study、TA、Reporting Event、Draft/Final 等任务背景。

训练标签为：

```text
某人员在某 DID 中的实际总登记工时
```

### 2.2 防止时间泄漏

模型严格按实际交付日期排序：

```text
历史 DID 实际交付日期 < 当前 DID 实际交付日期
```

因此，训练和预测都不会使用未来 DID 或同日 DID 的信息。

### 2.3 评估切分

按 DID 的实际交付日期进行分组时间切分：

```text
前 70% DID：训练 Ridge
中间 15% DID：选择预测策略和 P80/P90 校准
最后 15% DID：独立测试
```

同一个 DID 不会同时进入训练集和测试集。

## 3. 模型版本演进

| 版本 | 主要新增能力 | 解决的问题 |
|---|---|---|
| v1 | 任务数量、个人历史效率、TLF/ADaM/SDTM 精确名称匹配 | 建立可解释的第一版基线 |
| v2 | TLF 标题字符 n-gram 近似匹配 | 标题词序变化或轻微改写时，精确匹配会漏掉相似任务 |
| v2-fast | 缓存、候选筛选、重复相似任务特征 | v2 较慢，且无法充分描述重复相似工作经验 |
| v3-robust | 多 DID 组合覆盖、Ridge/个人基准融合、极端预测上限、自动基准对比 | 少量异常外推导致 WAPE/RMSE 偏高 |

## 4. v1：可解释的基础模型

### 4.1 主要输入

v1 使用：

- 当前 DID 的任务数量；
- 此人过去完成 DID 的数量、中位工时、单位任务中位工时；
- 全局历史工时；
- TLF、ADaM、SDTM 的精确任务名称重合；
- 最相似历史 DID 与当前 DID 的时间间隔；
- TA、Study Type、Reporting Event、Draft/Final。

TLF、ADaM、SDTM 的精确相似度采用 Jaccard：

```text
相似度 = 两边共同任务数 / 两边任务并集数
```

### 4.2 优点和限制

优点：

- 结构清晰、容易解释；
- 训练较快；
- 为后续版本提供可靠比较基准。

限制：

- 标题轻微改写会被视为不同任务；
- 主要依赖单个最相似 DID；
- 无法识别重复经验带来的效率变化。

## 5. v2：加入 TLF 标题近似匹配

### 5.1 改动

v2 对 TLF 标题使用本地字符 3-5 gram 向量和余弦相似度。它不调用外部 API，也不是 LLM embedding。

单个 TLF 的分数：

```text
80% x 标题相似度
+ 10% x Type 是否相同
+ 10% x Source 是否相同
```

若 Type 或 Source 缺失，已有字段会重新归一化，不会因缺失信息直接扣分。

每个目标 TLF 和历史 TLF 采用一对一匹配，分数低于 0.70 不作为匹配。DID 层面新增：

- `max_tlf_semantic_similarity`
- `max_tlf_semantic_coverage`
- `max_combined_similarity`

其中：

```text
combined_similarity
= (精确集合相似度 + TLF标题近似相似度) / 2
```

### 5.2 业务意义

v2 能识别下列情况：

```text
Summary of Treatment-Emergent Adverse Events
Treatment Emergent Adverse Event Summary
```

虽然文字顺序不同，仍可被识别为高度相似的 TLF。

## 6. v2-fast：重复经验与训练性能

### 6.1 重复相似工作特征

v2-fast 新增：

- `top3_combined_similarity_mean`：最相似 3 个 DID 的平均相似度；
- `top5_combined_similarity_mean`：最相似 5 个 DID 的平均相似度；
- `similar_did_count_ge_70`：相似度至少 0.70 的 DID 数；
- `similar_did_count_ge_85`：相似度至少 0.85 的 DID 数；
- `weighted_similar_hours`：相似 DID 工时的相似度加权平均；
- `weighted_similar_hours_per_task`：相似 DID 单位任务工时的加权平均；
- `latest_similar_hours`：最近一个相似 DID 的实际工时；
- `similar_hours_trend`：相似 DID 按实际交付日期排列后的工时趋势。

例如：

```text
第一次相似工作：30小时
第二次相似工作：24小时
第三次相似工作：18小时
```

`similar_hours_trend` 为负，模型可以从数据中学习“多次重复后可能更快”。这不是硬编码折扣；如果历史数据表明任务变复杂，模型也可能学习到工时增加。

### 6.2 性能优化

v2 的语义匹配需要比较大量历史 DID，训练时间较长。v2-fast：

- 只比较有价值的候选历史 DID：
  - 最近 50 个；
  - 最近 100 个同 Study DID；
  - 最近 100 个存在精确任务重合的 DID；
  - 最近 25 个同 TA DID；
- 将 TLF 匹配结果持久化到 `artifacts/did_effort_similarity_cache.joblib`；
- TLF 清单未变时重训可复用缓存；
- 每 500 条显示进度，每 2,000 条保存缓存；
- 按日期增量维护历史记录，避免每条样本反复扫描全部数据。

## 7. v3-robust：针对 WAPE 的关键改进

### 7.1 为什么需要 v3

v2-fast 的 WAPE 分析显示，少量极端预测贡献了大量总误差。例如：

```text
实际约535小时，预测超过6000小时
实际超过1000小时，预测只有几十小时
```

问题不是大多数普通 DID 都预测很差，而是 Ridge 在极端任务数量上可能线性外推，在反变换后产生不合理的大数。

### 7.2 改动一：多个历史 DID 的组合覆盖

原来的单 DID 相似度无法完整表达以下情况：

```text
目标 DID：TLF A、B、C、D
历史 DID-1：A、B
历史 DID-2：C、D
```

单独比较时，两个历史 DID 各只覆盖目标约 50%；但合起来，人员已经做过全部目标 TLF。

v3 新增：

- `tlf_prior_coverage`
- `adam_prior_coverage`
- `sdtm_prior_coverage`
- `overall_prior_coverage`
- `tlf_unseen_count`
- `adam_unseen_count`
- `sdtm_unseen_count`

解释：

```text
tlf_prior_overlap_count = 过去做过的目标 TLF 数量
tlf_prior_coverage = 过去做过的目标 TLF / 目标 TLF 总数
tlf_unseen_count = 目标中从未做过的 TLF 数量
```

这不会把多个历史 DID 的工时直接相加，而是把“组合经验覆盖程度”交给模型学习。

### 7.3 改动二：Ridge 与个人历史基准融合

v3 同时使用：

```text
Ridge 预测
个人历史工时中位数
```

训练时，校准集自动尝试不同权重，选择 WAPE 最低的方案。当前训练选择：

```text
最终预测
= 85% x Ridge 预测
+ 15% x 个人历史中位工时
- 0.73小时
```

若人员没有历史记录，个人基准自动改为历史全局中位工时。

业务意义：模型仍以任务内容和相似度为主，但不完全脱离此人正常历史工作量。

### 7.4 改动三：极端预测保护

校准集自动选择预测上限。当前正式模型的 P50 上限为：

```text
400 小时
```

这个值来自训练标签的第 99 百分位，不是手工随意填写。

意义：

- 避免数千小时的异常预测；
- 显著降低 RMSE 和 WAPE；
- 但真实超过 400 小时的特殊项目可能被低估，因此高风险场景应参考 P80/P90，并人工复核。

### 7.5 自动基准比较

每次训练输出三组测试指标：

```text
raw_ridge                 未加保护的 Ridge
person_history_baseline   个人历史中位数
robust_blend              v3 正式预测
```

这确保新模型不是只比旧版本好看，而是也要优于简单、透明的业务基准。

## 8. v3 使用的全部特征

v3-robust 的 Ridge 部分共使用 **49 个特征**：45 个数值特征和 4 个类别特征。所有历史类特征只使用目标 DID 实际交付日期（或预测 `as_of_date`）之前的数据。

### 8.1 当前任务量（12 个）

| 特征 | 含义 |
|---|---|
| `task_count` | 此人负责的总任务数。 |
| `task_generation_count` | 此人负责 Generation 的任务数。 |
| `task_qc_count` | 此人负责 QC 的任务数。 |
| `tlf_count` | 此人负责的 TLF 数量。 |
| `tlf_generation_count` | 此人负责 Generation 的 TLF 数量。 |
| `tlf_qc_count` | 此人负责 QC 的 TLF 数量。 |
| `adam_count` | 此人负责的 ADaM 工作项数量。 |
| `adam_generation_count` | 此人负责 Generation 的 ADaM 工作项数量。 |
| `adam_qc_count` | 此人负责 QC 的 ADaM 工作项数量。 |
| `sdtm_count` | 此人负责的 SDTM 工作项数量。 |
| `sdtm_generation_count` | 此人负责 Generation 的 SDTM 工作项数量。 |
| `sdtm_qc_count` | 此人负责 QC 的 SDTM 工作项数量。 |

### 8.2 人员与全局历史效率（7 个）

| 特征 | 含义 |
|---|---|
| `person_completed_count` | 此人在预测日期前完成的合格 DID 数。 |
| `person_median_hours` | 此人历史实际工时的中位数。 |
| `person_recent_median_hours` | 此人最近 5 个历史 DID 实际工时的中位数。 |
| `person_median_hours_per_task` | 此人历史每任务工时的中位数。 |
| `global_completed_count` | 预测日期前所有人员合格历史记录数。 |
| `global_median_hours` | 所有人员历史实际工时的中位数。 |
| `global_median_hours_per_task` | 所有人员历史每任务工时的中位数。 |

### 8.3 多个历史 DID 的任务覆盖（10 个）

这组特征回答：“目标任务中有多少内容，此人过去曾在一个或多个 DID 中做过？”

| 特征 | 含义 |
|---|---|
| `tlf_prior_overlap_count` | 目标 TLF 中曾在此人任一历史 DID 出现过的数量。 |
| `adam_prior_overlap_count` | 目标 ADaM 中曾在历史出现过的数量。 |
| `sdtm_prior_overlap_count` | 目标 SDTM 中曾在历史出现过的数量。 |
| `tlf_prior_coverage` | 已做过的目标 TLF 数量 / 目标 TLF 总数。 |
| `adam_prior_coverage` | 已做过的目标 ADaM 数量 / 目标 ADaM 总数。 |
| `sdtm_prior_coverage` | 已做过的目标 SDTM 数量 / 目标 SDTM 总数。 |
| `overall_prior_coverage` | 有任务内容的 TLF、ADaM、SDTM 三类覆盖率的平均值。 |
| `tlf_unseen_count` | 目标中从未在此人历史出现过的 TLF 数量。 |
| `adam_unseen_count` | 目标中从未出现过的 ADaM 数量。 |
| `sdtm_unseen_count` | 目标中从未出现过的 SDTM 数量。 |

### 8.4 单个历史 DID 的最高相似度（7 个）

| 特征 | 含义 |
|---|---|
| `max_tlf_similarity` | 与任一历史 DID 的最高 TLF 精确名称集合相似度。 |
| `max_tlf_semantic_similarity` | 与任一历史 DID 的最高 TLF 标题近似相似度。 |
| `max_tlf_semantic_coverage` | 任一历史 DID 对目标 TLF 的最高标题近似覆盖率。 |
| `max_adam_similarity` | 与任一历史 DID 的最高 ADaM 精确名称集合相似度。 |
| `max_sdtm_similarity` | 与任一历史 DID 的最高 SDTM 精确名称集合相似度。 |
| `max_overall_similarity` | 与任一历史 DID 的最高 TLF/ADaM/SDTM 精确相似度平均值。 |
| `max_combined_similarity` | 最相似历史 DID 的综合相似度，即精确集合相似度和 TLF 标题近似相似度的平均。 |

### 8.5 重复相似工作与学习趋势（8 个）

| 特征 | 含义 |
|---|---|
| `top3_combined_similarity_mean` | 相似度最高 3 个历史 DID 的综合相似度平均值。 |
| `top5_combined_similarity_mean` | 相似度最高 5 个历史 DID 的综合相似度平均值。 |
| `similar_did_count_ge_70` | 综合相似度至少 0.70 的历史 DID 数量。 |
| `similar_did_count_ge_85` | 综合相似度至少 0.85 的高度相似历史 DID 数量。 |
| `weighted_similar_hours` | 综合相似度至少 0.70 的历史 DID 实际工时，以相似度为权重的平均值。 |
| `weighted_similar_hours_per_task` | 同一批相似 DID 的每任务实际工时加权平均值。 |
| `latest_similar_hours` | 最近完成的相似 DID（相似度至少 0.70）的实际工时。 |
| `similar_hours_trend` | 相似 DID 按实际交付日期排列后，工时的线性趋势；负数表示历史上越做越快，正数表示工时增加。 |

### 8.6 相似任务的时间间隔（1 个）

| 特征 | 含义 |
|---|---|
| `days_since_similar_work` | 目标日期距离最相似历史 DID 完成日期的天数；若没有任何相似历史，使用较大的默认值。 |

### 8.7 任务背景类别（4 个）

以下字段经过 One-Hot Encoding 后输入 Ridge，使模型能学习不同任务背景的系统性差异：

| 特征 | 含义 |
|---|---|
| `ta` | Therapeutic Area，例如 Oncology、Vaccines。 |
| `study_type` | Study 的类型。 |
| `reporting_event` | 报告/交付事件类型。 |
| `draft_or_final` | Draft 或 Final 状态。 |

### 8.8 不属于 Ridge 输入、但影响最终输出的 v3 策略

以下不是新增的回归特征，但会影响最终 P50：

- `person_history_baseline`：人员历史工时中位数；无个人历史时回退为全局中位数；
- `ridge_weight` / `baseline_weight`：由校准集自动选择的 Ridge 与个人基准融合比例；
- `offset_hours`：由校准集选择的残差偏移；
- `cap_hours`：由训练标签分位数得到的预测上限，避免不合理的极端外推；
- `upper_adjustments.p80` / `upper_adjustments.p90`：在校准集计算的上界补偿，用于从 P50 生成 P80/P90。

## 9. 模型效果对比

以下版本均使用 32,705 条合格记录、相同时间切分：

| 指标 | v1 | v2 | v2-fast | v3-robust |
|---|---:|---:|---:|---:|
| MAE（小时） | 34.25 | 33.19 | 32.87 | **27.98** |
| Median AE（小时） | 9.13 | 9.37 | 9.13 | **8.95** |
| RMSE（小时） | 164.28 | 145.07 | 140.26 | **67.97** |
| WAPE | 87.27% | 84.57% | 83.75% | **71.30%** |
| Bias（小时） | **-8.29** | -9.86 | -9.99 | -15.05 |
| P80 Coverage | 81.13% | 81.35% | 81.01% | **80.56%** |
| P90 Coverage | 91.96% | 91.94% | 91.69% | **91.98%** |

### 9.1 如何解读

- MAE：平均每条 Person-DID 相差多少小时，越低越好；
- Median AE：普通案例的典型误差，越低越好；
- RMSE：对极端大错误处罚更重，越低越好；
- WAPE：累计绝对误差占实际总工时的比例，越低越好；
- Bias：整体偏高估或偏低估，负数表示低估；
- P80/P90 Coverage：实际工时没有超过 P80/P90 的比例，应接近 80%/90%。

v3 最大改善来自：

```text
WAPE：83.75% -> 71.30%
RMSE：140.26 -> 67.97小时
```

这表明 v3 显著减少了少量异常预测对整体结果的破坏。

## 10. 当前推荐使用方式

对于单个 Planned/Ongoing DID：

- P50：最典型的中心估计；
- P80：日常资源规划建议采用；
- P90：高风险交付或需更保守的资源预留时采用。

当前正式模型：

```text
artifacts/did_effort_model.joblib
model_version: did-effort-ridge-v3-robust
```

保留的 v2-fast 回退模型：

```text
artifacts/did_effort_model_v2_fast_backup.joblib
```

## 11. 当前局限和后续建议

### 11.1 当前局限

1. `TIME_ON` 是 DID 汇总工时，可能包含会议、返工或管理性工作；
2. 未完全区分 Generation 与 QC 的实际工时；
3. 没有任务范围历史快照时，回测可能使用 DID 后续更新后的最终任务清单；
4. TLF 标题相似度是字符 n-gram，不等同于深层语义 embedding；
5. 真实超高工时项目可能被 v3 上限低估；
6. Bias 仍为负，说明整体仍需关注低估风险。

### 11.2 推荐下一步

1. 自动生成异常工时和任务数量矛盾清单，供业务核查；
2. 对确认的数据错误建立排除名单，而不是仅因工时大就自动删除；
3. 记录任务级 Generation/QC 工时、返工、数据延迟和 scope change；
4. 比较不易极端外推的树模型，例如 Gradient Boosting 或 CatBoost；
5. 对高工时 DID 研究独立的风险分类或两阶段模型；
6. 建立“候选模型与当前正式模型”自动晋级比较机制。

## 12. 汇报时可使用的一句话总结

> 我们已将 DID 个人工时预测从基于任务数量和精确名称匹配的基础模型，升级为能够识别近似任务、重复经验、多个历史 DID 的组合覆盖，并自动抑制极端外推的稳健模型。在独立时间测试集上，WAPE 从 87.27% 降至 71.30%，RMSE 从 164.28 小时降至 67.97 小时；目前适合作为资源规划和风险预留的辅助决策工具，而不应替代业务专家对异常项目的判断。
