# Submission Examples

> Use these as few-shot examples for DID Agent Text-to-Cypher. Replace the keyword literals with the words from the user's question.

Search rule: split the submission description into keywords. A Submission matches when `Project_Name` contains every keyword, or when `Name` contains every keyword. Compare with `toUpper`. Do not require both fields to match. Do not match `Name` alone. Hours questions use this same match.

A study contributes to a submission through either path:

- `(Study)-[:HAS_DELIVERY]->(Delivery)-[:SUPPORT_SUBMISSION]->(Submission)`
- `(Study)-[:HAS_DID0]->(DID0)-[:SUPPORT_SUBMISSION]->(Submission)`

DSP category is `Study_Info.DSP_Flag`, reached by `(Study)-[:HAS_DETAIL]->(Study_Info)`.

China participation uses three paths. Do not put the China site filter inside `OPTIONAL MATCH`:

- A China delivery contributor: `(Person)-[:WORKS_ON]->(Delivery)-[:SUPPORT_SUBMISSION]->(Submission)` and `(Person)-[:FROM_SITE]->(Site)` where `Site.Name` or `Site.Site_Category` is `China`.
- A China study SDSL: the contributing study's `Study.SDSL` is a Person from that China site.
- A China PoC: `Study.SDSA_China_PoC` is non-blank on a contributing study. Delivery has no PoC property.

A team is `Person.Team_Lead_Name`. For "which teams" questions, return the distinct team lead names of those China contributors. Do not list every person. The answer names the team by its team lead, for example `Jane Smith team`.

Delivered dataset and TLF counts are properties on deliveries that already have `Actual_Delivery_Date`: `Delivery.CSR_SDTM_Num_Total`, `Delivery.CSR_ADaM_Num_Total`, and `Delivery.CSR_TLF_Num_Total`. Return one row per delivery. Do not count `SDTM`, `ADaM`, or `TLF` nodes. For a title such as `B798h – Submit NDA (R1, 50 & 100mg, IA)`, match `Submission.Name` on the compound code and the submission type only (`B798H` and `NDA`). Do not require dose, round, or other parenthetical words, and do not match `Project_Name` for this question.

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
WHERE toUpper(trim(site.Name)) = 'CHINA' OR toUpper(trim(coalesce(site.Site_Category, ''))) = 'CHINA'
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
  AND (toUpper(trim(site.Name)) = 'CHINA' OR toUpper(trim(coalesce(site.Site_Category, ''))) = 'CHINA')
WITH p, collect(DISTINCT s.Name) AS Evidence
RETURN p.Name AS Person, p.NTID AS NTID, 'Study SDSL' AS Contribution, Evidence
UNION
MATCH (sub:Submission)
WHERE (sub.Project_Name IS NOT NULL AND toUpper(sub.Project_Name) CONTAINS 'LITFULO' AND toUpper(sub.Project_Name) CONTAINS 'VITILIGO')
   OR (sub.Name IS NOT NULL AND toUpper(sub.Name) CONTAINS 'LITFULO' AND toUpper(sub.Name) CONTAINS 'VITILIGO')
WITH DISTINCT sub
MATCH (s:Study)-[:HAS_DELIVERY]->(d:Delivery)-[:SUPPORT_SUBMISSION]->(sub)
WHERE s.SDSA_China_PoC IS NOT NULL AND trim(s.SDSA_China_PoC) <> ''
OPTIONAL MATCH (p:Person)
WHERE replace(toUpper(p.Name), ' ', '') = replace(toUpper(trim(s.SDSA_China_PoC)), ' ', '')
WITH coalesce(p.Name, trim(s.SDSA_China_PoC)) AS Person, p.NTID AS NTID, collect(DISTINCT d.Name) AS Evidence
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

## sub003: Which teams across China supported Litfulo vitiligo submission

**Business intent**  
A team is `Person.Team_Lead_Name`. Find China contributors to the submission, then return each distinct team lead. Do not list every person.

**Cypher**

```cypher
CALL {
  MATCH (sub:Submission)
  WHERE (sub.Project_Name IS NOT NULL AND toUpper(sub.Project_Name) CONTAINS 'LITFULO' AND toUpper(sub.Project_Name) CONTAINS 'VITILIGO')
     OR (sub.Name IS NOT NULL AND toUpper(sub.Name) CONTAINS 'LITFULO' AND toUpper(sub.Name) CONTAINS 'VITILIGO')
  WITH DISTINCT sub
  MATCH (p:Person)-[:WORKS_ON]->(:Delivery)-[:SUPPORT_SUBMISSION]->(sub)
  MATCH (p)-[:FROM_SITE]->(site:Site)
  WHERE toUpper(trim(site.Name)) = 'CHINA' OR toUpper(trim(coalesce(site.Site_Category, ''))) = 'CHINA'
  RETURN p
  UNION
  MATCH (sub:Submission)
  WHERE (sub.Project_Name IS NOT NULL AND toUpper(sub.Project_Name) CONTAINS 'LITFULO' AND toUpper(sub.Project_Name) CONTAINS 'VITILIGO')
     OR (sub.Name IS NOT NULL AND toUpper(sub.Name) CONTAINS 'LITFULO' AND toUpper(sub.Name) CONTAINS 'VITILIGO')
  WITH DISTINCT sub
  MATCH (s:Study)-[:HAS_DELIVERY]->(:Delivery)-[:SUPPORT_SUBMISSION]->(sub)
  MATCH (p:Person)-[:FROM_SITE]->(site:Site)
  WHERE replace(toUpper(p.Name), ' ', '') = replace(toUpper(trim(s.SDSL)), ' ', '')
    AND (toUpper(trim(site.Name)) = 'CHINA' OR toUpper(trim(coalesce(site.Site_Category, ''))) = 'CHINA')
  RETURN p
}
WITH p
WHERE p.Team_Lead_Name IS NOT NULL AND trim(toString(p.Team_Lead_Name)) <> ''
RETURN DISTINCT trim(toString(p.Team_Lead_Name)) AS Team_Lead
ORDER BY Team_Lead
LIMIT 50
```

## sub004: How many datasets and TLFs have been delivered for B798h – Submit NDA (R1, 50 & 100mg, IA) submission

**Business intent**  
Count SDTM datasets, ADaM datasets, and TLFs already delivered for that submission. A delivery counts when `Actual_Delivery_Date` is set. Read the counts from the delivery. Do not count dataset or TLF nodes.

**Parameters**

```json
{
  "keywords": ["B798H", "NDA"]
}
```

**Cypher**

```cypher
MATCH (sub:Submission)
WHERE toUpper(sub.Name) CONTAINS "B798H"
  AND toUpper(sub.Name) CONTAINS "NDA"
MATCH (s:Study)-[:HAS_DELIVERY]->(d:Delivery)-[:SUPPORT_SUBMISSION]->(sub)
WHERE d.Actual_Delivery_Date IS NOT NULL
RETURN sub.Name AS Submission,
       s.Name AS Study,
       d.Name AS Delivery,
       d.Reporting_Event AS Reporting_Event,
       d.Planned_Delivery_Date AS Planned_Delivery_Date,
       d.Actual_Delivery_Date AS Actual_Delivery_Date,
       d.CSR_ADaM_Num_Total AS ADaM_Datasets,
       d.CSR_SDTM_Num_Total AS SDTM_Datasets,
       d.CSR_TLF_Num_Total AS TLFs
ORDER BY d.Actual_Delivery_Date
LIMIT 200
```
