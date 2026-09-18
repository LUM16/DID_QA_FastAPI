# DU Team Recommendation

## 目的

**Recommend DU Team** 根据新 Delivery 的 TLF scope，为指定 Group Lead 下当前
所属的 DU Team 排序。它是基于已完成 DID 经验和当前 active DID work burden 的
可解释决策支持工具，不是训练模型，不自动修改 Neo4j assignment。

DU 由 `Person.Team_Lead_Name` 定义；Group 由 `Person.Group_Lead_Name` 定义。
两者均使用 snapshot 刷新时的当前人员组织归属，而不是 DID 历史完成时的组织快照。

## 用户输入

页面要求：

1. 输入 Group Lead 名称，例如 `Maggie`；
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

输入 `Maggie` 时，程序只会从 snapshot 中真实存在的 `Group_Lead_Name` 候选中
确定唯一匹配，例如 `Zhang, Maggie`。若没有匹配或有多个匹配，会提示用户输入更
明确的名称，不会猜测或创建组织名称。

## Snapshot 与刷新

页面运行时不查询 Neo4j。维护者在 Neo4j 数据或人员组织关系更新后执行：

```cmd
py du_team_recommendation.py refresh-history
```

生成的 `artifacts/du_team_history_snapshot.joblib` 包含：

- DU Team Lead；
- 该 DU 当前关联的 Group Lead 名称；
- 该 DU 已完成 DID 的 TLF title/type/source 和实际完成日期；
- 每个 DU 当前的 distinct Planned + Ongoing DID 数。

推荐时首先以输入的 Group Lead 过滤 snapshot，只对该 Group 下的 DU 评分。旧版
snapshot 未保存 Group Lead，无法安全支持过滤；升级代码后必须先运行一次
`refresh-history` 生成新版 snapshot。

在 Git LFS/RSC 部署中，如 checkout 只有 LFS pointer，程序会从 GitHub 下载完整
snapshot 到 RSC 服务端 artifact cache。可通过
`DU_TEAM_HISTORY_SNAPSHOT_PATH` 或 `DU_TEAM_HISTORY_SNAPSHOT_URL` 配置路径。

## TLF coverage：可跨多个历史 DID 合并

系统逐条处理上传的目标 TLF。每条 TLF 在该 DU 的 completed history 中寻找最佳
有效历史匹配，标题 semantic match 必须达到 `>= 0.70`。

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
| Current active-DID workload | 35 | `35 × (1 - DU active DID count / selected Group 中最大 active DID count)`；active DID 越少，得分越高。 |

`Active DID` 是该 DU 成员参与的 distinct Planned + Ongoing Delivery 数量，不代表
精确 FTE capacity、请假、剩余工时或本次 Delivery 的实际工作量。

## 展示与审计

结果显示：

- 选定的 Group Lead；
- 该 Group 下 DU Team 的排名与总分；
- TLF semantic coverage；
- Similar DID 数量、Completed DID 数量、semantic candidate DID 数量；
- Current active DID 数；
- 每个输入 TLF 的 evidence DID 和完成日期；
- 最相似的最多五个历史 completed DID。

`Recommended` 表示总分至少 80；`Suitable with review`、`Backup option` 和
`Insufficient evidence` 分别对应 65、45 和更低的分数阈值。最终分配仍应由
Group/Team Lead 审核，尤其需结合技能、可用性、优先级和休假等未记录信号。

## 缓存与性能

TLF 标题相似度使用与 effort prediction 共享的：

```text
artifacts/did_effort_similarity_cache.joblib
```

cache key 基于标准化后的 TLF `title/type/source` 内容，不包含 DID、人员、DU 或
最终分数。cache hit 只避免重复相似度计算，不改变推荐结果。RSC 新产生的 cache
entry 只保留在该运行环境，不能自动回写 GitHub。
