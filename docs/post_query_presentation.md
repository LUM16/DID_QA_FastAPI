# Post-query result presentation

Normal graph questions follow the existing read-only Text-to-Cypher flow:

```text
question -> LLM-generated read-only Cypher -> Neo4j rows
         -> constrained presentation selection -> answer, optional chart/table
```

After Neo4j returns rows, a separate Vox call can select exactly one view:
`table`, `kpi_table`, `bar`, `horizontal_bar`, `line`, `stacked_bar`,
`grouped_bar`, or `pie`. It receives only the actual return-field names and
final rows. It cannot request Cypher, calculations, aggregation, renamed fields,
or transformed values.

The Streamlit UI then merges two presentation styles:

- **DID Insight2**: tabbed result views, CSV/JSON download, 👍/👎 feedback,
  labeled canvas bar/line/pie charts with hover tooltips, organization charts,
  and relationship graphs.
- **DID_QA-main**: validated field selection, stacked/grouped/series Streamlit
  charts, and an always-available table fallback.

`result_presentation.py` parses the JSON selection and validates it in Python.
Every selected field must be an actual returned field. Chart x/series values must
be present, and every chart y value must be a finite numeric value. Empty or
invalid data therefore cannot produce a chart. A chart payload always carries a
table fallback; `table` and `kpi_table` carry a table payload directly.

Thumbs-up feedback stores the question and Cypher in `data/memory/` and injects
those pairs back into later Cypher prompts as positive few-shot examples.

Presentation is deliberately optional. By default, a valid chart or table is
visual-only and the app skips the natural-language answer call. The selector may
set `summary_required: true` only when a short conclusion is necessary; that
summary is limited to two sentences and cannot repeat row details. Invalid JSON,
an unsupported selection, or a presentation-call failure produces no
visualization but never changes a successful Cypher result or its
natural-language answer.

Labels are deterministic: `hours`, `recorded_hours`, and `time_on_hours` are
labelled **Recorded TIME_ON hours**; `task_count` is labelled **Assigned task
count**. Other fields receive no inferred unit.
