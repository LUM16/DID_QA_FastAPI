# Person Productivity Examples

> Use these as few-shot examples for DID Agent Text-to-Cypher. Replace parameter placeholders before execution.

## q000: How many tasks did a person complete in a month?

**Business intent**  
List each completed delivery in the month with CSR/SDA/STD/eSub task counts. Do not return only a grand total.

**Parameters**

```json
{
  "person": "Lu, Manman",
  "startDate": "2026-08-01",
  "endDate": "2026-09-01"
}
```

**Cypher**

```cypher
MATCH (p:Person)-[w:WORKS_ON]->(d:Delivery)
WHERE replace(toUpper(p.Name), " ", "") = replace(toUpper("{{person:Person name}}"), " ", "")
  AND d.DID_Status = "Completed"
  AND d.Actual_Delivery_Date >= date('{{startDate:Start date}}')
  AND d.Actual_Delivery_Date < date('{{endDate:End date}}')
RETURN d.Name AS Delivery,
       d.DID AS DID,
       d.DID_Status AS Status,
       d.Deliverable_Detail AS Deliverable_Detail,
       d.Reporting_Detail AS Reporting_Detail,
       d.Actual_Delivery_Date AS Actual_Delivery_Date,
       d.Planned_Delivery_Date AS Planned_Delivery_Date,
       coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) AS CSR,
       coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) AS SDA,
       coalesce(toFloat(w.STD_Task_Num_Total), 0.0) AS STD,
       coalesce(toFloat(w.esub_Data_Num_Total), 0.0) AS eSub
ORDER BY d.Actual_Delivery_Date, d.Name
LIMIT 50
```

## q001: Summarize the my deliveries during a certain time period

**Business intent**  
Summarize the deliveries of a specific person during a specified time period.

**Parameters**

```json
{
  "person": "Chen, Sizhen",
  "startDate": "2025-01-01",
  "endDate": "2025-12-31"
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: '{{person:Person name}}'})-[r:WORKS_ON]->(d:Delivery)
WHERE d.Actual_Delivery_Date >= date('{{startDate:Start date}}')
  AND d.Actual_Delivery_Date <= date('{{endDate:End date}}')
RETURN p.Name AS Person_Name,
       count(DISTINCT d.Name) AS Total_Deliveries,
       sum(coalesce(toFloat(r.CSR_TLF_Num_Total), 0.0)) AS Total_TLF_Volume,
       sum(coalesce(toFloat(r.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(r.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(r.STD_Task_Num_Total), 0.0) + coalesce(toFloat(r.esub_Data_Num_Total), 0.0)) AS Total_Tasks
ORDER BY Total_Deliveries DESC
```

## q002: Summarize which studies I participated in delivering during a certain period. For each study, how many tasks were delivered? What percentage of the study's total tasks were delivered?

**Business intent**  
Summarize the studies a specific person delivered during a specified period, along with the number of tasks delivered and the percentage of tasks relative to the total study tasks.

**Parameters**

```json
{
  "person": "Chen, Sizhen",
  "startDate": "2025-01-01",
  "endDate": "2025-12-31"
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: '{{person:Person name}}'})-[wo:WORKS_ON]->(d:Delivery)<-[:HAS_DELIVERY]-(s:Study)
WHERE d.Actual_Delivery_Date >= date('{{startDate:Start date}}')
  AND d.Actual_Delivery_Date <= date('{{endDate:End date}}')
WITH s,
     collect(DISTINCT d.Name) AS deliveries,
     sum(coalesce(toFloat(wo.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(wo.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(wo.STD_Task_Num_Total), 0.0) + coalesce(toFloat(wo.esub_Data_Num_Total), 0.0)) AS Person_Task_Sum
MATCH (s)-[:HAS_DELIVERY]->(allD:Delivery)
WITH s, deliveries, Person_Task_Sum,
     sum(coalesce(toFloat(allD.CSR_Task_Num), 0.0) + coalesce(toFloat(allD.SDA_Task_Num), 0.0) + coalesce(toFloat(allD.STD_Task_Num), 0.0) + coalesce(toFloat(allD.esub_Task_Data_Num), 0.0)) AS Total_Study_Task_Num
RETURN s.Name AS Study_Name,
       Person_Task_Sum,
       deliveries,
       Total_Study_Task_Num,
       CASE WHEN Total_Study_Task_Num = 0 THEN null ELSE round(100.0 * Person_Task_Sum / Total_Study_Task_Num, 2) END AS Percent_Study_Task
ORDER BY Study_Name
```

## q003: How many TLFs were completed in the past year?

**Business intent**  
Summarize the total number of TLFs completed in the past year.

**Parameters**

```json
{
"person": "Chen, Sizhen",
		"years":1
}
```

**Cypher**

```cypher
WITH date() - duration({years: {{years:Number of years}}}) AS Last_Year_Date
MATCH (p:Person {Name: '{{person:Person name}}'})-[wo:WORKS_ON]->(d:Delivery)
WHERE d.Actual_Delivery_Date >= Last_Year_Date AND d.Actual_Delivery_Date <= date()
RETURN SUM(coalesce(toFloat(wo.CSR_TLF_Num_Total), 0.0)) AS Total_TLFs
```

## q005: How many datasets or tables are associated with each DID, and how many hours were spent on each DID?

**Business intent**  
Shows the number of datasets and the total hours spent for each DID.

**Parameters**

```json
{
"person": "Chen, Sizhen"
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: {{person:Name of the person}}})-[to:TIME_ON]->(didn:DIDN_Month)-[:BELONGS_TO]->(d:Delivery)
RETURN d.Name AS DIDN, SUM(to.Hour) AS Hours
```

## q006: Which studies and domains have I participated in?

**Business intent**  
Lists all the studies and domains the person has participated in.

**Parameters**

```json
{
"person": "Chen, Sizhen"
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: '{{person:Person name}}'})-[:WORKS_ON]->(d:Delivery)<-[:HAS_DELIVERY]-(s:Study)
MATCH (d)-[:HAS_SDTM]->(sdtm:SDTM)
RETURN DISTINCT s.Name AS Study_Name, sdtm.Name AS Domain
ORDER BY Study_Name, Domain
```

## q007: Which domains have I worked on in the past period, how many times, and which ones were the most and least frequent?

**Business intent**  
Summarizes the number of times each domain was worked on, and identifies the most and least frequent.

**Parameters**

```json
{
"person": "Chen, Sizhen",
      "startDate": "2025-01-01",
      "endDate": "2025-03-31"
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: '{{person:Person name}}'})-[:WORKS_ON]->(d:Delivery)
WHERE d.Actual_Delivery_Date >= date('{{startDate:Start date}}')
  AND d.Actual_Delivery_Date <= date('{{endDate:End date}}')
MATCH (d)-[:HAS_SDTM]->(sdtm:SDTM)
WITH sdtm.Name AS Domain, COUNT(DISTINCT d) AS Domain_Count
WITH COLLECT({Domain: Domain, Domain_Count: Domain_Count}) AS rows,
     MAX(Domain_Count) AS Max_Domain_Count,
     MIN(Domain_Count) AS Min_Domain_Count
UNWIND rows AS row
RETURN row.Domain AS Domain,
       row.Domain_Count AS Domain_Count,
       CASE WHEN row.Domain_Count = Max_Domain_Count THEN 'Y' ELSE '' END AS Most_Frequent,
       CASE WHEN row.Domain_Count = Min_Domain_Count THEN 'Y' ELSE '' END AS Least_Frequent
ORDER BY Domain_Count DESC, Domain
```

## q008: Which studies have I participated in, sorted by TA and domain?

**Business intent**  
Lists all the studies the person has participated in, sorted by TA and domain.

**Parameters**

```json
{
"person": "Chen, Sizhen",
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: '{{person:Person name}}'})-[:WORKS_ON]->(d:Delivery)<-[:HAS_DELIVERY]-(s:Study)
OPTIONAL MATCH (s)-[:HAS_DETAIL]->(info:Study_Info)
MATCH (d)-[:HAS_SDTM]->(sdtm:SDTM)
RETURN DISTINCT COALESCE(info.TA, 'Unknown') AS TA, sdtm.Name AS Domain, s.Name AS Study_Name
ORDER BY TA, Domain, Study_Name
```

## q009: How many hours did I work on study XXXX in the past two weeks?

**Business intent**  
Calculates the total hours worked on a specific study in the past two weeks.

**Parameters**

```json
{
"person": "Chen, Sizhen",
	  "days" : 14,
      "study_name": "C4591007"
}
```

**Cypher**

```cypher
WITH date()-duration({days: {{days: number of days}}}) AS Date_Past_Two_Weeks
MATCH (p:Person {Name: {{person:Name of the person}}})-[to:TIME_ON]->(didn:DIDN_Month)-[:BELONGS_TO]->(d:Delivery)<-[:HAS_DELIVERY]-(s:Study {Name: {{stduy_name: Name of the study}}})
WHERE date(to.From_Date) >= Date_Past_Two_Weeks
RETURN s.Name AS Study_Name, SUM(to.Hour) AS Hours
```

## q010: Please summarize the delivery efficiency of the past two weeks

**Business intent**  
Summarizes the delivery efficiency (number of deliveries and average tasks) in the past two weeks.

**Parameters**

```json
{
"person": "Chen, Sizhen",
		"weeks" : 2
}
```

**Cypher**

```cypher
WITH date() - duration({weeks: {{weeks:Number of weeks}}}) AS Date_Past_Two_Weeks
MATCH (p:Person {Name: '{{person:Person name}}'})-[to:TIME_ON]->(didn:DIDN_Month)-[:BELONGS_TO]->(d:Delivery)<-[wo:WORKS_ON]-(p)
WHERE d.Actual_Delivery_Date >= Date_Past_Two_Weeks AND d.Actual_Delivery_Date <= date()
WITH SUM(to.Hour) AS Total_Hour,
     SUM(COALESCE(toFloat(wo.CSR_Task_Num_Total), 0.0) + COALESCE(toFloat(wo.SDA_Task_Num_Total), 0.0) + COALESCE(toFloat(wo.STD_Task_Num_Total), 0.0) + COALESCE(toFloat(wo.esub_Data_Num_Total), 0.0)) AS Total_Task
RETURN Total_Hour,
       Total_Task,
       CASE WHEN Total_Task = 0 THEN null ELSE round(Total_Hour / Total_Task, 2) END AS Hour_Per_Task
```

## q011: How much time does it take to complete one task based on the tasks I worked on in the past six months?

**Business intent**  
Estimates the time taken to complete one task based on recent tasks worked on.

**Parameters**

```json
{
"person": "Chen, Sizhen",
		"months": 6
}
```

**Cypher**

```cypher
WITH date() - duration({months: {{months:Number of months}}}) AS Date_Past_Six_Months
MATCH (p:Person {Name: '{{person:Person name}}'})-[to:TIME_ON]->(didn:DIDN_Month)-[:BELONGS_TO]->(d:Delivery)<-[wo:WORKS_ON]-(p)
WHERE d.Actual_Delivery_Date >= Date_Past_Six_Months AND d.Actual_Delivery_Date <= date()
WITH SUM(COALESCE(toFloat(to.Hour), 0.0)) AS Total_Hour,
     SUM(COALESCE(toFloat(wo.CSR_Task_Num_Total), 0.0) + COALESCE(toFloat(wo.SDA_Task_Num_Total), 0.0) + COALESCE(toFloat(wo.STD_Task_Num_Total), 0.0) + COALESCE(toFloat(wo.esub_Data_Num_Total), 0.0)) AS Total_Task
RETURN Total_Hour,
       Total_Task,
       CASE WHEN Total_Task = 0 THEN null ELSE round(Total_Hour / Total_Task, 2) END AS Hour_Per_Task
```

## q012: Please analyze the status of DIDs over the past 6 months and time spent on each

**Business intent**  
Analyzes the and time spent on each DID over the past 6 months.

**Parameters**

```json
{
"person": "Chen, Sizhen",
		"months": 6
}
```

**Cypher**

```cypher
WITH date()-duration({months: {{months: number of months}}}) AS Date_Past_Six_Month
MATCH (p:Person {Name:{{person:Name of the person}}})-[to:TIME_ON]->(didn:DIDN_Month)-[:BELONGS_TO]->(d:Delivery)
WHERE d.Actual_Delivery_Date >= Date_Past_Six_Month
WITH d.Name as DID, SUM(to.Hour) AS Total_Hour
RETURN DID, Total_Hour
```

## q013: Which DID did I spend the most time on in the past two weeks?

**Business intent**  
Finds which DID had the most time spent on in the past two weeks.

**Parameters**

```json
{
"person": "Chen, Sizhen",
		"weeks" : 2
}
```

**Cypher**

```cypher
WITH date()-duration({weeks: {{weeks: number of weeks}}}) AS Date_Past_Two_Weeks
MATCH (p:Person {Name:{{person:Name of the person}}})-[to:TIME_ON]->(didn:DIDN_Month)-[:BELONGS_TO]->(d:Delivery)
WHERE d.Actual_Delivery_Date >= Date_Past_Two_Weeks
WITH d.Name as DID, SUM(to.Hour) AS Total_Hour
RETURN DID, Total_Hour
ORDER BY Total_Hour DESC
```

## q015: Which domains have been worked on in the past period, and how many times?

**Business intent**  
Summarizes the domains worked on in the past period and the number of times each domain was worked on.

**Parameters**

```json
{
"person": "Chen, Sizhen",
        "startDate": "2025-01-01",
        "endDate": "2025-03-31"
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: {{person:Name of the person}}})-[:WORKS_ON]->(d:Delivery)
WHERE d.Actual_Delivery_Date >= date({{startDate}} AND d.Actual_Delivery_Date <= date({{endDate}}
MATCH (d)-[rel:HAS_SDTM]->(sdtm:SDTM)
WHERE p.Name in [rel.Generation, rel.QC]
WITH sdtm.Name AS Domain, COUNT(sdtm.Name) AS CNT_SDTM
RETURN Domain, CNT_SDTM
```

## q016: Please help me summarize goals for direct report(s) to fill in the PLI system

**Business intent**  
Summarizes the goals for direct report(s) in terms of total studies, TLFs, and tasks for filling in the PLI system.

**Parameters**

```json
{
  "manager": "Chen, Sizhen",
  "semester": 1,
  "year": 2025
}
```

**Cypher**

```cypher
WITH {{semester:Semester number}} AS Semester, {{year:Target year}} AS Target_Year
MATCH (employee:Person)-[:REPORTS_TO]->(manager:Person {Name: '{{manager:Manager name}}'})
MATCH (employee)-[wo:WORKS_ON]->(d:Delivery)
OPTIONAL MATCH (d)<-[:HAS_DELIVERY]-(s:Study)
WITH employee, wo, s, Semester, Target_Year, date(d.Actual_Delivery_Date) AS Delivery_Date
WHERE Delivery_Date.year = Target_Year
  AND ((Semester = 1 AND Delivery_Date.month >= 1 AND Delivery_Date.month <= 6)
    OR (Semester = 2 AND Delivery_Date.month >= 7 AND Delivery_Date.month <= 12))
WITH employee,
     COUNT(DISTINCT s) AS Total_Studies,
     SUM(COALESCE(toFloat(wo.CSR_TLF_Num_Total), 0.0)) AS Total_TLFs,
     SUM(COALESCE(toFloat(wo.CSR_Task_Num_Total), 0.0) + COALESCE(toFloat(wo.SDA_Task_Num_Total), 0.0) + COALESCE(toFloat(wo.STD_Task_Num_Total), 0.0) + COALESCE(toFloat(wo.esub_Data_Num_Total), 0.0)) AS Total_Tasks
RETURN employee.Name AS Direct_Report, Total_Studies, Total_TLFs, Total_Tasks
ORDER BY Direct_Report
```

## q117: recommend new studies or domains for a person based on their past experience.

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"personName": "Chen, Zhenchao (Riven)"
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: {personName}})-[:WORKS_ON]->(d:Delivery)<-[:HAS_DELIVERY]-(s:Study)
OPTIONAL MATCH (s)-[:HAS_DETAIL]->(info:Study_Info)
OPTIONAL MATCH (d)-[r1:HAS_SDTM]->(sdtm:SDTM)
WHERE r1.Generation CONTAINS p.Name OR r1.QC CONTAINS p.Name
OPTIONAL MATCH (d)-[r2:HAS_ADAM]->(adam:ADaM)
WHERE r2.Generation CONTAINS p.Name OR r2.QC CONTAINS p.Name
RETURN
p.Name AS Person_Name,
s.Name AS Study_Names,
COLLECT(DISTINCT info.Program_Code) AS Program_Codes,
COLLECT(DISTINCT info.Study_Type) AS Study_Types,
COLLECT(DISTINCT sdtm.Name) + COLLECT(DISTINCT adam.Name) AS Related_Domains
```

## q118: recommend new studies or domains for a person based on their past skills.

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"personName": "Chen, Zhenchao (Riven)"
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: {personName}})-[:WORKS_ON]->(d:Delivery)<-[:HAS_DELIVERY]-(s:Study)
OPTIONAL MATCH (s)-[:HAS_DETAIL]->(info:Study_Info)
OPTIONAL MATCH (d)-[r1:HAS_SDTM]->(sdtm:SDTM)
WHERE r1.Generation CONTAINS p.Name OR r1.QC CONTAINS p.Name
OPTIONAL MATCH (d)-[r2:HAS_ADAM]->(adam:ADaM)
WHERE r2.Generation CONTAINS p.Name OR r2.QC CONTAINS p.Name
RETURN
p.Name AS Person_Name,
s.Name AS Study_Names,
COLLECT(DISTINCT info.Program_Code) AS Program_Codes,
COLLECT(DISTINCT info.Study_Type) AS Study_Types,
COLLECT(DISTINCT sdtm.Name) + COLLECT(DISTINCT adam.Name) AS Related_Domains
```

## q125: Summarize someone's expertise in TA and Domain.

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"personName": "Chen, Zhenchao (Riven)"
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: {personName}})-[:WORKS_ON]->(d:Delivery)<-[:HAS_DELIVERY]-(s:Study)
OPTIONAL MATCH (s)-[:HAS_DETAIL]->(info:Study_Info)
OPTIONAL MATCH (d)-[r1:HAS_SDTM]->(sdtm:SDTM)
WHERE r1.Generation CONTAINS p.Name OR r1.QC CONTAINS p.Name
OPTIONAL MATCH (d)-[r2:HAS_ADAM]->(adam:ADaM)
WHERE r2.Generation CONTAINS p.Name OR r2.QC CONTAINS p.Name
RETURN
p.Name AS Person_Name,
s.Name AS Study_Names,
COLLECT(DISTINCT info.Program_Code) AS Program_Codes,
COLLECT(DISTINCT info.Study_Type) AS Study_Types,
COLLECT(DISTINCT sdtm.Name) + COLLECT(DISTINCT adam.Name) AS Related_Domains
```

## q134: list domains a person has involved

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"personName": "Chen, Zhenchao (Riven)"
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: {personName}})-[:WORKS_ON]->(d:Delivery)<-[:HAS_DELIVERY]-(s:Study)
OPTIONAL MATCH (s)-[:HAS_DETAIL]->(info:Study_Info)
OPTIONAL MATCH (d)-[r1:HAS_SDTM]->(sdtm:SDTM)
WHERE r1.Generation CONTAINS p.Name OR r1.QC CONTAINS p.Name
OPTIONAL MATCH (d)-[r2:HAS_ADAM]->(adam:ADaM)
WHERE r2.Generation CONTAINS p.Name OR r2.QC CONTAINS p.Name
RETURN
p.Name AS Person_Name,
s.Name AS Study_Names,
COLLECT(DISTINCT info.Program_Code) AS Program_Codes,
COLLECT(DISTINCT info.Study_Type) AS Study_Types,
COLLECT(DISTINCT sdtm.Name) + COLLECT(DISTINCT adam.Name) AS Related_Domains
```
