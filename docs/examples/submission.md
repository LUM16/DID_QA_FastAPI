# Submission Examples

> Use these as few-shot examples for DID Agent Text-to-Cypher. Replace the keyword literals with the words from the user's question.

Search rule: split the submission description into keywords. A Submission matches when `Project_Name` contains every keyword, or when `Name` contains every keyword. Compare with `toUpper`. Do not require both fields to match.

A study contributes to a submission through either path:

- `(Study)-[:HAS_DELIVERY]->(Delivery)-[:SUPPORT_SUBMISSION]->(Submission)`
- `(Study)-[:HAS_DID0]->(DID0)-[:SUPPORT_SUBMISSION]->(Submission)`

DSP category is `Study_Info.DSP_Flag`, reached by `(Study)-[:HAS_DETAIL]->(Study_Info)`.

China participation uses three paths. Do not put the China site filter inside `OPTIONAL MATCH`:

- A China delivery contributor: `(Person)-[:WORKS_ON]->(Delivery)-[:SUPPORT_SUBMISSION]->(Submission)` and `(Person)-[:FROM_SITE]->(Site)` where `Site.Name` or `Site.Category` is `China`.
- A China study SDSL: the contributing study's `Study.SDSL` is a Person from that China site.
- A China PoC: `Study.SDSA_China_PoC` or `Delivery.SDSA_China_PoC` is non-blank on a contributing study or supporting delivery.

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

## sub002: Who in China contributed to Litfulo vitiligo submission

**Business intent**  
Find China contributors to the Litfulo vitiligo submission. Count a person when they work on a supporting delivery and belong to the China site, when they are the China-site SDSL of a contributing study, or when they are named as China PoC.

**Cypher**

```cypher
MATCH (sub:Submission)
WHERE (sub.Project_Name IS NOT NULL AND toUpper(sub.Project_Name) CONTAINS 'LITFULO' AND toUpper(sub.Project_Name) CONTAINS 'VITILIGO')
   OR (sub.Name IS NOT NULL AND toUpper(sub.Name) CONTAINS 'LITFULO' AND toUpper(sub.Name) CONTAINS 'VITILIGO')
WITH DISTINCT sub
MATCH (p:Person)-[:WORKS_ON]->(d:Delivery)-[:SUPPORT_SUBMISSION]->(sub)
MATCH (p)-[:FROM_SITE]->(site:Site)
WHERE toUpper(trim(site.Name)) = 'CHINA' OR toUpper(trim(coalesce(site.Category, ''))) = 'CHINA'
WITH p, collect(DISTINCT d.Name) AS Evidence
RETURN p.Name AS Person, p.NTID AS NTID, 'Delivery contributor' AS Contribution, Evidence
UNION
MATCH (sub:Submission)
WHERE (sub.Project_Name IS NOT NULL AND toUpper(sub.Project_Name) CONTAINS 'LITFULO' AND toUpper(sub.Project_Name) CONTAINS 'VITILIGO')
   OR (sub.Name IS NOT NULL AND toUpper(sub.Name) CONTAINS 'LITFULO' AND toUpper(sub.Name) CONTAINS 'VITILIGO')
WITH DISTINCT sub
MATCH (s:Study)
OPTIONAL MATCH (s)-[:HAS_DELIVERY]->(d:Delivery)-[:SUPPORT_SUBMISSION]->(sub)
OPTIONAL MATCH (s)-[:HAS_DID0]->(did0:DID0)-[:SUPPORT_SUBMISSION]->(sub)
WITH s, d, did0
WHERE (d IS NOT NULL OR did0 IS NOT NULL)
  AND s.SDSL IS NOT NULL AND trim(s.SDSL) <> ''
MATCH (p:Person)-[:FROM_SITE]->(site:Site)
WHERE replace(toUpper(p.Name), ' ', '') = replace(toUpper(trim(s.SDSL)), ' ', '')
  AND (toUpper(trim(site.Name)) = 'CHINA' OR toUpper(trim(coalesce(site.Category, ''))) = 'CHINA')
WITH p, collect(DISTINCT s.Name) AS Evidence
RETURN p.Name AS Person, p.NTID AS NTID, 'Study SDSL' AS Contribution, Evidence
UNION
MATCH (sub:Submission)
WHERE (sub.Project_Name IS NOT NULL AND toUpper(sub.Project_Name) CONTAINS 'LITFULO' AND toUpper(sub.Project_Name) CONTAINS 'VITILIGO')
   OR (sub.Name IS NOT NULL AND toUpper(sub.Name) CONTAINS 'LITFULO' AND toUpper(sub.Name) CONTAINS 'VITILIGO')
WITH DISTINCT sub
MATCH (d:Delivery)-[:SUPPORT_SUBMISSION]->(sub)
WHERE d.SDSA_China_PoC IS NOT NULL AND trim(d.SDSA_China_PoC) <> ''
OPTIONAL MATCH (p:Person)
WHERE replace(toUpper(p.Name), ' ', '') = replace(toUpper(trim(d.SDSA_China_PoC)), ' ', '')
WITH coalesce(p.Name, trim(d.SDSA_China_PoC)) AS Person, p.NTID AS NTID, collect(DISTINCT d.Name) AS Evidence
RETURN Person, NTID, 'China PoC' AS Contribution, Evidence
UNION
MATCH (sub:Submission)
WHERE (sub.Project_Name IS NOT NULL AND toUpper(sub.Project_Name) CONTAINS 'LITFULO' AND toUpper(sub.Project_Name) CONTAINS 'VITILIGO')
   OR (sub.Name IS NOT NULL AND toUpper(sub.Name) CONTAINS 'LITFULO' AND toUpper(sub.Name) CONTAINS 'VITILIGO')
WITH DISTINCT sub
MATCH (s:Study)
OPTIONAL MATCH (s)-[:HAS_DELIVERY]->(d:Delivery)-[:SUPPORT_SUBMISSION]->(sub)
OPTIONAL MATCH (s)-[:HAS_DID0]->(did0:DID0)-[:SUPPORT_SUBMISSION]->(sub)
WITH s, d, did0
WHERE (d IS NOT NULL OR did0 IS NOT NULL)
  AND s.SDSA_China_PoC IS NOT NULL AND trim(s.SDSA_China_PoC) <> ''
OPTIONAL MATCH (p:Person)
WHERE replace(toUpper(p.Name), ' ', '') = replace(toUpper(trim(s.SDSA_China_PoC)), ' ', '')
WITH coalesce(p.Name, trim(s.SDSA_China_PoC)) AS Person, p.NTID AS NTID, collect(DISTINCT s.Name) AS Evidence
RETURN Person, NTID, 'China PoC' AS Contribution, Evidence
ORDER BY Person, Contribution
LIMIT 50
```
