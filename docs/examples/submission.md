# Submission Examples

> Use these as few-shot examples for DID Agent Text-to-Cypher. Replace the keyword literals with the words from the user's question.

Search rule: split the submission description into keywords. A Submission matches when `Project_Name` contains every keyword, or when `Name` contains every keyword. Compare with `toUpper`. Do not require both fields to match.

A study contributes to a submission through either path:

- `(Study)-[:HAS_DELIVERY]->(Delivery)-[:SUPPORT_SUBMISSION]->(Submission)`
- `(Study)-[:HAS_DID0]->(DID0)-[:SUPPORT_SUBMISSION]->(Submission)`

DSP category is `Study_Info.DSP_Flag`, reached by `(Study)-[:HAS_DETAIL]->(Study_Info)`.

## sub001: Please list the studies that contribute to Litfulo vitiligo submission and show study DSP category.

**Business intent**  
Find studies that support the Litfulo vitiligo submission, through a delivery or through DID0, and return each study with its DSP category.

**Parameters**

```json
{
  "keywords": ["LITFULO", "VITILIGO"]
}
```

**Cypher**

```cypher
MATCH (sub:Submission)
WHERE (sub.Project_Name IS NOT NULL AND toUpper(sub.Project_Name) CONTAINS 'LITFULO' AND toUpper(sub.Project_Name) CONTAINS 'VITILIGO')
   OR (sub.Name IS NOT NULL AND toUpper(sub.Name) CONTAINS 'LITFULO' AND toUpper(sub.Name) CONTAINS 'VITILIGO')
WITH DISTINCT sub
MATCH (s:Study)
OPTIONAL MATCH (s)-[:HAS_DELIVERY]->(d:Delivery)-[:SUPPORT_SUBMISSION]->(sub)
OPTIONAL MATCH (s)-[:HAS_DID0]->(did0:DID0)-[:SUPPORT_SUBMISSION]->(sub)
WITH s, d, did0
WHERE d IS NOT NULL OR did0 IS NOT NULL
OPTIONAL MATCH (s)-[:HAS_DETAIL]->(si:Study_Info)
RETURN DISTINCT s.Name AS Study, si.DSP_Flag AS DSP_Category
ORDER BY Study
LIMIT 50
```
