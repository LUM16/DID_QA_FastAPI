# Question retrieval comparison

Safe questions: **129**. Agent-authored evaluation queries: **60**. Timing repeats per query/method: **30**.

Every safe question has a matching offline review and source hash. **128** questions have **250** review cautions. The source Cypher is unchanged; cautions travel with retrieved examples.

Runtime: Python **3.10.9**, scikit-learn **1.7.2**.

All methods return at most three question-level references. The legacy file-prefix baseline can expose fewer than three complete questions.

| Method | Hit@3 | Precision@3 | Recall@3 | MRR@3 | nDCG@3 | p50 ms | p95 ms | Mean prompt chars |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| flat_tfidf | 0.833 | 0.328 | 0.761 | 0.686 | 0.679 | 0.936 | 4.676 | 4161 |
| categorized_tfidf | 0.083 | 0.044 | 0.078 | 0.067 | 0.069 | 0.806 | 4.941 | 2794 |
| flat_original | 0.367 | 0.139 | 0.311 | 0.272 | 0.267 | 0.764 | 4.337 | 3430 |
| legacy_prefix | 0.017 | 0.006 | 0.017 | 0.017 | 0.017 | 0.022 | 0.081 | 1967 |

## Observed trade-off

Against category-filtered retrieval with identical reviewed vectors, flat retrieval changes Hit@3 by **+75.0 percentage points**, MRR@3 by **+0.619**, and p50 local latency by **+0.130 ms**.

Against the actual legacy prompt, mean retrieved-context size changes by **+2194 characters**. A larger complete-example prompt can increase generation cost/latency even when local retrieval is fast; this experiment does not measure that downstream trade-off.

## Interpretation

- `flat_tfidf`: all safe reviewed questions, without category filtering (production default).
- `categorized_tfidf`: the identical reviewed index, restricted to the original keyword-selected file.
- `flat_original`: all safe original titles, without review paraphrase augmentation.
- `legacy_prefix`: actual original selection of one topic file and its first 2200 characters.

Cold reviewed corpus loading/index construction: **43.471 ms** (imports excluded). Sparse vector matrix: **195664 bytes**, shape **[129, 6992]**, nonzeros **16262**.

## Limits

- Agent-authored paraphrase relevance labels, not independent human gold judgments.
- Recall uses the annotated relevant IDs only; labels may be incomplete.
- Local lexical TF-IDF, not semantic embeddings or downstream answer accuracy.
- Warm timings include selection, transform, scoring and prompt assembly; exclude imports, source I/O, fingerprint checks, warning log I/O, Vox and Neo4j.
- Legacy baseline scores only fully visible examples; partial examples are not executable references.
- Review augmentation is controlled by categorized_tfidf using the same reviewed vectors and flat_original using original titles only.
- Categorized baseline preserves this repository's one-file keyword routing, not an optimized or learned classifier; results do not generalize to all category-based retrieval.
- Prompt character counts are not token counts or measured LLM latency/cost.
- Offline review effort is not included in cold index construction time.

## Per-query retrieval

| Query | Relevant | Flat Top 3 | Categorized Top 3 | Original-title Top 3 | Legacy complete IDs |
|---|---|---|---|---|---|
| e01: For August, break my finished work down into the four task measures for every delivery. | q000 | q077, dashboard_q016, q066 | q000, q001, q010 | q023, q078, q054 | q000 |
| e02: 我在各项研究做了多少工作，占整个研究工作总量的百分比是多少？ | q002 | dashboard_q001, q002, dashboard_q002 | (none) | dashboard_q001, dashboard_q002, dashboard_q003 | (none) |
| e03: Show me the elapsed labour and output-item quantities side by side for each of my delivery IDs. | q005 | q073, q065, q076 | q073, q108, q107 | q020, q091, q078 | q040, q043 |
| e04: 过去一个季度我最熟悉和最少碰到的SDTM域分别是什么？请把次数也列出来。 | q007 | q007, q003, q015 | q140_2, q112, q076 | q140_2, dashboard_q001, dashboard_q002 | q075 |
| e05: Arrange my previous study assignments first by therapeutic area, then by data domain. | q008 | q008, q125, q099 | q104, q070, q096 | q008, q099, q070 | q040, q043 |
| e06: For a selected protocol, total the effort I recorded during the latest fourteen days. | q009 | dashboard_q013, q114, q092 | (none) | q002, dashboard_q009, q001 | (none) |
| e07: 用我近半年的记录算一算，平均做一项任务要几小时？ | q011 | q000, q011, q039 | q000, q011, q016 | dashboard_q001, dashboard_q002, dashboard_q003 | q000 |
| e08: Which delivery absorbed the biggest share of my effort recently, looking only at the last fortnight? | q013 | q056, q055, q091 | q120, q078, q040 | q095, q055, q091 | q040, q043 |
| e09: 为我的直属员工填写PLI准备半年度业绩依据，包括研究数、输出量和任务量。 | q016 | q016, dashboard_q006, q001 | q016, q001, q011 | q016, dashboard_q001, dashboard_q002 | q000 |
| e10: What unfinished commitments are due over the coming fortnight, and in what order should I tackle them? | q018, q082, q089, q028 | q082, q017, dashboard_q006 | (none) | q062, q012, q045 | (none) |
| e11: 把我手头正在进行的交付逐条列出，并算出距离截止日期还有几天。 | q019 | q019, dashboard_q006, q018 | q077, q043, q104 | dashboard_q001, dashboard_q002, dashboard_q003 | q040, q043 |
| e12: As the study programming lead, what delivery commitments fall within the coming quarter? | q020 | q025, q062, q020 | q113, q106, q077 | q062, q025, q020 | q040, q043 |
| e13: 我的LoT分工里编程和复核各有多少，能据此看出后续负担吗？ | q022 | q022, q140_2, dashboard_q009 | q140_2, q140_1, q075 | dashboard_q009, q022, q075 | q075 |
| e14: Count next month's assigned figures, listings and tables separately for production and checking. | q025 | q025, q003, q060 | (none) | q025, q075, q060 | (none) |
| e15: 按既往做事速度，未来一个季度这些工作大概要占我多少小时？ | q029 | q024, q039, q054 | (none) | dashboard_q001, dashboard_q002, dashboard_q003 | (none) |
| e16: Give me this week's final dLoT assignments, grouped under their protocols with generator and checker roles. | q030 | q030, q028, q140_2 | q140_2, q109, q133 | q030, q109, q028 | q075 |
| e17: If my weekly budget is forty working hours, how should it be divided across the projects I support? | q039 | q039, q089, q011 | q011, q009, q005 | q089, q091, q039 | q000 |
| e18: 请比较我去年上半年与下半年的产出效率和每项任务所花时间。 | q042 | q042, q046, q023 | q011, q000, q010 | dashboard_q001, dashboard_q002, dashboard_q003 | q000 |
| e19: For a protocol of my choosing, show the finished delivery milestones and how actual dates differed from the plan. | q040 | q043, q040, q096 | q091, q030, q019 | dashboard_q010, q042, q049 | q017, q018, q019 |
| e20: 我们DU各位同事做过哪些研究，又实际接触过什么域？ | q045 | q082, q045, q096 | (none) | q051, q059, q062 | (none) |
| e21: Contrast my team's delivered workload in the two semesters of a given year. | q046 | q113, q046, dashboard_q012 | q002, q003, q009 | q113, q109, q129 | q000 |
| e22: 从今年二月开始，我的组员完成任务数和全部门人均水平相比如何？ | q048 | q048, q047, q054 | q000, q003, q011 | dashboard_q001, dashboard_q002, dashboard_q003 | q000 |
| e23: Build a member-by-member account of our recent completed work alongside the commitments ahead. | q053 | q057, q053, q047 | q012, q009, q010 | q057, q062, q021 | q000 |
| e24: 未来几个月里，哪些组员和我本人完全没有交付安排？先看下个月。 | q060 | q060, q082, q024 | q120, q072, q108 | dashboard_q001, dashboard_q002, dashboard_q003 | q040, q043 |
| e25: Break the team's forward task plan into a grid of people and calendar months. | q057 | q120, dashboard_q002, dashboard_q012 | q000, q001, q002 | q120, q049, q112 | q000 |
| e26: 我负责的DU未来交付任务量比同一部门其他DU高还是低？ | q063 | q063, q088, dashboard_q004 | q002, q001, q000 | q051, q059, q062 | q000 |
| e27: Within one study delivery, what did each contributor deliver, and how large was their share of the combined work? | q067, q078 | q070, q002, q077 | q070, q077, q073 | q005, q078, q002 | q040, q043 |
| e28: 针对一个指定DID，请给出所有参与者的累计工时及逐月明细。 | q070 | q070, sub003, q078 | q009, q006, q013 | dashboard_q009, q013, q005 | q000 |
| e29: Find this month's deliveries whose reporting descriptions mention CSR. | q072 | q072, q120, q093 | dashboard_q007, dashboard_q011, dashboard_q015 | q072, dashboard_q011, q108 | dashboard_q001 |
| e30: 两个交付版本的数据集与输出清单有哪些新增和缺失？ | q076, q101 | q140_3, q101, q005 | q043, q072, q104 | dashboard_q001, dashboard_q002, dashboard_q003 | q040, q043 |
| e31: For this delivery, deduplicate the output titles and count the distinct ones under each source domain. | q075 | q075, q110, q109 | q072, q066, q077 | q072, q030, q099 | q040, q043 |
| e32: 未来两个月我的哪些交付可能撞期，需要同时处理？ | q080 | q080, q082, q018 | q107, q121, q077 | dashboard_q001, dashboard_q002, dashboard_q003 | q040, q043 |
| e33: Find the work assigned to me that has no corresponding time entry anywhere in its history. | q083, q092 | q107, q092, q113 | (none) | q113, q029, q108 | (none) |
| e34: 根据过去和未来季度任务量的变化，哪些人可能变成资源瓶颈？ | q084 | q084, q011, q056 | q011, q118, q001 | dashboard_q001, dashboard_q002, dashboard_q003 | q000 |
| e35: Prepare the TA leader's next fortnight delivery briefing for everyone further down the reporting tree. | q090 | dashboard_q015, q090, dashboard_q016 | q072, q113, q120 | q090, q125, q063 | q040, q043 |
| e36: 这个DID在什么平台执行？把CDARS或者SIGMA的目录位置给我。 | q093 | q093, q071, q005 | q071, q078, q121 | q093, dashboard_q009, q013 | q040, q043 |
| e37: I need an example output for an unfamiliar topic; which deliveries have a title close to the one I describe? | q094, q100 | q103, q100, q040 | (none) | q103, q100, q040 | (none) |
| e38: 某张表在哪次最新交付里能找到？按实际日期找最近版本。 | q095 | q095, q096, q040 | q096, q040, q108 | dashboard_q001, dashboard_q002, dashboard_q003 | q040, q043 |
| e39: Across which delivery IDs has this same named output been used? | q097, q111 | q092, q111, q097 | q108, q107, q040 | q055, q097, q134 | q040, q043 |
| e40: 找出不同DID之间重名的表格，看看有哪些交付共用了标题。 | q103 | q103, q094, q082 | q104, q077, q120 | dashboard_q009, q013, q005 | q040, q043 |
| e41: Who programmed and independently checked the outputs sourced from ADLB in the chosen protocol? | q109 | q120, q060, sub002 | (none) | q120, sub002, q075 | (none) |
| e42: 给我这个交付各张TLF的正式编号，而不是只给标题。 | q110 | q103, q110, q111 | q077, q067, q106 | q110, dashboard_q001, q140_1 | q040, q043 |
| e43: Which colleagues in my immediate team have worked on survival curves and could help with a rush assignment? | q129 | q129, q130, q015 | q063, q068, q065 | q015, q007, q129 | (none) |
| e44: 需要找个懂统计建模的同事请教，从历史输出经验看谁合适？ | q131 | q131, q130, q129 | (none) | dashboard_q001, dashboard_q002, dashboard_q003 | (none) |
| e45: Look at the study's successive versions and point out when the analysis-dataset programmer or checker changed. | q140_3 | q113, q140_3, q140_1 | q113, q120, q096 | q002, dashboard_q012, q106 | q040, q043 |
| e46: 选定季度里，哪十项研究的已完成TLF输出量最大？也要负责人信息。 | dashboard_q003 | dashboard_q001, dashboard_q003, dashboard_q002 | q131, q097, q109 | q110, dashboard_q001, q140_1 | q075 |
| e47: List protocols led by an SDSL based in the Indian office, including their study milestone information. | dashboard_q007 | dashboard_q008, q113, dashboard_q007 | q113, q106, q120 | dashboard_q008, q106, q018 | q040, q043 |
| e48: 只看目前活跃的三期研究，列出SDSL和上级负责人。 | dashboard_q008 | dashboard_q008, q113, dashboard_q001 | (none) | q113, dashboard_q008, dashboard_q007 | (none) |
| e49: For one delivery ID I want the complete inventory: datasets, outputs, assigned programmers, checkers and file identifiers. | dashboard_q009 | q070, q067, q078 | sub004, sub002, sub001 | dashboard_q013, q078, q070 | (none) |
| e50: 某研究正在做的人员还同时承担哪些其他研究的活跃交付？ | dashboard_q012 | dashboard_q012, q112, sub002 | q113, q043, q096 | dashboard_q001, dashboard_q002, dashboard_q003 | q040, q043 |
| e51: Compare offices year by year on finished delivery output, logged effort and effort per task. | dashboard_q014 | dashboard_q013, dashboard_q005, dashboard_q016 | q005, q010, q011 | dashboard_q014, q046, q048 | q000 |
| e52: 在一个TA负责人范围内，按各组负责人比较已交付工作及耗时。 | dashboard_q016 | dashboard_q016, dashboard_q008, q061 | q113, q121, q106 | q061, dashboard_q015, q125 | q040, q043 |
| e53: For my chosen study, who owns each SDTM or analysis domain, and which colleagues collaborated with them during a selected interval? | q106, q126 | q126, q002, q059 | q077, q073, q120 | q001, q126, q002 | q040, q043 |
| e54: 既想看团队近期每个DID耗时和任务量，也想知道下个月各成员预计工作多少。 | q056, q062 | dashboard_q005, q056, q062 | q001, q012, q016 | dashboard_q009, q013, q005 | q000 |
| e55: Show the full delivery list for a protocol and locate its responsible study lead. | q096, q104, q113 | q113, q114, q110 | q113, q104, q096 | dashboard_q010, sub001, q113 | q040, q043 |
| e56: 给同事安排新的Kaplan-Meier输出之前，先查谁有相关经验，再看看这些人的其他活跃交付。 | q133, q130, dashboard_q012 | dashboard_q012, q129, q130 | q023, q038, q082 | q130, q129, q133 | q017, q018, q019 |
| e57: Summarize a programmer's therapeutic-area experience, then suggest unfamiliar studies or domains they could take on next. | q125, q117, q118 | q117, q118, q125 | (none) | q117, q118, q131 | (none) |
| e58: 这项申报由谁牵头？另外请列出所选研究参与交付的人员。 | q121, q112, q120 | q112, q106, q121 | q106, q121, q120 | dashboard_q001, dashboard_q002, dashboard_q003 | q040, q043 |
| e59: For the selected study, compare ownership handoffs across versions separately for tables and for tabulation domains. | q140_1, q140_2 | q140_2, q140_3, q140_1 | q106, q040, q120 | q140_1, q140_2, q140_3 | q040, q043 |
| e60: 先查自己现在可填日报的交付编号，再查哪些已分配交付一直没有工时记录。 | q107, q139, q083, q092 | q083, q092, q107 | q001, q010, q009 | dashboard_q001, dashboard_q002, dashboard_q003 | q000 |
