# Team Recommendation

## 目的

**Recommend Team** 根据新 Delivery 的 TLF scope，跨 Group 比较所选 TA Lead 下当前所属的
所有合格团队。它是基于已完成 DID 经验和当前 active DID work burden 的
可解释决策支持工具，不是训练模型，不自动修改 Neo4j assignment。

DU 由 `Person.Team_Lead_Name` 定义；Group 由 `Person.Group_Lead_Name` 定义。TA
mapping 使用成员的 `Person.TA_Lead_Name`，但仅接受能匹配到正式 `Person.TA_Lead = "Y"`
人员节点的名称。三层均使用 snapshot 刷新时的当前人员组织归属，而不是 DID 历史完成时的
组织快照。

## 用户输入

页面要求：

1. 从可搜索下拉菜单选择 `Shen, Henry` 或 `Iyer, Priya Venkatesan`；
2. 上传新 Delivery 的 TLF scope：
   - 具有 `TLF` sheet 的 Excel workbook；或
   - 一个 TLF CSV。

TLF 使用以下列：

| 字段 | 用途 |
| --- | --- |
| `Title` | TLF 标题语义匹配 |
| `Type` | TLF 匹配辅助元数据 |
| `Source Datasets` | TLF 匹配辅助元数据 |

ADaM/SDTM Data sheet 或 CSV 不再参与 DU recommendation；页面不计算、不展示
ADaM/SDTM coverage 或 Missing ADaM/SDTM。

页面仅列出 snapshot 中有有效团队映射的 Henry / Priya，缺少映射时显示提示。
不再要求选择 Group Lead；所选 TA 下不同 Group 的团队进入同一个比较池。
用户可输入几个字符过滤候选，但必须选择完整候选名称，不能猜测或创建组织名称。

## Snapshot 与刷新

页面运行时不查询 Neo4j。维护者在 Neo4j 数据或人员组织关系更新后执行：

```cmd
py du_team_recommendation.py refresh-history
```

生成的 `artifacts/du_team_history_snapshot.joblib` 包含：

- DU Team Lead；
- 该 DU 当前成员的 TA Lead + Group Lead 成对组织映射；
- 该 DU 成员实际负责 Generation 或 QC 的 completed-DID TLF
  title/type/source 和实际完成日期；
- 每个 DU 当前的 distinct Planned + Ongoing DID 数。

推荐时按输入 TA Lead 的真实成员级组织映射过滤 snapshot，不按 Group 过滤。
所有具有 completed-DID 历史的合格团队均参与评分，页面默认展示前三名及候选团队总数。
团队不会因多条历史记录或多个 Group 映射而重复排名。
现有 v4 TA/Group snapshot 可直接复用；更旧的 snapshot 必须运行 `refresh-history` 更新。

在 Git LFS/RSC 部署中，如 checkout 只有 LFS pointer，程序会从 GitHub 下载完整
snapshot 到 RSC 服务端 artifact cache。可通过
`DU_TEAM_HISTORY_SNAPSHOT_PATH` 或 `DU_TEAM_HISTORY_SNAPSHOT_URL` 配置路径。

## TLF coverage：可跨多个历史 DID 合并

系统逐条处理上传的目标 TLF。每条 TLF 只在该 DU 成员实际被记录为
`HAS_TLF.Generation` 或 `HAS_TLF.QC` 的 completed-DID TLF 中寻找最佳有效历史
匹配；仅参与同一 DID、但没有负责该表的成员不贡献 coverage。标题 semantic match
必须达到 `>= 0.70`。

标题先标准化，再使用 character 3–5 gram 向量相似度；Type 和 Source 在两边均有
值且精确一致时作为辅助 metadata。每条目标 TLF 都必须实际匹配，不能只因同一
Delivery 中存在其他相似 TLF 而被计为覆盖。

因此，若：

```text
目标：TLF-A、TLF-B
历史 DID-1：TLF-A
历史 DID-2：TLF-B
```

则：

```text
TLF semantic coverage = 2 / 2 = 100%
```

页面的 **TLF coverage evidence across completed DIDs** 表会逐条展示目标 TLF 是否
covered、其 evidence DID 及完成日期，便于审核跨 DID 累积经验。

## 评分：100 分

```text
Overall score =
  37 × TLF semantic coverage
+ 18 × Similar DID experience
+ 10 × Recent relevant experience
+ 35 × Current active-DID workload
```

| 指标 | 权重 | 定义 |
| --- | ---: | --- |
| TLF semantic coverage | 37 | 已由该 DU 历史中任一 completed DID 有效匹配的目标 TLF 比例。 |
| Similar DID experience | 18 | 仍以**单个**历史 DID 的完整 TLF coverage 评价，避免将零散工作误报为完整相似 Delivery。`0.6 × best single-DID similarity + 0.4 × min(1, similar DID count / 5)`。 |
| Recent relevant experience | 10 | 仅对 single-DID similarity `>= 0.70` 的 DID 计算；最近 180/365/730 天系数为 1.0/0.7/0.4，更早为 0.15。 |
| Current active-DID workload | 35 | `35 × (1 - team active DID count / 所选 TA 下合格候选团队的最大 active DID count)`；active DID 越少，得分越高。若候选团队均为零，则均得到 35 分。其他 TA 的 workload 不参与归一化。 |

`Active DID` 是该 DU 成员参与的 distinct Planned + Ongoing Delivery 数量，不代表
精确 FTE capacity、请假、剩余工时或本次 Delivery 的实际工作量。

## 展示与审计

结果显示：

- 选定的 TA Lead 和跨 Group 的候选团队总数；
- 该 TA 下团队的排名与总分，及各团队所属的 Group Lead（仅作结果信息）；
- TLF semantic coverage；
- Similar DID 数量、Completed DID 数量、semantic candidate DID 数量；
- Current active DID 数；
- 每个输入 TLF 的 evidence DID 和完成日期；
- 最相似的最多五个历史 completed DID。

`Recommended` 表示总分至少 80；`Suitable with review`、`Backup option` 和
`Insufficient evidence` 分别对应 65、45 和更低的分数阈值。最终分配仍应由
Group/Team Lead 审核，尤其需结合技能、可用性、优先级和休假等未记录信号。

页面 tab、标题、按钮与图表使用 “Team” 命名；内部模块、snapshot 文件和
`du_team` 字段保持原名，以兼容既有 artifact 和 TLF allocation。

## 缓存与性能

TLF 标题相似度使用与 effort prediction 共享的：

```text
artifacts/did_effort_similarity_cache.joblib
```

cache key 基于标准化后的 TLF `title/type/source` 内容，不包含 DID、人员、DU 或
最终分数。cache hit 只避免重复相似度计算，不改变推荐结果。RSC 新产生的 cache
entry 只保留在该运行环境，不能自动回写 GitHub。
