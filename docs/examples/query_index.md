# DID Agent Query Library Index

This index organizes the original `cypher examples.docx` into topic-based Markdown files for DID Agent few-shot prompting.

## Files

- `person_productivity.md` - Person Productivity Examples
- `workload_planning.md` - Workload Planning Examples
- `study_delivery.md` - Study and Delivery Examples
- `lot_tlf_sdtm_adam.md` - LoT, TLF, SDTM, ADaM Examples
- `team_manager.md` - Team, DU, Manager and TA Lead Examples
- `reporting_dashboard.md` - Reporting Dashboard Examples
- `sensitive_excluded.md` - examples not recommended for production prompt loading
- `uncategorized.md` - parsed safe examples not yet assigned to a topic

## Recommended loading strategy

1. Always load `skill.md` and `schema.md`.
2. For CLI MVP, load all topic files except `sensitive_excluded.md`.
3. For production, use retrieval: select only the 3-5 most similar examples for each user question.
4. Keep `reporting_dashboard.md` as high-priority examples for KPI/dashboard questions.