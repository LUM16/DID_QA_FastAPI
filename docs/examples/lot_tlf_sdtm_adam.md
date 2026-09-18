# LoT, TLF, SDTM, ADaM Examples

> Use these as few-shot examples for DID Agent Text-to-Cypher. Replace parameter placeholders before execution.

## q075: Summarize the LoT (listings, outputs, tables) for a specific project and report the number of unique tables for each domain after removing duplicates.

**Business intent**  
Counts unique tables for each domain in a specified project

**Parameters**

```json
{
"delivery_id": "C3671053_1"
}
```

**Cypher**

```cypher
MATCH (delivery:Delivery{Name: "{{delivery_id:Delivery ID}}"})-[:HAS_TLF]->(tlf:TLF)
RETURN tlf.Source AS Domain, COUNT(DISTINCT tlf.Name) AS Unique_TLF_Count
ORDER BY Domain
```

## q076: Please list the difference of {{task_type:Task type}} between two specific DID {{delivery_id1:Delivery ID 1}} and {{delivery_id2:Delivery ID 2}}

**Business intent**  
Auto-parameterized query to list SDTM/ADaM/TLF differences between two DIDs

**Parameters**

```json
{
"task_type": "SDTM,ADaM,TLF",
      "delivery_id1": "C3671053_1",
      "delivery_id2": "C3671053_2"
}
```

**Cypher**

```cypher
WITH '{{delivery_id1:Delivery ID 1}}' AS targetDID1, '{{delivery_id2:Delivery ID 2}}' AS targetDID2
MATCH (did1:Delivery {DID: targetDID1})
OPTIONAL MATCH (did1)-[:HAS_SDTM]->(sdtm1:SDTM)
OPTIONAL MATCH (did1)-[:HAS_ADAM]->(adam1:ADaM)
OPTIONAL MATCH (did1)-[:HAS_TLF]->(tlf1:TLF)
WITH targetDID1, targetDID2,
     collect(DISTINCT sdtm1.Name) AS sdtmNames1,
     collect(DISTINCT adam1.Name) AS adamNames1,
     collect(DISTINCT tlf1.Name) AS tlfNames1
MATCH (did2:Delivery {DID: targetDID2})
OPTIONAL MATCH (did2)-[:HAS_SDTM]->(sdtm2:SDTM)
OPTIONAL MATCH (did2)-[:HAS_ADAM]->(adam2:ADaM)
OPTIONAL MATCH (did2)-[:HAS_TLF]->(tlf2:TLF)
WITH targetDID1, targetDID2, sdtmNames1, adamNames1, tlfNames1,
     collect(DISTINCT sdtm2.Name) AS sdtmNames2,
     collect(DISTINCT adam2.Name) AS adamNames2,
     collect(DISTINCT tlf2.Name) AS tlfNames2
RETURN 'SDTM' AS Deliverable_Type,
       [n IN sdtmNames1 WHERE NOT n IN sdtmNames2] AS SDTM_Unique_To_First_DID,
       [n IN sdtmNames2 WHERE NOT n IN sdtmNames1] AS SDTM_Unique_To_Second_DID,
       'ADaM' AS Deliverable_Type_2,
       [n IN adamNames1 WHERE NOT n IN adamNames2] AS ADaM_Unique_To_First_DID,
       [n IN adamNames2 WHERE NOT n IN adamNames1] AS ADaM_Unique_To_Second_DID,
       'TLF' AS Deliverable_Type_3,
       [n IN tlfNames1 WHERE NOT n IN tlfNames2] AS TLF_Unique_To_First_DID,
       [n IN tlfNames2 WHERE NOT n IN tlfNames1] AS TLF_Unique_To_Second_DID
```

## q094: Please help me retrieve tables similar to a specific table title.

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"table_keyword1": "Demographic",
      "table_keyword2": "Characteristics"
}
```

**Cypher**

```cypher
MATCH (d:Delivery)-[:HAS_TLF]->(tlf:TLF)
WHERE tlf.Name CONTAINS {{table_keyword1:Table keyword 1}} OR tlf.Name CONTAINS {{table_keyword2:Table keyword 2}}
MATCH (s:Study)-[:HAS_DELIVERY]->(d)
RETURN s.Name as Study, d.DID, tlf.Name as Table_Title, tlf.Category, tlf.Type
ORDER BY s.Name, d.DID
```

## q095: Which DID contains the most recently updated table?

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"table_name": "Demographic Characteristics",
      "limit": 10
}
```

**Cypher**

```cypher
MATCH (d:Delivery)-[:HAS_TLF]->(tlf:TLF)
WHERE tlf.Name CONTAINS {{table_name:Table name}}
  AND d.Actual_Delivery_Date IS NOT NULL
RETURN d.DID, d.Actual_Delivery_Date, tlf.Name as Table_Title, d.Study
ORDER BY d.Actual_Delivery_Date DESC
LIMIT {{limit:Number of results}}
```

## q097: Which DIDs has a particular table appeared in?

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"table_name": "Demographic Characteristics"
}
```

**Cypher**

```cypher
MATCH (d:Delivery)-[:HAS_TLF]->(tlf:TLF)
WHERE tlf.Name CONTAINS {{table_name:Table name}}
RETURN d.DID, tlf.Name, d.DID_Status, d.Planned_Delivery_Date, d.Study
ORDER BY d.Planned_Delivery_Date DESC
```

## q099: Which domain/TLF can this study refer to?

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"ta": "Oncology",
      "limit": 10
}
```

**Cypher**

```cypher
MATCH (si:Study_Info)
WHERE si.TA = {{ta:Therapeutic area}}
MATCH (s:Study)-[:HAS_DETAIL]->(si)
MATCH (s)-[:HAS_DELIVERY]->(d:Delivery)
WHERE d.Actual_Delivery_Date IS NOT NULL
WITH s, si, d
ORDER BY d.Actual_Delivery_Date DESC
WITH s.Name as Study, si.TA as TA, COLLECT(DISTINCT d.DID)[0..5] as Recent_DIDs, MAX(d.Actual_Delivery_Date) as Latest_Delivery_Date
RETURN Study, TA, Recent_DIDs, Latest_Delivery_Date
ORDER BY Latest_Delivery_Date DESC
LIMIT {{limit:Number of studies}}
```

## q100: When facing an unfamiliar domain, I want to quickly search which DID has a similar TLF.

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"table_keyword1": "Demographic",
      "table_keyword2": "Characteristics"
}
```

**Cypher**

```cypher
MATCH (d:Delivery)-[:HAS_TLF]->(tlf:TLF)
WHERE tlf.Name CONTAINS {{table_keyword1:Table keyword 1}} OR tlf.Name CONTAINS {{table_keyword2:Table keyword 2}}
MATCH (s:Study)-[:HAS_DELIVERY]->(d)
RETURN s.Name as Study, d.DID, tlf.Name as Table_Title, tlf.Category, tlf.Type
ORDER BY s.Name, d.DID
```

## q101: Answer the differences between TLFs or datasets in two DIDs.

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"did1": "C1071003_1",
      "did2": "C1071003_2"
}
```

**Cypher**

```cypher
MATCH (d1:Delivery {DID: '{{did1:First DID}}'})
MATCH (d2:Delivery {DID: '{{did2:Second DID}}'})
OPTIONAL MATCH (d1)-[:HAS_TLF]->(tlf1:TLF)
OPTIONAL MATCH (d2)-[:HAS_TLF]->(tlf2:TLF)
WITH d1, d2,
     COLLECT(DISTINCT tlf1.Name) AS DID1_TLFs,
     COLLECT(DISTINCT tlf2.Name) AS DID2_TLFs
WITH d1, d2, DID1_TLFs, DID2_TLFs,
     [tlf IN DID1_TLFs WHERE NOT tlf IN DID2_TLFs] AS TLF_Only_in_DID1,
     [tlf IN DID2_TLFs WHERE NOT tlf IN DID1_TLFs] AS TLF_Only_in_DID2
OPTIONAL MATCH (d1)-[:HAS_ADAM]->(adam1:ADaM)
OPTIONAL MATCH (d2)-[:HAS_ADAM]->(adam2:ADaM)
WITH d1, d2, DID1_TLFs, DID2_TLFs, TLF_Only_in_DID1, TLF_Only_in_DID2,
     COLLECT(DISTINCT adam1.Name) AS DID1_ADaMs,
     COLLECT(DISTINCT adam2.Name) AS DID2_ADaMs
WITH d1, d2, DID1_TLFs, DID2_TLFs, TLF_Only_in_DID1, TLF_Only_in_DID2,
     DID1_ADaMs, DID2_ADaMs,
     [adam IN DID1_ADaMs WHERE NOT adam IN DID2_ADaMs] AS ADaM_Only_in_DID1,
     [adam IN DID2_ADaMs WHERE NOT adam IN DID1_ADaMs] AS ADaM_Only_in_DID2
OPTIONAL MATCH (d1)-[:HAS_SDTM]->(sdtm1:SDTM)
OPTIONAL MATCH (d2)-[:HAS_SDTM]->(sdtm2:SDTM)
WITH d1.DID AS DID1, d2.DID AS DID2,
     DID1_TLFs, DID2_TLFs, TLF_Only_in_DID1, TLF_Only_in_DID2,
     DID1_ADaMs, DID2_ADaMs, ADaM_Only_in_DID1, ADaM_Only_in_DID2,
     COLLECT(DISTINCT sdtm1.Name) AS DID1_SDTMs,
     COLLECT(DISTINCT sdtm2.Name) AS DID2_SDTMs
RETURN DID1, DID2,
       SIZE(DID1_TLFs) AS DID1_TLF_Count, SIZE(DID2_TLFs) AS DID2_TLF_Count,
       TLF_Only_in_DID1, TLF_Only_in_DID2,
       SIZE(DID1_ADaMs) AS DID1_ADaM_Count, SIZE(DID2_ADaMs) AS DID2_ADaM_Count,
       ADaM_Only_in_DID1, ADaM_Only_in_DID2,
       SIZE(DID1_SDTMs) AS DID1_SDTM_Count, SIZE(DID2_SDTMs) AS DID2_SDTM_Count,
       [sdtm IN DID1_SDTMs WHERE NOT sdtm IN DID2_SDTMs] AS SDTM_Only_in_DID1,
       [sdtm IN DID2_SDTMs WHERE NOT sdtm IN DID1_SDTMs] AS SDTM_Only_in_DID2
```

## q103: Which deliveries have a similar or duplicate table title?

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
{}
}
```

**Cypher**

```cypher
MATCH (d1:Delivery)-[:HAS_TLF]->(tlf1:TLF)
MATCH (d2:Delivery)-[:HAS_TLF]->(tlf2:TLF)
WHERE d1.DID <> d2.DID AND tlf1.Name = tlf2.Name
RETURN tlf1.Name as Duplicate_TLF, 
       COLLECT(DISTINCT d1.DID) + COLLECT(DISTINCT d2.DID) as DIDs_With_Duplicate
ORDER BY Duplicate_TLF
```

## q109: retrieve the generator and QCer for a specific domain/table in a given study.

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"studyName": "C2321001",
    "source": "ADLB"
}
```

**Cypher**

```cypher
MATCH (s:Study {Name: {studyName}})-[:HAS_DELIVERY]->(d:Delivery)-[r:HAS_TLF]->(t:TLF {Source: {source}})
RETURN t.Name as TLFNAME, r.Generation as Generator, r.QC as QCer
```

## q110: Retrieve the TLF number for a specific delivery.

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"deliveryName": "C1071004_20"
}
```

**Cypher**

```cypher
WITH '{{delivery_id:Delivery ID}}' AS specificDID
MATCH (delivery:Delivery {Name: specificDID})-[hasTLF:HAS_TLF]->(tlf:TLF)
RETURN delivery.Name AS Delivery_ID,
       tlf.Name AS TLF_Name,
       hasTLF.TLF_Number AS TLF_Number
ORDER BY TLF_Name
```

## q111: Find delivery identifiers for TLFs containing a specific name.

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"tlfName": "Kaplan-Meier Plot of Overall survival"
}
```

**Cypher**

```cypher
MATCH (t:TLF)
WHERE t.Name CONTAINS {tlfName}
MATCH (d:Delivery)-[:HAS_TLF]->(t)
RETURN d.DID AS Delivery_Identifier
```

## q112: list  people are or have been involved in the delivery of a specific study

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"studyName": "C2321001"
}
```

**Cypher**

```cypher
MATCH (study:Study {Name: '{{study:Study name}}'})-[:HAS_DELIVERY]->(delivery:Delivery)
MATCH (person:Person)-[:WORKS_ON]->(delivery)
RETURN DISTINCT study.Name AS Study_Name, person.Name AS Person_Name
ORDER BY Person_Name
```

## q128: list team members under Wang Fang, summarizing task numbers by study generation numbers and QC numbers for period 2025-03-01 to 2025-09-01

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"teamLeadName": "Wang, Fang",
    "startDate": "2025-03-01",
    "endDate": "2025-09-01"
}
```

**Cypher**

```cypher
MATCH (teamMember:Person {Team_Lead_Name: '{{team_lead:Team lead name}}'})-[r:WORKS_ON]->(d:Delivery)<-[:HAS_DELIVERY]-(study:Study)
WHERE d.Actual_Delivery_Date >= date('{{startDate:Start date}}') AND d.Actual_Delivery_Date <= date('{{endDate:End date}}')
WITH teamMember, study,
     SUM(coalesce(toFloat(r.CSR_Task_Num_Generation), 0.0) + coalesce(toFloat(r.SDA_Task_Num_Generation), 0.0) + coalesce(toFloat(r.STD_Task_Num_Generation), 0.0) + coalesce(toFloat(r.esub_Data_Num_Generation), 0.0)) AS Total_Task_Num_GEN,
     SUM(coalesce(toFloat(r.CSR_Task_Num_QC), 0.0) + coalesce(toFloat(r.SDA_Task_Num_QC), 0.0) + coalesce(toFloat(r.STD_Task_Num_QC), 0.0) + coalesce(toFloat(r.esub_Data_Num_QC), 0.0)) AS Total_Task_Num_QC
RETURN teamMember.Name AS Team_Member_Name, study.Name AS Study_Name, Total_Task_Num_GEN, Total_Task_Num_QC
ORDER BY Team_Member_Name, Study_Name
```

## q129: Suggest a colleague in my team for urgent task, contains TLF about Kaplan-Meier Plot

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"teamLeadName": "Zhang, Wei (Tony)",
    "tlfName": "Kaplan-Meier Plot"
}
```

**Cypher**

```cypher
MATCH (p:Person {Team_Lead_Name: {teamLeadName}})-[:WORKS_ON]->(d:Delivery)-[r:HAS_TLF]->(t:TLF)
WHERE t.Name CONTAINS {tlfName} AND (r.Generation = p.Name OR r.QC = p.Name)
RETURN p.Name AS Person_Name, COUNT(t) AS Frequency
 order by  Frequency DESC
```

## q130: Suggest a colleague I could ask for TLF about Kaplan-Meier Plot

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"tlfName": "Kaplan-Meier Plot"
}
```

**Cypher**

```cypher
MATCH (p:Person)-[:WORKS_ON]->(d:Delivery)-[r:HAS_TLF]->(t:TLF)
WHERE t.Name CONTAINS {tlfName} AND (r.Generation = p.Name OR r.QC = p.Name)
RETURN p.Name AS Person_Name, COUNT(t) AS Frequency
 order by  Frequency DESC
```

## q131: Suggest a colleague I could ask for Modelling

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"tlfName": "Modelling"
}
```

**Cypher**

```cypher
MATCH (p:Person)-[:WORKS_ON]->(d:Delivery)-[r:HAS_TLF]->(t:TLF)
WHERE t.Name CONTAINS {tlfName} AND (r.Generation = p.Name OR r.QC = p.Name)
RETURN p.Name AS Person_Name, COUNT(t) AS Frequency
  order by  Frequency DESC
```

## q133: Suggest a colleague I could assign for pending TLF in dLOT about Kaplan-Meier Plot

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"tlfName": "Kaplan-Meier Plot"
}
```

**Cypher**

```cypher
MATCH (p:Person)-[:WORKS_ON]->(d:Delivery)-[r:HAS_TLF]->(t:TLF)
WHERE t.Name CONTAINS {tlfName} AND (r.Generation = p.Name OR r.QC = p.Name)
RETURN p.Name AS Person_Name, COUNT(t) AS Frequency
 order by  Frequency DESC
```

## q140_1: Compare TLF generation and QC across deliveries for Study C2321001

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"study": "C2321001"
}
```

**Cypher**

```cypher
MATCH (s:Study {Name: '{{study:Study Name}}'})-[:HAS_DELIVERY]->(d:Delivery)-[r:HAS_TLF]->(tlf:TLF)
WITH tlf.Name AS TLF_Name, d.Name AS Delivery_Name, r.Generation AS Generation, r.QC AS QC
WITH TLF_Name, Delivery_Name, Generation, QC,
     toInteger(last(split(Delivery_Name, '_'))) AS numericSuffix
ORDER BY TLF_Name, numericSuffix ASC
WITH TLF_Name, collect({delivery: Delivery_Name, generation: Generation, qc: QC}) AS deliveries
UNWIND range(1, size(deliveries) - 1) AS i
WITH TLF_Name, deliveries[i - 1] AS prevDelivery, deliveries[i] AS currentDelivery
WHERE prevDelivery.generation <> currentDelivery.generation
   OR prevDelivery.qc <> currentDelivery.qc
RETURN TLF_Name AS TLF,
       currentDelivery.delivery AS Delivery_Name,
       prevDelivery.generation AS Previous_Generation,
       currentDelivery.generation AS Current_Generation,
       prevDelivery.qc AS Previous_QC,
       currentDelivery.qc AS Current_QC
ORDER BY TLF_Name, currentDelivery.delivery
```

## q140_2: Compare SDTM generation and QC across deliveries for Study C2321001

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"study": "C2321001"
}
```

**Cypher**

```cypher
MATCH (s:Study {Name: '{{study:Study Name}}'})-[:HAS_DELIVERY]->(d:Delivery)-[r:HAS_SDTM]->(sdtm:SDTM)
WITH sdtm.Name AS SDTM_Name, d.Name AS Delivery_Name, r.Generation AS Generation, r.QC AS QC
WITH SDTM_Name, Delivery_Name, Generation, QC,
     toInteger(last(split(Delivery_Name, '_'))) AS numericSuffix
ORDER BY SDTM_Name, numericSuffix ASC
WITH SDTM_Name, collect({delivery: Delivery_Name, generation: Generation, qc: QC}) AS deliveries
UNWIND range(1, size(deliveries) - 1) AS i
WITH SDTM_Name, deliveries[i - 1] AS prevDelivery, deliveries[i] AS currentDelivery
WHERE prevDelivery.generation <> currentDelivery.generation
   OR prevDelivery.qc <> currentDelivery.qc
RETURN SDTM_Name AS SDTM,
       currentDelivery.delivery AS Delivery_Name,
       prevDelivery.generation AS Previous_Generation,
       currentDelivery.generation AS Current_Generation,
       prevDelivery.qc AS Previous_QC,
       currentDelivery.qc AS Current_QC
ORDER BY SDTM_Name, currentDelivery.delivery
```

## q140_3: Compare ADaM generation and QC across deliveries for Study C2321001

**Business intent**  
Compare ADaM generation and QC across deliveries for Study C2321001

**Parameters**

```json
{
"study": "C2321001"
}
```

**Cypher**

```cypher
MATCH (s:Study {Name: '{{study:Study Name}}'})-[:HAS_DELIVERY]->(d:Delivery)-[r:HAS_ADAM]->(adam:ADaM)
WITH adam.Name AS ADaM_Name, d.Name AS Delivery_Name, r.Generation AS Generation, r.QC AS QC
WITH ADaM_Name, Delivery_Name, Generation, QC,
     toInteger(last(split(Delivery_Name, '_'))) AS numericSuffix
ORDER BY ADaM_Name, numericSuffix ASC
WITH ADaM_Name, collect({delivery: Delivery_Name, generation: Generation, qc: QC}) AS deliveries
UNWIND range(1, size(deliveries) - 1) AS i
WITH ADaM_Name, deliveries[i - 1] AS prevDelivery, deliveries[i] AS currentDelivery
WHERE prevDelivery.generation <> currentDelivery.generation
   OR prevDelivery.qc <> currentDelivery.qc
RETURN ADaM_Name AS ADaM,
       currentDelivery.delivery AS Delivery_Name,
       prevDelivery.generation AS Previous_Generation,
       currentDelivery.generation AS Current_Generation,
       prevDelivery.qc AS Previous_QC,
       currentDelivery.qc AS Current_QC
ORDER BY ADaM_Name, currentDelivery.delivery
```
