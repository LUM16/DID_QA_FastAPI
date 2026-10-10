# 新 Delivery 的 DU 推荐与 TLF 人员分配

## 汇报摘要

系统为新 Delivery 提供两层、顺序执行的资源决策支持：

```text
新 Delivery 的 TLF scope
        |
        v
第 1 层：Recommend Team
选择 Henry 或 Priya，跨其下所有 Group 比较团队
        |
        v
第 2 层：Allocate TLF People
在已确认的 DU Team 内，为每条 TLF 推荐 Generation / QC primary 和 backup
        |
        v
Team Lead 审核、确认并在业务系统中实施
```

两项能力均为**可解释的规则型推荐**，不是黑箱式自动派工，也不会自动修改
Neo4j、人员 assignment 或项目计划。每一项推荐都能回溯至已完成 DID 的实际
TLF 经验、当前 active DID 负担和明确的规则。

---

## 1. 两项能力分别回答什么问题

| 决策层级 | 功能 | 要回答的问题 | 推荐对象 |
| --- | --- | --- | --- |
| 团队层级 | **Recommend Team** | 在所选 TA Lead 下跨 Group 比较，哪个团队最适合接手这份新 Delivery？ | Team / Team Lead |
| 人员层级 | **Allocate TLF People** | 在已经确定的 DU 内，谁应负责每条 TLF 的 Generation 和 QC？ | Person |

两者不能互相替代：

- DU recommendation 不指定具体的 Gen/QC 人员；
- TLF allocation 不在多个 DU 之间比较团队；
- 推荐 DU 后，仍必须由 Group Lead / Team Lead 确认团队，再运行人员分配。

---

## 2. 共用的设计原则

### 2.1 只将已完成工作当作历史经验

历史经验仅来自：

```text
Completed DID
+ 有实际交付日期
+ 有 TLF 及其实际 Generation / QC 责任记录
```

Planned 或 Ongoing DID 只用于计算当前工作负担，不作为“已经验证过的经验”。

### 2.2 实际负责才算经验

不能因为某人参与过包含某个 TLF 的 DID，就认为其负责过该 TLF。

只有人员实际出现在 Delivery 的以下属性中，才视为该 TLF 的 role evidence：

```text
HAS_TLF.Generation
HAS_TLF.QC
```

因此，系统区分：

```text
参与过同一 Delivery
!=
实际负责某条 TLF
```

这能避免把泛参与经历误报为可交付的表级经验。

### 2.3 TLF 相似度由确定性算法计算

系统不会让 LLM 判断每一条 TLF 是否相似。TLF 标题经过统一标准化后，使用
character 3-5 gram 向量相似度：

```text
HashingVectorizer(char_wb, 3-5)
-> L2 normalization
-> vector inner product
```

这样可以处理大小写、标点、下划线、轻微格式差异或词形变化。有效 semantic match
要求相似度达到：

```text
>= 0.70
```

`Type` 和 `Source Datasets` 仅作为精确匹配的辅助 metadata；不会由 LLM 重新解释。

### 2.4 Snapshot 使结果可重复、可审计

推荐页面运行时不直接访问 Neo4j。维护者在数据或组织结构刷新后，手动更新
snapshot：

```cmd
py du_team_recommendation.py refresh-history
py tlf_person_allocation.py refresh-snapshot
```

| 功能 | Snapshot artifact | 内容 |
| --- | --- | --- |
| DU recommendation | `artifacts/du_team_history_snapshot.joblib` | 当前 Group/DU 归属、实际 Gen/QC-owned TLF 历史、DU active DID 数 |
| TLF allocation | `artifacts/tlf_person_allocation_snapshot.joblib` | 人员级 Gen/QC TLF 历史证据、完成日期、当前 active DID 数 |

这使一次推荐能够说明“使用了哪一版历史数据”，也避免每次网页点击都对生产 Neo4j
执行大量匹配查询。

---

## 3. 第一层：Recommend Team

### 3.1 目的

在用户指定的 TA Lead 管辖范围内跨 Group，根据新 Delivery 的 TLF scope，对所有合格团队
进行排序，找出：

```text
有相关已交付 TLF 经验
+ 能覆盖更多目标 TLF
+ 近期有相似 Delivery 经验
+ 当前 active DID 相对较少
```

的 DU。

### 3.2 用户输入

1. 从可搜索下拉菜单选择 `Shen, Henry` 或 `Iyer, Priya Venkatesan`；
2. 新 Delivery 的 TLF scope：
   - 带 `TLF` sheet 的 Excel；或
   - 单个 TLF CSV。

使用的 TLF 列：

```text
Title
Type
Source Datasets
```

TA Lead 候选必须在 snapshot 中存在真实成员级组织映射。页面只开放 Henry / Priya，
不再提供 Group Lead 输入；其下所有 Group 的合格团队统一排名，默认展示前三名。
Group Lead 仅在结果中作为归属信息展示。现有 v4 snapshot 可直接复用。

本功能当前**不使用** ADaM/SDTM coverage，也不会显示 Missing ADaM/SDTM。

### 3.3 团队经验如何覆盖新 scope

系统对上传的每一条目标 TLF 独立寻找历史 evidence：

```text
目标 TLF-A -> 可由 DU 的 Completed DID-1 中实际负责过 TLF-A 的成员覆盖
目标 TLF-B -> 可由同一 DU 的 Completed DID-2 中实际负责过 TLF-B 的成员覆盖
```

因此，不要求单个历史 DID 覆盖所有新 TLF：

```text
目标 scope: TLF-A, TLF-B
历史 DID-1: 覆盖 TLF-A
历史 DID-2: 覆盖 TLF-B

TLF semantic coverage = 2 / 2 = 100%
```

但“Similar DID experience”仍以单个历史 DID 的完整 scope 相似度计算，避免把来自多个
不相关项目的零散经验误说成一次完整的相似 Delivery。

### 3.4 DU 评分：100 分

```text
DU score =
  37 x TLF semantic coverage
+ 18 x Similar DID experience
+ 10 x Recent relevant experience
+ 35 x Current active-DID workload
```

| 维度 | 满分 | 含义 |
| --- | ---: | --- |
| TLF semantic coverage | 37 | 新 Delivery 中有多少目标 TLF 能由该 DU 的实际 Gen/QC 历史证据覆盖。 |
| Similar DID experience | 18 | 该 DU 是否有单个 completed DID 的完整 scope 与新 Delivery 接近，以及相似 DID 的数量。 |
| Recent relevant experience | 10 | 相似 completed DID 越近期完成，得分越高。 |
| Current active-DID workload | 35 | 该 DU 当前 Planned + Ongoing distinct DID 越少，得分越高。 |

工作负担分数公式：

```text
35 x (1 - team active DID count / selected TA eligible-team maximum active DID count)
```

归一化仅使用所选 TA 下的合格候选团队，不受其他 TA 的工作负担影响。
这是一项相对负担指标，而不是 FTE capacity、休假、优先级或剩余工时的精确替代。

### 3.5 输出与审核

结果页面显示：

- 所选 TA Lead 下跨 Group 的团队排名、Group Lead 归属、总分和 recommendation level；
- TLF coverage；
- 当前 active DID 数；
- 最相似 completed DID；
- 每个输入 TLF 的 evidence DID 和完成日期。

建议等级：

| 总分 | 标签 | 含义 |
| ---: | --- | --- |
| >= 80 | Recommended | 经验覆盖和相对工作负担均较强。 |
| >= 65 | Suitable with review | 可行，但需要 Lead 结合业务情况审核。 |
| >= 45 | Backup option | 可作为备选团队。 |
| < 45 | Insufficient evidence | 历史 evidence 或适配度不足。 |

---

## 4. 第二层：Allocate TLF People

### 4.1 目的

在已选定的 DU Team 中，为新 Delivery 的每一条 TLF 推荐：

```text
1 名 Generation primary
1 名 QC primary
每个 role 最多 2 名 backup
```

它的目标不是把所有工作集中交给“分数最高的人”，而是在历史 role experience、当前
负担、Gen/QC 独立性与 source/domain 连续性之间取得可解释的平衡。

### 4.2 用户输入

1. 从可搜索下拉菜单明确选择完整 Team Lead 名称；
2. 新 Delivery 的 scope：
   - 带 `TLF` sheet 的 Excel（`Data` sheet 可选）；或
   - 单独一份 TLF CSV，无需第二个 Data 上传入口。

其中：

```text
TLF: Title, Type, Source Datasets
可选 workbook Data: SDTM/ADaM, Domain/Dataset Name
```

无需 Data 时仍按 `Source Datasets` 将相关 TLF 分组；缺少 source 则逐条独立，
不虚构 ADaM → SDTM 映射。workbook 原有 Data sheet 保留直接 SDTM 匹配分组能力，
不直接给人员打分。同步和后台 API 只上传 `primary_file` 与完整 `team_lead_name`，
Excel 导出仅使用已有 allocation result；core 可选 Data 参数仅保留旧调用兼容性。

### 4.3 候选人筛选

Generation 与 QC 分开产生候选池：

```text
Gen 候选人：必须有 Generation role evidence
QC 候选人：必须有 QC role evidence
```

每个“目标 TLF × 人员 × role”只挑选相关历史 evidence 进入评分。相关条件至少满足
下列之一：

```text
标题完全一致
或 Type / Source 一致
或 标准化标题存在长度 >= 3 的共同词
```

系统每人每个 role 最多比较 25 条最相关历史记录，并采用其中基础分最高、同分时完成日期
更近的一条作为最佳 evidence。

### 4.4 人员基础评分：100 分

| 维度 | 满分 | 计算逻辑 |
| --- | ---: | --- |
| TLF title semantic match | 40 | `40 x 标题相似度`。 |
| Exact title experience | 15 | 标准化标题完全一致。 |
| Type / Source match | 5 | Type 与 Source 各 2.5 分；双方非空且精确一致才得分。 |
| Recent relevant experience | 5 | semantic similarity >= 0.70 时，按完成时间衰减。 |
| Current active-DID workload | 35 | active DID 越少，得分越高。 |

近期经验的时间系数：

| 完成时间 | 系数 |
| --- | ---: |
| 180 天内 | 1.0 |
| 181-365 天 | 0.7 |
| 366-730 天 | 0.4 |
| 更早 | 0.15 |

人员工作负担分数：

```text
35 x (1 - person active DID count / selected team maximum active DID count)
```

### 4.5 同一来源 TLF 的连续性

为降低人员频繁切换和 handoff 风险，输入 TLF 会先分组：

```text
优先：Source Datasets 直接匹配 Data sheet 中的 SDTM domain
其次：标准化后的 Source Datasets 组合
最后：没有 Source 的 TLF 各自独立成组
```

在同一个 group 内：

- Generation primary 最多使用两人；
- QC primary 最多使用另两人；
- 已在该 group 承担 Gen primary 的人不切换为 QC primary，反之亦然；
- 已有合格 evidence 的 primary 会优先延续到同 group 的后续 TLF；
- backup 不受 primary roster 限制。

系统只基于输入中明确提供的 source/domain 直接关系分组，不推断 ADaM 与 SDTM 的血缘。

### 4.6 平衡和 QC guardrails

在同一轮 allocation 中，每获得一个 primary assignment，人员后续的 primary 排名会扣分：

```text
adjusted primary score = base score - 12 x prior primary assignments
```

它和当前 active-DID workload 同时工作：

- active DID workload：反映该人员已经在进行中的 Delivery 数量；
- 动态扣分：避免新上传的多条 TLF 全部落在同一个人身上。

同一 TLF 的 Gen 与 QC primary 默认必须是不同人员。只有在没有任何其他 QC role
evidence 的候选人时，系统才允许同一人作为 QC fallback，并明确显示：

```text
LEAD REVIEW REQUIRED
```

如果没有可靠 QC evidence，系统不会虚构一名 QC primary。

### 4.7 输出与审核

每条 TLF 的结果包括：

- Gen/QC primary；
- 各 role 最多两位 backup；
- score、active DID 数；
- 最佳历史 evidence DID 与完成日期；
- source/domain group；
- `LEAD REVIEW REQUIRED` 等审核提示。

同时可以下载 `tlf_person_allocation.xlsx`：每行一条输入 TLF，Generation 与 QC
primary/backup 分列，便于 Lead review、会议讨论和后续操作。

---

## 5. 建议的端到端业务流程

### 5.1 维护者在 Neo4j 数据更新后

```text
1. 确认 Completed DID、TLF Generation/QC、组织关系和 current workload 已刷新
2. refresh DU history snapshot
3. refresh TLF allocation snapshot
4. 如需要，发布 snapshot / shared cache 到 RSC
```

### 5.2 Group Lead / Team Lead 在新 Delivery 到来时

```text
1. 准备新 Delivery 的 TLF scope
2. 在 Recommend Team 选择 Henry 或 Priya，并上传 TLF scope
3. 审核排序、TLF coverage evidence 和 current workload
4. 确认一个 DU Team
5. 在 Allocate TLF People 搜索并选择该 Team Lead，上传单份 TLF CSV 或 workbook（Data sheet 可选）
6. 审核 Gen/QC primary、backup、group 连续性和 review flags
7. Lead 结合技能、availability、priority、休假和培训状态作最终决定
8. 在正式业务系统中执行人员分配
```

---

## 6. 汇报演示建议

### 场景

```text
某 TA 获得一份新 Delivery，需要跨其下多个 Group 选择团队，
并为其中每条 TLF 指定 Generation 和 QC 人员。
```

### 演示顺序

1. **展示输入**：Henry 或 Priya，以及新 Delivery 的 TLF scope；
2. **展示团队推荐**：跨 Group 排名、TLF coverage、similar completed DID、active DID workload；
3. **解释可审计性**：每个目标 TLF 都显示实际 Gen/QC-owned evidence DID；
4. **确认一个 DU**：说明这是 Lead 的业务决策，而非系统自动派工；
5. **展示人员 allocation**：Gen/QC primary、backups、评分和历史 evidence；
6. **展示 group continuity**：同一 source/domain 的 TLF 尽量由稳定的小范围人员承担；
7. **展示 QC guardrail**：Gen/QC 分离；出现 `LEAD REVIEW REQUIRED` 时由 Lead 决策；
8. **下载 Excel**：将推荐结果带入资源评审会议。

### 可直接用于汇报的总结

> 系统先在指定 TA Lead 下跨 Group 选择具有真实、已交付 TLF 经验且相对有容量的团队，再在该团队
> 内按每条 TLF 的实际 Gen/QC 历史经验推荐人员。推荐过程保留 TLF 级 evidence、工作
> 负担、评分和审核提示，帮助 Lead 更快地做出一致且可追溯的资源决策；最终人员安排仍由
> 业务负责人确认。

---

## 7. 边界与治理要求

系统不能直接判断或替代以下信息：

- 人员技能等级、培训和认证状态；
- 休假、可用工时、跨项目优先级；
- 实际 FTE capacity 或 remaining hours；
- 尚未写入 Neo4j 的临时工作安排；
- TLF 内容质量或交付风险的完整业务判断。

因此，系统输出应理解为：

```text
数据驱动、可解释、可审计的推荐
不是自动批准或自动执行的最终资源计划
```

推荐前应确认 snapshot 已按最新可信数据刷新；推荐后应由 Group Lead / Team Lead
结合未入库的业务信号进行最终审核。
