# 预测快照与实际工时校验

`validate_effort_predictions.py` 用于在 Neo4j 刷新后，将**已保存的预测快照**
与最新数据库中已完成 DID 的实际工时进行比较。

## 为什么需要预测快照

预测发生后，DID 的任务内容、人员分配、模型版本和 Neo4j 数据都可能变化。因此，
请保留预测当天的 CSV，不要被下一次导出覆盖。例如：

```cmd
py effort_prediction.py export-ongoing --output data\ongoing_did_predictions_2026-09-15.csv
```

该文件的每一行是一个 `Person x DID` 预测，含 P50、P80 和 P90。

## 在 Neo4j 刷新后执行校验

```cmd
py validate_effort_predictions.py ^
  --input data\ongoing_did_predictions_2026-09-15.csv ^
  --output data\prediction_actual_comparison_2026-09-15.csv ^
  --report data\prediction_validation_report_2026-09-15.md
```

脚本会：

1. 读取预测快照的 `person` 与 `did`；
2. 仅匹配当前 `DID_Status = completed` 的相同 `Person x DID`；
3. 汇总该人员在该 DID 的 `TIME_ON.Hour`，作为 `actual_hours`；
4. 写出已完成项目的比较 CSV 和 Markdown 汇总报告。

尚未完成、在新版数据库中不再可精确匹配的项目不会进入比较 CSV，报告会统计其数量；
下一次数据刷新后可使用同一预测快照再次执行。

## 比较 CSV 字段

输出保留原预测快照字段，另增加：

- `completed_date`
- `actual_hours`
- `actual_time_record_count`
- `error_hours = actual_hours - p50_hours`
- `absolute_error_hours`
- `p80_covered`
- `p90_covered`

`p80_covered` 和 `p90_covered` 用于检查实际工时是否落在模型的风险缓冲范围内。
若 `actual_time_record_count = 0`，该 DID 已完成但没有记录工时；它会以
`actual_hours = 0` 保留在结果中，避免被静默忽略。

## Markdown 报告指标

- 已比较数量和未完成/无法匹配数量；
- MAE 和中位绝对误差；
- WAPE；
- 平均误差（`Actual - P50`；正值表示模型偏低估）；
- P80 与 P90 coverage。

比较 CSV 可直接作为后续 Streamlit 图表的数据源。
