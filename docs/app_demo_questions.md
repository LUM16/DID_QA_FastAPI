# DID Neo4j Q&A App 汇报演示问题

本文提供可在 Streamlit App 的 **Ask Neo4j** 对话框中直接输入的演示问题。
问题覆盖 DID 组合、交付进度、人员工时、TLF/Data、团队与管理层级，以及
effort prediction。它们不包含 **Recommend DU Team** 或 **Allocate TLF People**
功能。

## 演示前建议

1. 先确认 RSC 已连接到最新 Neo4j 数据，并且页面显示连接正常。
2. 使用数据库中实际存在的 Study、DID、人员或 Team Lead 名称替换方括号中的
   示例值，例如 `[Study ID]`、`[DID]`、`[Person Name]`、`[Team Lead Name]`。
3. 对需要趋势或分布的题目，建议选择跨多个 DID 或一段时间的数据范围，图表会
   比单条记录更适合展示。
4. 如果要演示 effort prediction，先确认部署中已有
   `artifacts/did_effort_model.joblib`，且目标人员与 DID 在 Neo4j 中存在有效
   assignment。

## 一、建议的 5 分钟主线演示

这五个问题可按顺序展示“自然语言提问 -> Neo4j 查询 -> 表格/图表 -> 可解释
业务结论”的完整流程。

| 顺序 | 可直接输入的问题 | 建议展示 | 汇报重点 |
| --- | --- | --- | --- |
| 1 | `[Study ID] 有哪些 DID？分别是什么状态、计划交付日期和实际交付日期？` | 明细表 | 展示自然语言自动查询 Study 与 Delivery 关系。 |
| 2 | `[Study ID] 中不同 DID 状态的数量分布。` | 柱状图 + 表格 | 展示 app 根据返回的分类计数自动选择安全图表。 |
| 3 | `哪些 Ongoing DID 的计划交付日期最早？显示 Study、DID、计划交付日期和负责人员。` | 排序表 | 展示对当前交付风险和人员责任的快速定位。 |
| 4 | `[Person Name] 参与过哪些 DID？请显示每个 DID 的状态、TLF 数、ADaM 数和 SDTM 数。` | 明细表 | 展示从 Person 到 Delivery 再到 TLF/Data 的图关系追溯。 |
| 5 | `预测 [Person Name] 完成 [DID] 需要多少工时？` | 预测结果卡/表格 | 展示模型输出 P50/P80/P90，而不是让 LLM 编造工时。 |

## 二、DID 与交付进度

### 1. 当前组合与状态

```text
[Study ID] 有哪些 DID？显示 DID、Reporting Event、状态、Draft/Final、计划交付日期和实际交付日期。
```

**适合讲解：** 一个问题同时查看该 study 的交付组合、报告事件和进度。

```text
当前 Planned、Ongoing 和 Completed DID 各有多少？
```

**适合讲解：** 适合展示全局 portfolio 的状态分布图。

```text
请按 Study 汇总 Ongoing DID 数量，并按数量从高到低排序。
```

**适合讲解：** 快速识别当前交付活动最集中的 study。

### 2. 时间与风险跟踪

```text
未来 90 天内计划交付的 DID 有哪些？请显示 DID、Study、状态、计划交付日期和 Reporting Event。
```

**适合讲解：** 近期工作计划和关键交付节点。

```text
已完成 DID 的实际交付日期按月份如何分布？
```

**适合讲解：** 月度 delivery throughput；通常适合柱状图或折线图。

```text
哪些 Completed DID 的实际交付日期晚于计划交付日期？显示 DID、Study、计划日期、实际日期和相差天数。
```

**适合讲解：** 数据允许时，可用于回顾交付延迟；应以返回表格为准。

```text
按 Reporting Event 汇总 Completed DID 数量。
```

**适合讲解：** 展示不同交付事件的历史工作量分布。

## 三、人员经验、投入与生产力

### 1. 人员参与范围

```text
[Person Name] 当前参与哪些 Planned 或 Ongoing DID？
```

**适合讲解：** 某位同事当前的 active workload。

```text
[Person Name] 历史参与过哪些 Completed DID？请显示 Study、DID、实际交付日期和负责的 TLF、ADaM、SDTM 数量。
```

**适合讲解：** 个人 completed experience 的可审计证据。

```text
参与 Ongoing DID 数量最多的人员是谁？请按人数排序显示前 10 名。
```

**适合讲解：** 团队当前工作负担；适合 horizontal bar chart。

### 2. 工时与任务量

```text
[Person Name] 在 [DID] 上记录了多少 TIME_ON 工时？请按月份汇总。
```

**适合讲解：** 人员在特定交付上的实际投入趋势。若数据跨月，适合折线图。

```text
请按人员汇总 [DID] 的 TIME_ON 工时，并显示该人员负责的 TLF、ADaM 和 SDTM 数量。
```

**适合讲解：** 在同一 DID 内比较投入和任务范围。

```text
过去 12 个月中，Completed DID 的总 TIME_ON 工时按人员如何分布？
```

**适合讲解：** 历史投入结构。展示时应说明 TIME_ON 是已记录工时，不等同于未来预测。

```text
哪些人员在 Completed DID 中承担的 TLF Generation 数量最多？
```

**适合讲解：** 识别具有较多 TLF Generation 历史经验的人员。

## 四、TLF、ADaM 与 SDTM 覆盖范围

### 1. 单个 DID 的工作内容

```text
[DID] 包含哪些 TLF？请显示 TLF 名称、Type、Source Datasets、Generation 和 QC 人员。
```

**适合讲解：** 从 Delivery 到 TLF 的明细追溯，以及 Gen/QC 分工。

```text
[DID] 使用哪些 ADaM dataset 和 SDTM domain？
```

**适合讲解：** 一个 DID 的数据范围概览。

```text
[DID] 的 TLF、ADaM 和 SDTM 数量分别是多少？
```

**适合讲解：** 适合以 KPI table 或单行汇总呈现的 scope sizing 问题。

### 2. 跨 DID 对比

```text
比较 [DID A] 和 [DID B] 的 TLF、ADaM、SDTM 数量及共同使用的数据集。
```

**适合讲解：** 同一 study 或相近 reporting event 的 scope 对比。

```text
哪些 Completed DID 使用了 [SDTM Domain]？请显示 DID、Study、实际交付日期和相关人员。
```

**适合讲解：** 从具体 SDTM domain 反查历史经验和交付记录。

```text
哪些 DID 使用了 [ADaM Dataset]？按 DID 状态汇总数量。
```

**适合讲解：** dataset 的跨项目复用和当前/历史交付分布。

```text
最常出现的 TLF Source Datasets 是哪些？请显示对应 TLF 数量。
```

**适合讲解：** 展示数据源驱动的 TLF 工作范围，通常适合条形图。

## 五、组织与团队视角

> 使用真实的 `Team_Lead_Name`、`Group_Lead_Name` 或人员姓名。组织层级问题应
> 明确说明希望按 Team、Group、Manager 还是 TA 统计，以减少歧义。

```text
[Team Lead Name] 团队当前有多少位人员？每个人参与多少个 Planned 或 Ongoing DID？
```

**适合讲解：** 团队人员规模与当前 active DID work burden。

```text
[Team Lead Name] 团队已完成的 DID 数量按人员如何分布？
```

**适合讲解：** 团队 completed delivery participation 的分布；适合条形图。

```text
[Group Lead Name] Group 下有哪些 Team Lead？每个 Team Lead 团队的 Ongoing DID 数量是多少？
```

**适合讲解：** 从 Group 到 Team 的组织层级汇总。

```text
[Person Name] 的直属 Manager 是谁？该 Manager 下还有哪些人员？
```

**适合讲解：** 人员组织关系查询；适合表格展示。

```text
按 TA 汇总 Planned、Ongoing 和 Completed DID 数量。
```

**适合讲解：** 跨治疗领域的 portfolio 状态对比；适合 grouped 或 stacked bar chart。

## 六、Effort Prediction 演示问题

以下问题在普通聊天框输入。只有表达了明确“预测/estimate/forecast effort”的请求
才会进入 effort model；普通图数据库问答仍走 read-only Text-to-Cypher。

```text
预测 [Person Name] 完成 [DID] 需要多少工时？
```

```text
Estimate the effort for [Person Name] on [DID].
```

```text
[Person Name] 在 [DID] 上的 P50、P80 和 P90 预计工时分别是多少？
```

**适合讲解的核心信息：**

- P50：中位情景的预测总工时；
- P80/P90：更保守的计划情景，用于 capacity/risk discussion；
- 数值由 Python 中已训练的 Ridge V3 model 计算；
- 模型使用人员历史效率、目标 DID 的 TLF/Data scope、历史相似工作等特征；
- LLM 只负责受约束的意图和人员/DID 参数解析，不计算或修改 P50/P80/P90。

## 七、图表展示问题

图表只使用 Neo4j 已返回的字段，且系统会检查分类字段、数值字段和非有限值；
若不适合绘图，仍保留表格结果。以下问题最容易得到适合汇报的图表：

```text
按 DID_Status 统计 DID 数量。
```

```text
按月份统计 Completed DID 数量。
```

```text
按人员统计当前 Ongoing DID 数量，显示前 10 名。
```

```text
按 Team Lead 统计团队已完成 DID 数量。
```

```text
按 Reporting Event 汇总 DID 数量。
```

```text
按 Study 汇总 TLF 数量，显示前 10 个 Study。
```

**讲解建议：** 强调图表位于查询完成之后。先由 Neo4j 返回真实 rows，再由受限
展示层在已返回字段中选择 table/chart；图表不会改变 Cypher 查询含义或计算新的
业务数值。

## 八、推荐的收尾问题

```text
请总结 [Study ID] 当前的 DID 状态、最近计划交付和参与人员。
```

若希望以人员计划为结尾：

```text
预测 [Person Name] 完成 [DID] 的 P50、P80、P90 工时，并列出影响预测的主要历史依据。
```

汇报时应明确：Q&A 返回的是 Neo4j 的真实、只读数据；预测是独立模型的决策支持
结果。两者都不自动修改生产数据或人员分配。
