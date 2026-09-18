# Uncategorized Safe Examples

> Review these and move them into a topic file if useful.

## q042: Compare the efficiency of my tasks between the first and second halves of the year.

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"person_name": "PERSON_NAME",
      "year": 2024
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: '{{person:Person name}}'})-[r:WORKS_ON]->(d:Delivery)
WHERE d.Year = {{year:Year}}
WITH p, d, r,
     CASE WHEN d.Month <= 6 THEN 'First_Half' ELSE 'Second_Half' END AS Half_Year,
     coalesce(toFloat(r.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(r.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(r.STD_Task_Num_Total), 0.0) + coalesce(toFloat(r.esub_Data_Num_Total), 0.0) AS Task_Num
WITH p, Half_Year,
     count(d) AS Delivery_Count,
     sum(Task_Num) AS Total_Tasks
MATCH (p)-[t:TIME_ON]->(dm)
WHERE (dm:DIDN_Month OR dm:DID0_Month OR dm:Study_Month)
  AND dm.Year = {{year:Year}}
  AND ((dm.Month <= 6 AND Half_Year = 'First_Half') OR (dm.Month > 6 AND Half_Year = 'Second_Half'))
WITH Half_Year, Delivery_Count, Total_Tasks, sum(t.Hour) AS Total_Hours
RETURN Half_Year,
       Delivery_Count,
       Total_Tasks,
       Total_Hours,
       CASE WHEN Total_Tasks = 0 THEN null ELSE round(Total_Hours * 1.0 / Total_Tasks, 2) END AS Hours_Per_Task
ORDER BY Half_Year
```

## q093: Please tell me where the DID runs, and provide the specific CDARS or SIGMA path.

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"did": "C1071003_1"
}
```

**Cypher**

```cypher
MATCH (d:Delivery {DID: {{did:DID name}}})
RETURN d.DID, d.Reporting_Path, d.Reporting_System, d.Study
```

## q114: calculate the total hours spent by the SDSL for study C2321001.

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"studyName": "C2321001",
    "didTypes": ["DID0", "DIDN"]
}
```

**Cypher**

```cypher
MATCH (s:Study {Name: {studyName}})-[:HAS_DELIVERY]->(d:Delivery)
MATCH (sdsl:Person)-[:WORKS_AS]->(s)
WHERE sdsl.Name = s.SDSL
MATCH (sdsl)-[t:TIME_ON]->(sm:Study_Month)-[:BELONGS_TO]->(s)
WHERE t.DID_Type IN {didTypes}
RETURN SUM(t.Hour) AS Total_Hours_Spent
```

## q126: summarize which team members under team lead 'Wang, Fang' collaborated with others on deliveries from March 1, 2025, to September 1, 2025 and which domains are they involved?

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
MATCH (teamMember:Person {Team_Lead_Name: '{{team_lead:Team lead name}}'})-[:WORKS_ON]->(d:Delivery)
WHERE d.Actual_Delivery_Date >= date('{{startDate:Start date}}') AND d.Actual_Delivery_Date <= date('{{endDate:End date}}')
WITH teamMember, d
MATCH (otherPerson:Person)-[:WORKS_ON]->(d)
WHERE otherPerson <> teamMember
WITH teamMember, otherPerson, d
OPTIONAL MATCH (d)-[r1:HAS_SDTM]->(sdtm:SDTM)
WHERE r1.Generation = teamMember.Name OR r1.QC = teamMember.Name
OPTIONAL MATCH (d)-[r2:HAS_ADAM]->(adam:ADaM)
WHERE r2.Generation = teamMember.Name OR r2.QC = teamMember.Name
OPTIONAL MATCH (d)-[r3:HAS_TLF]->(tlf:TLF)
WHERE r3.Generation = teamMember.Name OR r3.QC = teamMember.Name
RETURN teamMember.Name AS Team_Member,
       COLLECT(DISTINCT otherPerson.Name) AS Collaborators,
       COLLECT(DISTINCT d.Name) AS Deliveries,
       COLLECT(DISTINCT sdtm.Name) AS SDTM_Domains,
       COLLECT(DISTINCT adam.Name) AS ADaM_Domains,
       COLLECT(DISTINCT tlf.Name) AS TLF_Domains
ORDER BY Team_Member
```

## q139: find which DIDs are available for filling in the daily survey

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"personName": "Chen, Zhenchao (Riven)",
    "didStatuses": ["Planned", "Ongoing", "Completed"]
     "TodayDate": "2025-09-01"
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: {personName}})-[:WORKS_ON]->(d:Delivery)
WHERE d.DID_Status IN {didStatuses} and d.Actual_Delivery_Date >=date({TodayDate})
RETURN d.Name AS Eligible_DIDs
```
