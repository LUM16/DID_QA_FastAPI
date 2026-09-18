# TLF 人员分配逻辑说明

## 1. 目的与适用范围

**Allocate TLF People** 用于在已经选定的 DU Team Lead 团队内，为新
Delivery 的每一个 TLF 推荐：

- 一名 **Generation primary**；
- 一名 **QC primary**；
- 每个角色最多两名有历史依据的 backup。

该功能只评估 TLF 分配，不使用 ADaM/SDTM 工作量来预测个人工时，也不
自动变更 Neo4j 中的人员分配。输出是可解释的推荐，最终人员安排仍由 Team
Lead 确认。

## 2. 输入、输出与数据边界

### 输入

用户上传以下任一种格式：

1. 含有 `TLF` 和 `Data` sheet 的 Excel workbook；或
2. 一份 TLF CSV 与一份 Data CSV。

TLF sheet/CSV 中使用 `Title`、`Type`、`Source Datasets`。Data 中的
`SDTM/ADaM` 与 `Domain/Dataset Name` 只用于识别 source/domain group；
它们不直接参加个人评分。

用户还需要输入 DU Team Lead 名称。Vox/LLM 仅执行一次受限名称匹配：它
只能从 snapshot 中真实存在的 `Team_Lead_Name` 候选列表返回一个**完全一致**
的值。任何新造、纠正或缩写后的团队名称都会被拒绝。

### 输出

页面逐个 TLF 展示 Gen/QC primary、最多两个 backup、得分、当前 active DID
数、最佳历史证据 DID 和必要的 review 提示。同时可下载
`tlf_person_allocation.xlsx`：一行一个输入 TLF，Generation 与 QC 的
primary/backup 分列，并包含 group、score、evidence DID、snapshot 时间和
Team Lead。

## 3. 历史证据：snapshot 而非实时 Neo4j 查询

分配页面本身**不会查询 Neo4j**。维护者在数据更新后手动执行：

```cmd
py tlf_person_allocation.py refresh-snapshot
```

这会生成 `artifacts/tlf_person_allocation_snapshot.joblib`。snapshot 包括：

- 已完成 Delivery 中 `Person x DID x TLF` 的历史记录；
- 每个历史 TLF 的名称、Type、Source、完成日期和 DID；
- `HAS_TLF.Generation` 与 `HAS_TLF.QC` 上的实际 role evidence；
- 每个人当前处于 `Planned` 或 `Ongoing` 状态的 distinct active DID 数量。

读取关系为：

```text
(:Person)-[:WORKS_ON]->(:Delivery)-[:HAS_TLF]->(:TLF)
```

历史证据仅取 `DID_Status = Completed`、具有 DID 和实际交付日期的记录；
当前负担则只计算 `Planned`/`Ongoing` DID。故推荐依据已交付经验和当前负担，
不会将未完成工作误当作已验证经验。

## 4. 候选人如何产生

先选择用户确认的 Team Lead，再只保留该团队中具有对应 role evidence 的人员：

- Generation 候选人必须曾被记录为该历史 TLF 的 `Generation`；
- QC 候选人必须曾被记录为该历史 TLF 的 `QC`。

系统不是将每个输入 TLF 与团队所有历史记录做无限制笛卡尔积。对于每个
“目标 TLF x 人员 x role”，只保留满足至少一种条件的相关历史 TLF：

1. 标题完全一致；或
2. Type 或 Source 一致；或
3. 标准化标题有长度至少 3 的共同词。

这些记录按“标题完全一致、metadata 命中数、共同标题词数、完成日期”排序，
每位人员每个 role 最多取 25 条进入相似度评分。没有满足条件的 role evidence
的人员不会被推荐为该 TLF 的候选人。

## 5. TLF 相似度的计算

### 5.1 标题标准化

目标和历史 TLF 标题都会转为小写；下划线、斜线、反斜线和竖线会转为空格；
其他非字母数字字符被移除，连续空格合并。例如格式差异不会造成不同标题。

### 5.2 确定性字符相似度

TLF allocation 不让 LLM 判断每一个 TLF 是否相似。它使用确定性的 Python
文本向量计算：

```text
HashingVectorizer
analyzer = char_wb
character n-gram range = 3 to 5
L2 normalization
similarity = normalized vector inner product
```

字符 n-gram 可以对单词顺序、标点、复数或轻微拼写/格式变化保持一定鲁棒性。
标准化标题完全一致时相似度为 `1.0`；标题为空时为 `0.0`。

allocation 对一次比较只传入“一个目标标题”和“一个历史标题”，所以这部分
语义相似度只由标题决定。共享底层函数在一般 DID 对 DID 场景可执行
one-to-one greedy TLF matching：从最高分 pair 开始匹配，低于 `0.70` 的 pair
不匹配，且任一 TLF 只能使用一次。当前 allocation 的单 TLF 场景等价于对该
标题 pair 应用相同 `0.70` 阈值。

### 5.3 Type/Source 不与标题重复计分

标题 semantic match 和 Type/Source 分开处理：

- 标题相似度单独决定 40 分中的 semantic 部分；
- Type、Source 仅在二者都非空且标准化后完全相同时分别得到 2.5 分；
- 因此 dataset/类型一致不会被隐性重复加到标题相似度里。

对于一个人，系统会遍历其最多 25 条相关 role evidence，选取**总基础分最高**
的一条作为该人的推荐证据；若基础分相同，选择完成日期更近的记录。

## 6. 个人基础评分：满分 100 分

每个 role 独立评分，分数完全由历史证据和当前 workload 组成：

| 组成 | 最高分 | 计算方法 |
| --- | ---: | --- |
| TLF 标题 semantic match | 40 | `40 x 标题相似度` |
| Exact title experience | 15 | 标准化标题完全一致为 15，否则为 0 |
| Type/Source match | 5 | Type、Source 各 2.5；分别精确匹配才得分 |
| Recent relevant experience | 5 | 仅标题相似度 >= 0.70 时按历史 DID 完成日期衰减 |
| Current active-DID workload | 35 | active DID 越少，得分越高 |

Recent relevant experience 的日期系数为：完成在 180 天内为 `1.0`，181–365 天为
`0.7`，366–730 天为 `0.4`，更早的有效完成记录为 `0.15`；该系数再乘以 5 分。

工作负担分数为：

```text
workload score = 35 x (1 - person's active DID count / team maximum active DID count)
```

如果团队所有候选人的 active DID 数均为 0，则每人均得到完整 35 分。这里衡量
的是当前活跃 DID 的数量，不是本次上传 TLF 被分配后的任务数量。

## 7. Source/domain group 连续性

为减少同一数据来源在团队成员之间不必要的交接，TLF 先被分组。分组优先级为：

1. 若 `Source Datasets` 中的名称可**直接**匹配上传 Data sheet 里的 SDTM
   domain，则 group 为该 SDTM domain；
2. 若不能直接匹配，则用标准化后的原始 `Source Datasets` 组合作为 group；
3. 没有 Source 的 TLF 各自单独成为一个 `Individual` group。

系统不推断 ADaM 与 SDTM 的血缘关系；只有上传数据明确给出的直接名称匹配才会
归入 SDTM group。

每个 group 内：

- Generation primary 最多使用两人；
- QC primary 最多使用另外两人；
- 已成为该 group 某 role primary 的人员，会优先继续承担该 role 的后续 TLF；
- 如果现有 primary 对某个 TLF 没有任何相关 evidence，系统才会在该 role 的
  两人上限内引入另一位人员；
- 某人一旦为 group 的 Generation primary，不会再作为该 group 中其他 TLF 的
  QC primary；QC 到 Generation 同样禁止；
- backup 不受上述 primary roster 限制，以保留替代人员。

## 8. 主推荐、工作量平衡和 QC 保护规则

### 动态平衡

在本次上传的一整轮 allocation 中，每当某人已获得一个 primary assignment，
其后续 primary 排名会扣除：

```text
adjusted primary score = base score - 12 x prior primary assignments
```

这项动态扣分与 35 分的当前 active-DID workload 同时生效：前者避免新工作全部
集中到一个人，后者反映其已经进行中的 DID 负担。系统没有硬性的全局 primary
人数上限，以免在大型输入中因硬限制产生空推荐。

### Gen/QC 独立性和例外

对于同一个 TLF，Gen 和 QC primary 必须为不同人员。只有确认不存在任何其他
具有 QC role evidence 的候选人时，才允许 Generation primary 同时作为 QC
fallback；该行会明确标识：

```text
LEAD REVIEW REQUIRED
```

如果该 Generation primary 本身也没有 QC evidence，则不会虚构 QC primary，
仍要求 Team Lead review。backup 不等同于 primary，不会消除上述 review 要求。

## 9. 相似度缓存、RSC 与性能边界

标题相似度使用共享缓存：

```text
artifacts/did_effort_similarity_cache.joblib
```

cache key 基于标准化的 TLF `title/type/source` 集合 hash；key 有方向性，因为
coverage 可能不同。allocation 实际传入空 Type/Source 的单 TLF pair，因此
该调用的 cache entry 本质上重用的是标题比较结果。命中 cache 时不会重新执行
字符 n-gram 向量计算；miss 会在当前可写 cache 中记录。

Git LFS deployment 中，如果 checkout 获得 LFS pointer，程序会从 GitHub 下载
实际 snapshot/cache 至 RSC 服务端的 artifact cache directory（可通过
`DID_EFFORT_ARTIFACT_CACHE_DIR` 配置），而不会下载到浏览器用户电脑。

需要注意：cache 减少的是相似度计算，不能消除候选收集、逐人评分、group roster
约束和 backup 排序的成本。大规模输入即使 cache 全部命中，仍可能需要显著运行
时间；应将结果用于受控的 Team Lead review，而不是期待实时秒级响应。

RSC 运行中新增的 cache entry 只保留在该运行环境，不会自动回写 GitHub。若要
让其他实例共享新增结果，维护者需要显式发布更新后的 cache artifact。

## 10. 可审计性与限制

每一条推荐都能追溯到：

- 匹配的 Team Lead；
- primary/backup 的历史 role evidence DID；
- 历史证据完成日期和 TLF；
- 每项评分组成、基础分、动态平衡扣分和最终分；
- 当前 active DID 数；
- source/domain group 和任何 `LEAD REVIEW REQUIRED` 原因。

该功能是基于历史已完成工作和规则的决策支持工具，不替代人员技能判断、项目
优先级、可用性、休假、培训状态或 Team Lead 的最终管理决策。
