# Team, DU, Manager and TA Lead Examples

> Use these as few-shot examples for DID Agent Text-to-Cypher. Replace parameter placeholders before execution.

## Org chart — person / reporting_level / reports_to / status (preferred)

**Business intent**  
Preferred template for org-chart / team-structure questions. Returns one row per person so the UI can render both a table and a grouped organization chart.
- `reporting_level` is 0 for the root person, 1 for direct reports, 2 for their reports, and so on.
- `reports_to` is the direct manager's Name (a list; empty for the level-0 root).

**Parameters**

```json
{
  "manager": "Iyer, Priya Venkatesan"
}
```

**Cypher**

```cypher
MATCH path = (member:Person)-[:REPORTS_TO*0..6]->(root:Person)
WHERE replace(toUpper(root.Name), " ", "") = replace(toUpper("{{manager:Person name}}"), " ", "")
WITH root, member, min(length(path)) AS reporting_level
OPTIONAL MATCH (member)-[:REPORTS_TO]->(mgr:Person)
WITH member, reporting_level,
     CASE WHEN reporting_level = 0 THEN [] ELSE collect(DISTINCT mgr.Name) END AS reports_to
RETURN member.Name AS person,
       reporting_level,
       reports_to,
       coalesce(member.Status, "") AS status
ORDER BY reporting_level, person
LIMIT 500
```

## q045: Which studies have my DU members (under manager {{manager:Person name}}) participated in, and what domain are involved

**Business intent**  
Auto-parameterized query to get studies and domains participated by DU members under a specific manager

**Parameters**

```json
{
"manager": "tao, yuxi"
}
```

**Cypher**

```cypher
MATCH (manager:Person) WHERE replace(toUpper(manager.Name), " ", "") = replace(toUpper("{{manager:Person name}}", " ", "")) OPTIONAL MATCH (manager)<-[:REPORTS_TO]-(person:Person) OPTIONAL MATCH (person)-[:WORKS_ON]->(delivery:Delivery) OPTIONAL MATCH (delivery)-[hasSdtm:HAS_SDTM]->(sdtm:SDTM) WHERE (hasSdtm.QC CONTAINS person.Name OR hasSdtm.Generation CONTAINS person.Name) RETURN person.Name AS DU_Member_Name, collect(DISTINCT delivery.Study) AS Studies, collect(DISTINCT delivery.DID) AS DID_List, collect(DISTINCT sdtm.Name) AS SDTM_Names ORDER BY DU_Member_Name;
```

## q046: Please summarize how many tasks were delivered by my DU (under manager {{manager:Person name}}) in S1 and S2 of {{year:Year}}

**Business intent**  
Auto-parameterized query to summarize DU tasks in S1/S2 of a specific year

**Parameters**

```json
{
"manager": "tao, yuxi",
      "year": 2025
}
```

**Cypher**

```cypher
WITH {{year:Year}} AS targetYear,
     targetYear * 12 + 1 AS startS1,
     targetYear * 12 + 6 AS endS1,
     targetYear * 12 + 7 AS startS2,
     targetYear * 12 + 12 AS endS2
MATCH (manager:Person)
WHERE replace(toUpper(manager.Name), ' ', '') = replace(toUpper('{{manager:Person name}}'), ' ', '')
OPTIONAL MATCH (manager)<-[:REPORTS_TO]-(person:Person)
WITH manager, collect(person) + [manager] AS duMembers, startS1, endS1, startS2, endS2
UNWIND duMembers AS person
OPTIONAL MATCH (person)-[w:WORKS_ON]->(delivery:Delivery)
WHERE delivery.DID_Status = 'Completed'
  AND delivery.Year * 12 + delivery.Month >= startS1
  AND delivery.Year * 12 + delivery.Month <= endS2
WITH person, delivery, w, startS1, endS1, startS2, endS2,
     coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0) AS Member_Task_Num,
     coalesce(toFloat(delivery.CSR_Task_Num), 0.0) + coalesce(toFloat(delivery.SDA_Task_Num), 0.0) + coalesce(toFloat(delivery.STD_Task_Num), 0.0) + coalesce(toFloat(delivery.esub_Task_Data_Num), 0.0) AS Delivery_Task_Num
WITH person.Name AS DU_Member_Name,
     sum(CASE WHEN delivery.Year * 12 + delivery.Month >= startS1 AND delivery.Year * 12 + delivery.Month <= endS1 THEN Member_Task_Num ELSE 0 END) AS Total_Tasks_S1,
     sum(CASE WHEN delivery.Year * 12 + delivery.Month >= startS2 AND delivery.Year * 12 + delivery.Month <= endS2 THEN Member_Task_Num ELSE 0 END) AS Total_Tasks_S2,
     sum(CASE WHEN delivery.Year * 12 + delivery.Month >= startS1 AND delivery.Year * 12 + delivery.Month <= endS1 THEN Delivery_Task_Num ELSE 0 END) AS Total_Tasks_S1_All,
     sum(CASE WHEN delivery.Year * 12 + delivery.Month >= startS2 AND delivery.Year * 12 + delivery.Month <= endS2 THEN Delivery_Task_Num ELSE 0 END) AS Total_Tasks_S2_All
RETURN collect(DU_Member_Name) AS DU_Members,
       collect(Total_Tasks_S1) AS DU_Tasks_S1,
       collect(Total_Tasks_S2) AS DU_Tasks_S2,
       sum(Total_Tasks_S1_All) AS Total_Tasks_S1_All,
       sum(Total_Tasks_S2_All) AS Total_Tasks_S2_All
```

## q047: Please summarize the total number of tasks completed by my DU (under manager {{manager:Person name}}) from {{start_month:Month}} {{start_year:Year}} to the present, list all DIDs, and provide a breakdown by person

**Business intent**  
Auto-parameterized query to summarize DU tasks from a specific month/year to present, with DID list

**Parameters**

```json
{
"manager": "tao, yuxi",
      "start_year": 2025,
      "start_month": 1
}
```

**Cypher**

```cypher
WITH date({year: {{start_year:Year}}, month: {{start_month:Month}}, day: 1}) AS startOfPeriod, date() AS today
MATCH (manager:Person)
WHERE replace(toUpper(manager.Name), ' ', '') = replace(toUpper('{{manager:Person name}}'), ' ', '')
OPTIONAL MATCH (manager)<-[:REPORTS_TO]-(person:Person)
WITH manager, collect(person) AS duMembers, startOfPeriod, today
UNWIND duMembers + [manager] AS person
OPTIONAL MATCH (person)-[w:WORKS_ON]->(delivery:Delivery)
WHERE delivery.DID_Status = 'Completed'
  AND delivery.Actual_Delivery_Date >= startOfPeriod
  AND delivery.Actual_Delivery_Date <= today
WITH person.Name AS DU_Member_Name, delivery,
     coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0) AS Member_Task_Num,
     coalesce(toFloat(delivery.CSR_Task_Num), 0.0) + coalesce(toFloat(delivery.SDA_Task_Num), 0.0) + coalesce(toFloat(delivery.STD_Task_Num), 0.0) + coalesce(toFloat(delivery.esub_Task_Data_Num), 0.0) AS Delivery_Task_Num
WITH DU_Member_Name,
     sum(Member_Task_Num + CASE WHEN DU_Member_Name = delivery.SDSL THEN Delivery_Task_Num ELSE 0.0 END) AS Total_Task,
     collect(DISTINCT delivery.DID) AS Delivery_IDs
WITH DU_Member_Name, Total_Task, Delivery_IDs
WITH sum(Total_Task) AS Total_Tasks_All,
     collect(DU_Member_Name) AS DU_Members,
     collect(Total_Task) AS DU_Tasks,
     collect(Delivery_IDs) AS DU_DIDs
RETURN DU_Members, DU_Tasks, DU_DIDs, Total_Tasks_All
ORDER BY DU_Members
```

## q048: Please summarize tasks completed by my DU members (under manager {{manager:Person name}}) from {{start_month:Month}} {{start_year:Year}} to present, and compare with department average (under dept leader {{dept_leader:Person name}})

**Business intent**  
Auto-parameterized query to compare DU members' tasks with department average in a specific period

**Parameters**

```json
{
"manager": "tao, yuxi",
      "dept_leader": "Shen, Henry",
      "start_year": 2025,
      "start_month": 1
}
```

**Cypher**

```cypher
WITH date({year: {{start_year:Year}}, month: {{start_month:Month}}, day: 1}) AS startOfPeriod,
     date() AS today,
     '{{manager:Person name}}' AS targetManagerName,
     '{{dept_leader:Person name}}' AS deptLeaderName
MATCH (manager:Person)
WHERE lower(replace(manager.Name, ' ', '')) = lower(replace(targetManagerName, ' ', ''))
OPTIONAL MATCH (manager)<-[:REPORTS_TO]-(duMember:Person)
WITH startOfPeriod, today, deptLeaderName, manager, collect(duMember) + [manager] AS allDuPersons
UNWIND allDuPersons AS duPerson
OPTIONAL MATCH (duPerson)-[w:WORKS_ON]->(delivery:Delivery)
WHERE delivery.DID_Status = 'Completed'
  AND delivery.Actual_Delivery_Date >= startOfPeriod
  AND delivery.Actual_Delivery_Date <= today
WITH startOfPeriod, today, deptLeaderName, duPerson.Name AS duMemberName,
     COALESCE(SUM(coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0)), 0.0)
     + COALESCE(SUM(CASE WHEN duPerson.Name = delivery.SDSL THEN coalesce(toFloat(delivery.CSR_Task_Num), 0.0) + coalesce(toFloat(delivery.SDA_Task_Num), 0.0) + coalesce(toFloat(delivery.STD_Task_Num), 0.0) + coalesce(toFloat(delivery.esub_Task_Data_Num), 0.0) ELSE 0.0 END), 0.0) AS duPersonTotalTask
MATCH (deptLeader:Person)
WHERE lower(replace(deptLeader.Name, ' ', '')) = lower(replace(deptLeaderName, ' ', ''))
OPTIONAL MATCH (subordinate:Person)-[:REPORTS_TO]->(deptLeader)
OPTIONAL MATCH (subordinate)-[sw:WORKS_ON]->(subDelivery:Delivery)
WHERE subDelivery.DID_Status = 'Completed'
  AND subDelivery.Actual_Delivery_Date >= startOfPeriod
  AND subDelivery.Actual_Delivery_Date <= today
WITH duMemberName, duPersonTotalTask,
     COUNT(DISTINCT subordinate) AS deptPersonCount,
     COALESCE(SUM(coalesce(toFloat(sw.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(sw.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(sw.STD_Task_Num_Total), 0.0) + coalesce(toFloat(sw.esub_Data_Num_Total), 0.0)), 0.0)
     + COALESCE(SUM(CASE WHEN subordinate.Name = subDelivery.SDSL THEN coalesce(toFloat(subDelivery.CSR_Task_Num), 0.0) + coalesce(toFloat(subDelivery.SDA_Task_Num), 0.0) + coalesce(toFloat(subDelivery.STD_Task_Num), 0.0) + coalesce(toFloat(subDelivery.esub_Task_Data_Num), 0.0) ELSE 0.0 END), 0.0) AS deptTotalTask
WITH duMemberName, duPersonTotalTask, deptTotalTask,
     CASE WHEN deptPersonCount = 0 THEN 0 ELSE deptTotalTask / TOFLOAT(deptPersonCount) END AS deptAvgTaskPerPerson
RETURN duMemberName AS DU_Member_Name,
       duPersonTotalTask AS Total_Tasks_Per_DU_Member,
       round(deptAvgTaskPerPerson, 2) AS Avg_Tasks_Per_Person_In_Dept
ORDER BY duMemberName
```

## q049: How many tasks will my DU members (including myself) plan to complete in the next {{months:Number of months}} months?

**Business intent**  
Counts planned tasks for each DU member in the next N months

**Parameters**

```json
{
"months": 3,
      "manager": "Liang, Jia Yi (Erin)"
}
```

**Cypher**

```cypher
WITH '{{manager:Person name}}' AS managerName,
     toInteger('{{months:Number of months}}') AS numberOfMonths,
     date() AS today
MATCH (manager:Person)
WHERE replace(toUpper(manager.Name), ' ', '') = replace(toUpper(managerName), ' ', '')
OPTIONAL MATCH (duMember:Person)-[:REPORTS_TO]->(manager)
WITH manager, collect(duMember) + [manager] AS allMembers, today, numberOfMonths
UNWIND allMembers AS person
OPTIONAL MATCH (person)-[work:WORKS_ON]->(delivery:Delivery)
WHERE delivery.DID_Status IN ['Ongoing', 'Planned']
  AND date({year: delivery.Year, month: delivery.Month, day: 1}) >= date({year: today.year, month: today.month, day: 1}) + duration({months: 1})
  AND date({year: delivery.Year, month: delivery.Month, day: 1}) < date({year: today.year, month: today.month, day: 1}) + duration({months: numberOfMonths + 1})
WITH person,
     coalesce(sum(coalesce(toFloat(work.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(work.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(work.STD_Task_Num_Total), 0.0) + coalesce(toFloat(work.esub_Data_Num_Total), 0.0)), 0.0) AS Tasks_Next_Months
RETURN person.Name AS DU_Member, Tasks_Next_Months
ORDER BY Tasks_Next_Months DESC
```

## q051: Please summarize all {{status:Delivery status}} deliveries for my DU (under manager {{manager:Person name}})

**Business intent**  
Auto-parameterized query to list specific status deliveries for a DU

**Parameters**

```json
{
"manager": "tao, yuxi",
      "status": ["Ongoing", "Planned"]
}
```

**Cypher**

```cypher
MATCH (manager:Person) WHERE replace(toUpper(manager.Name), " ", "") = replace(toUpper("{{manager:Person name}}", " ", "")) OPTIONAL MATCH (delivery:Delivery) WHERE delivery.DID_Status IN {{status:Delivery status}} AND (delivery.SDSL = manager.Name OR delivery.SDSA_China_PoC = manager.Name OR delivery.SDSA_US_PoC = manager.Name OR delivery.SDSA_India_PoC = manager.Name) WITH delivery.DID AS Delivery_ID, delivery.Planned_Delivery_Date AS Planned_Delivery_Date, delivery.Reporting_Event AS Reporting_Event, delivery.Study AS Study, delivery.SDSL AS Responsible_SDSL, delivery.Reporting_Detail AS Reporting_Detail RETURN Delivery_ID, Planned_Delivery_Date, Reporting_Event, Study, Responsible_SDSL, Reporting_Detail ORDER BY Planned_Delivery_Date;
```

## q053: Please generate a work summary for my DU members (under manager {{manager:Person name}}) over the past {{summary_period:Months}} months and future {{plan_period:Months}} months

**Business intent**  
Auto-parameterized query to generate DU members' past work summary and future plan

**Parameters**

```json
{
"manager": "tao, yuxi",
      "summary_period": 3,
      "plan_period": 3
}
```

**Cypher**

```cypher
WITH date() AS today,
     date() - duration({months: {{summary_period:Months}}}) AS summaryEnd,
     date() + duration({months: {{plan_period:Months}}}) AS planEnd,
     '{{manager:Person name}}' AS targetManagerName
MATCH (manager:Person)
WHERE replace(toUpper(manager.Name), ' ', '') = replace(toUpper(targetManagerName), ' ', '')
OPTIONAL MATCH (manager)<-[:REPORTS_TO]-(duMember:Person)
WITH manager, collect(duMember) + [manager] AS allDuPersons, today, summaryEnd, planEnd
UNWIND allDuPersons AS duPerson
OPTIONAL MATCH (duPerson)-[w:WORKS_ON]->(delivery:Delivery)
WHERE delivery.DID_Status = 'Completed'
  AND delivery.Actual_Delivery_Date >= summaryEnd
  AND delivery.Actual_Delivery_Date <= today
OPTIONAL MATCH (duPerson)-[w2:WORKS_ON]->(delivery2:Delivery)
WHERE delivery2.DID_Status IN ['Ongoing', 'Planned']
  AND delivery2.Planned_Delivery_Date >= today
  AND delivery2.Planned_Delivery_Date <= planEnd
WITH duPerson.Name AS DU_Member_Name,
     sum(coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0)) AS Past_Work,
     collect(DISTINCT {Future_DID: delivery2.DID, Future_Tasks: coalesce(toFloat(w2.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w2.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w2.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w2.esub_Data_Num_Total), 0.0)}) AS Future_Plan
RETURN DU_Member_Name, Past_Work, Future_Plan
ORDER BY DU_Member_Name
```

## q054: Please summarize all tasks completed by my DU members (under manager {{manager:Person name}}), broken down by season, for the past {{year_count:Years}} years

**Business intent**  
Auto-parameterized query to summarize DU tasks by season for past N years

**Parameters**

```json
{
"manager": "tao, yuxi",
      "year_count": 2
}
```

**Cypher**

```cypher
WITH range(date().year - {{year_count:Years}} + 1, date().year) AS targetYears,
     '{{manager:Person name}}' AS targetManagerName,
     [[1,2,3], [4,5,6], [7,8,9], [10,11,12]] AS seasonMonths
MATCH (manager:Person)
WHERE replace(toUpper(manager.Name), ' ', '') = replace(toUpper(targetManagerName), ' ', '')
OPTIONAL MATCH (manager)<-[:REPORTS_TO]-(teamMember:Person)
WITH manager, collect(teamMember) AS teamMembers, targetYears, seasonMonths
WITH teamMembers + [manager] AS allDUMembers, targetYears, seasonMonths
UNWIND targetYears AS year
UNWIND range(0, size(seasonMonths) - 1) AS season
WITH allDUMembers, year, season,
     year * 12 + seasonMonths[season][0] AS seasonStart,
     year * 12 + seasonMonths[season][2] AS seasonEnd
UNWIND allDUMembers AS duMember
OPTIONAL MATCH (duMember)-[worksOn:WORKS_ON]->(delivery:Delivery)
WHERE delivery.DID_Status = 'Completed'
  AND delivery.Year * 12 + delivery.Month >= seasonStart
  AND delivery.Year * 12 + delivery.Month <= seasonEnd
WITH duMember.Name AS DU_Member_Name, year AS Target_Year, season + 1 AS Target_Season,
     coalesce(toFloat(worksOn.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(worksOn.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(worksOn.STD_Task_Num_Total), 0.0) + coalesce(toFloat(worksOn.esub_Data_Num_Total), 0.0)
     + CASE WHEN duMember.Name = delivery.SDSL THEN coalesce(toFloat(delivery.CSR_Task_Num), 0.0) + coalesce(toFloat(delivery.SDA_Task_Num), 0.0) + coalesce(toFloat(delivery.STD_Task_Num), 0.0) + coalesce(toFloat(delivery.esub_Task_Data_Num), 0.0) ELSE 0.0 END AS Task_Num
WITH DU_Member_Name, Target_Year, Target_Season, sum(Task_Num) AS Total_Completed_Tasks
RETURN DU_Member_Name, Target_Year, Target_Season, Total_Completed_Tasks
ORDER BY DU_Member_Name ASC, Target_Year ASC, Target_Season ASC
```

## q055: Which {{status:Delivery status}} deliveries of my DU (under manager {{manager:Person name}}) are concentrated in the same time period

**Business intent**  
Auto-parameterized query to find concentrated DU deliveries by month

**Parameters**

```json
{
"manager": "tao, yuxi",
      "status": ["Planned", "Ongoing"]
}
```

**Cypher**

```cypher
WITH '{{manager:Person name}}' AS targetManagerName, {{status:Delivery status}} AS targetStatuses
MATCH (manager:Person)
WHERE lower(replace(manager.Name, ' ', '')) = lower(replace(targetManagerName, ' ', ''))
WITH manager.Name AS managerName, targetStatuses
MATCH (manager:Person {Name: managerName})
OPTIONAL MATCH (manager)<-[:REPORTS_TO]-(duMember:Person)
WITH managerName, collect(duMember.Name) + [managerName] AS duMemberNames, targetStatuses
MATCH (d:Delivery)
WHERE d.DID_Status IN targetStatuses
  AND d.Year IS NOT NULL AND d.Month IS NOT NULL
  AND (d.SDSL IN duMemberNames OR d.SDSA_US_PoC IN duMemberNames OR d.SDSA_China_PoC IN duMemberNames OR d.SDSA_India_PoC IN duMemberNames OR d.FSP_Ephicacy_PoC IN duMemberNames OR d.FSP_Fortrea_PoC IN duMemberNames OR d.FSP_TCS_PoC IN duMemberNames OR d.FSP_Other_PoC IN duMemberNames)
OPTIONAL MATCH (respPerson:Person)
WHERE respPerson.Name IN [d.SDSL, d.SDSA_US_PoC, d.SDSA_China_PoC, d.SDSA_India_PoC, d.FSP_Ephicacy_PoC, d.FSP_Fortrea_PoC, d.FSP_TCS_PoC, d.FSP_Other_PoC]
  AND respPerson.Name IN duMemberNames
WITH d, respPerson,
     coalesce(toFloat(d.CSR_Task_Num), 0.0) + coalesce(toFloat(d.SDA_Task_Num), 0.0) + coalesce(toFloat(d.STD_Task_Num), 0.0) + coalesce(toFloat(d.esub_Task_Data_Num), 0.0) AS TotalTasks
WITH DISTINCT d.DID_Status AS Delivery_Status, d.Year AS Delivery_Year, d.Month AS Delivery_Month,
     d.DID AS DeliveryID, d.Study AS StudyName, d.Planned_Delivery_Date AS PlannedDate, TotalTasks,
     coalesce(respPerson.Name, 'Unassigned') AS ResponsibleMember
WITH Delivery_Status, Delivery_Year, Delivery_Month,
     count(DISTINCT DeliveryID) AS Monthly_Delivery_Count,
     collect(DISTINCT {DID: DeliveryID, Study_Name: StudyName, Planned_Date: PlannedDate, Total_Tasks: TotalTasks, Responsible_Member: ResponsibleMember}) AS Monthly_Delivery_Details
RETURN Delivery_Status,
       toString(Delivery_Year) + '-' + CASE WHEN Delivery_Month < 10 THEN '0' + toString(Delivery_Month) ELSE toString(Delivery_Month) END AS Delivery_Year_Month,
       Monthly_Delivery_Count, Monthly_Delivery_Details
ORDER BY Delivery_Year ASC, Delivery_Month ASC, CASE WHEN Delivery_Status = 'Planned' THEN 1 ELSE 2 END
```

## q056: Please summarize the number of tasks and time spent by my DU members (under manager {{manager:Person name}}) in each DID in last {{period:Months}} months

**Business intent**  
Auto-parameterized query to summarize DU members' tasks and time per DID in last N months

**Parameters**

```json
{
"manager": "tao, yuxi",
      "period": 1,
      "status": ["Completed", "Ongoing"]
}
```

**Cypher**

```cypher
WITH '{{manager:Person name}}' AS targetManagerName,
     {{period:Months}} AS periodMonths,
     {{status:Delivery status}} AS targetStatuses
WITH targetManagerName, date() - duration({months: periodMonths}) AS rawStart, targetStatuses
WITH targetManagerName, date({year: rawStart.year, month: rawStart.month, day: 1}) AS pastPeriodStart, targetStatuses
MATCH (manager:Person)
WHERE lower(replace(manager.Name, ' ', '')) = lower(replace(targetManagerName, ' ', ''))
OPTIONAL MATCH (manager)<-[:REPORTS_TO]-(duMember:Person)
WITH manager, collect(duMember.Name) + [manager.Name] AS duMemberNames, pastPeriodStart, targetStatuses
UNWIND duMemberNames AS duMemberName
MATCH (duMember:Person {Name: duMemberName})
OPTIONAL MATCH (duMember)-[t:TIME_ON]->(m:DIDN_Month)-[:BELONGS_TO]->(d:Delivery)<-[w:WORKS_ON]-(duMember)
WHERE d.DID_Status IN targetStatuses
  AND m.Year = pastPeriodStart.year
  AND m.Month = pastPeriodStart.month
WITH duMember.Name AS DU_Member, d.DID AS Delivery_ID, d.Study AS Study_Name,
     coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0) AS Total_Tasks,
     sum(coalesce(toFloat(t.Hour), 0.0)) AS Total_Time_Hours
RETURN DU_Member, Delivery_ID, Study_Name, Total_Tasks, Total_Time_Hours
ORDER BY DU_Member ASC, Total_Tasks DESC
```

## q057: Summarize, by member and by month, which tasks each DU member is expected to complete in the next {{months:Number of months}} months.

**Business intent**  
Summarizes expected tasks for each DU member in the next N months

**Parameters**

```json
{
"months": 3,
      "manager": "tao, yuxi"
}
```

**Cypher**

```cypher
WITH '{{manager:Person name}}' AS managerName,
     toInteger('{{months:Number of months}}') AS numberOfMonths,
     date() AS today
UNWIND range(1, numberOfMonths) AS monthOffset
WITH managerName, monthOffset, today + duration({months: monthOffset}) AS targetDate
MATCH (manager:Person)
WHERE replace(toUpper(manager.Name), ' ', '') = replace(toUpper(managerName), ' ', '')
OPTIONAL MATCH (duMember:Person)-[:REPORTS_TO]->(manager)
WITH targetDate.year AS year, targetDate.month AS month, manager, collect(DISTINCT duMember) AS directMembers
WITH year, month, [member IN ([manager] + directMembers) WHERE member IS NOT NULL] AS allMembers
UNWIND allMembers AS member
OPTIONAL MATCH (member)-[work:WORKS_ON]->(delivery:Delivery)
WHERE delivery.DID_Status IN ['Ongoing', 'Planned']
  AND delivery.Year = year
  AND delivery.Month = month
WITH year, month, member,
     sum(coalesce(toFloat(work.CSR_Task_Num_Total), 0.0)) AS CSR_Tasks,
     sum(coalesce(toFloat(work.SDA_Task_Num_Total), 0.0)) AS SDA_Tasks,
     sum(coalesce(toFloat(work.STD_Task_Num_Total), 0.0)) AS STD_Tasks,
     sum(coalesce(toFloat(work.esub_Data_Num_Total), 0.0)) AS eSub_Tasks
RETURN member.Name AS DU_Member, year AS Year, month AS Month,
       CSR_Tasks, SDA_Tasks, STD_Tasks, eSub_Tasks,
       CSR_Tasks + SDA_Tasks + STD_Tasks + eSub_Tasks AS Expected_Total_Tasks
ORDER BY DU_Member, Year, Month
```

## q058: Please summarize all {{status:Delivery status}} deliveries my DU (under manager {{manager:Person name}}) completed, with task breakdown by person

**Business intent**  
Auto-parameterized query to summarize DU's completed deliveries and task breakdown by person

**Parameters**

```json
{
"manager": "tao, yuxi",
      "status": "Completed"
}
```

**Cypher**

```cypher
WITH '{{manager:Person name}}' AS managerName
MATCH (manager:Person)
WHERE replace(toUpper(manager.Name), ' ', '') = replace(toUpper(managerName), ' ', '')
OPTIONAL MATCH (manager)<-[:REPORTS_TO]-(duMember:Person)
WITH manager, collect(duMember) + [manager] AS allDuPersons
UNWIND allDuPersons AS duPerson
OPTIONAL MATCH (duPerson)-[w:WORKS_ON]->(completedDelivery:Delivery)
WHERE completedDelivery.DID_Status = '{{status:Delivery status}}'
WITH duPerson.Name AS DU_Member_Name,
     COUNT(DISTINCT completedDelivery) AS Member_Completed_Deliveries,
     collect(DISTINCT completedDelivery.Name) AS Member_Delivery_Names,
     COALESCE(SUM(coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0)), 0.0) AS Member_Total_Tasks
RETURN DU_Member_Name,
       Member_Completed_Deliveries AS Completed_Deliveries_Per_Member,
       Member_Delivery_Names AS Delivery_Names_Per_Member,
       Member_Total_Tasks AS Total_Tasks_Per_Member
ORDER BY DU_Member_Name
```

## q059: Please summarize all {{status:Delivery status}} deliveries for my DU (under manager {{manager:Person name}})

**Business intent**  
Auto-parameterized query to list specific status deliveries for a DU (duplicate of q051, adjusted for consistency)

**Parameters**

```json
{
"manager": "tao, yuxi",
      "status": ["Ongoing", "Planned"]
}
```

**Cypher**

```cypher
MATCH (manager:Person) WHERE replace(toUpper(manager.Name), " ", "") = replace(toUpper("{{manager:Person name}}", " ", "")) OPTIONAL MATCH (delivery:Delivery) WHERE delivery.DID_Status IN {{status:Delivery status}} AND (delivery.SDSL = manager.Name OR delivery.SDSA_China_PoC = manager.Name OR delivery.SDSA_US_PoC = manager.Name OR delivery.SDSA_India_PoC = manager.Name) WITH delivery.DID AS Delivery_ID, delivery.Planned_Delivery_Date AS Planned_Delivery_Date, delivery.Reporting_Event AS Reporting_Event, delivery.Study AS Study, delivery.SDSL AS Responsible_SDSL, delivery.Reporting_Detail AS Reporting_Detail RETURN Delivery_ID, Planned_Delivery_Date, Reporting_Event, Study, Responsible_SDSL, Reporting_Detail ORDER BY Planned_Delivery_Date;
```

## q060: List DU members (including myself) who do not have any deliveries for next month.

**Business intent**  
Lists DU members with no deliveries next month

**Parameters**

```json
{
"manager": "Fei, Qili"
}
```

**Cypher**

```cypher
// Step 1: Calculate year and month for next month
WITH date() AS today
WITH today.year AS baseYear, today.month AS baseMonth
WITH CASE WHEN baseMonth + 1 > 12 THEN baseYear + 1 ELSE baseYear END AS nextYear, CASE WHEN baseMonth + 1 > 12 THEN baseMonth + 1 - 12 ELSE baseMonth + 1 END AS nextMonth
// Step 2: Get DU members (including yourself)
MATCH (manager:Person)
WHERE replace(toUpper(manager.Name), " ", "") = replace(toUpper("{{manager:Manager name}}"), " ", "")
OPTIONAL MATCH (manager)<-[:REPORTS_TO]-(duMember:Person)
WITH nextYear, nextMonth, collect(manager) + collect(duMember) AS allMembers
UNWIND allMembers AS person
// Step 3: Find deliveries for each member for next month
OPTIONAL MATCH (person)-[:WORKS_ON]->(delivery:Delivery)
WHERE delivery.Year = nextYear AND delivery.Month = nextMonth
WITH person.Name AS DU_Member, collect(delivery) AS deliveries
// Step 4: Only return members with no deliveries
WHERE size(deliveries) = 0
RETURN DU_Member AS DU_Member_No_Delivery_Next_Month
ORDER BY DU_Member
```

## q061: Please summarize tasks and deliveries of each DU for TA Lead {{ta_lead:Person name}}

**Business intent**  
Auto-parameterized query to summarize each DU's tasks/deliveries under a specific TA Lead

**Parameters**

```json
{
"ta_lead": "Zhuang, meinan"
}
```

**Cypher**

```cypher
WITH '{{ta_lead:Person name}}' AS targetTALeadName
MATCH path = (taLead:Person)<-[:REPORTS_TO*0..]-(duManager:Person)
WHERE replace(toUpper(taLead.Name), ' ', '') = replace(toUpper(targetTALeadName), ' ', '')
  AND duManager.Manager IS NOT NULL AND duManager.Manager <> ''
OPTIONAL MATCH (duManager)<-[:REPORTS_TO]-(duMember:Person)
WITH duManager, collect(duMember) + [duManager] AS allDUMembers
UNWIND allDUMembers AS duPerson
OPTIONAL MATCH (duPerson)-[w:WORKS_ON]->(completedDelivery:Delivery)
WHERE completedDelivery.DID_Status = 'Completed'
WITH duManager.Name AS DU_Manager_Name,
     coalesce(sum(coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0)), 0.0)
     + coalesce(sum(CASE WHEN duPerson.Name = completedDelivery.SDSL THEN coalesce(toFloat(completedDelivery.CSR_Task_Num), 0.0) + coalesce(toFloat(completedDelivery.SDA_Task_Num), 0.0) + coalesce(toFloat(completedDelivery.STD_Task_Num), 0.0) + coalesce(toFloat(completedDelivery.esub_Task_Data_Num), 0.0) ELSE 0.0 END), 0.0) AS DU_Total_Completed_Tasks,
     count(DISTINCT completedDelivery) AS DU_Total_Completed_Deliveries
RETURN DU_Manager_Name AS DU_Identifier,
       DU_Total_Completed_Tasks AS Total_Completed_Tasks_Per_DU,
       DU_Total_Completed_Deliveries AS Total_Completed_Deliveries_Per_DU
ORDER BY DU_Manager_Name
```

## q062: Summarize the workload of each DU member (including myself) for the coming month.

**Business intent**  
Summarizes the workload for each DU member for the coming month

**Parameters**

```json
{
"manager": "Liang, Jia Yi (Erin)"
}
```

**Cypher**

```cypher
WITH date() AS today
WITH today.year AS baseYear, today.month AS baseMonth
WITH CASE WHEN baseMonth + 1 > 12 THEN baseYear + 1 ELSE baseYear END AS nextYear,
     CASE WHEN baseMonth + 1 > 12 THEN baseMonth + 1 - 12 ELSE baseMonth + 1 END AS nextMonth
MATCH (manager:Person)
WHERE replace(toUpper(manager.Name), ' ', '') = replace(toUpper('{{manager:Person name}}'), ' ', '')
OPTIONAL MATCH (manager)<-[:REPORTS_TO]-(duMember:Person)
WITH nextYear, nextMonth, collect(manager) + collect(duMember) AS allMembers
UNWIND allMembers AS person
OPTIONAL MATCH (person)-[w:WORKS_ON]->(delivery:Delivery)
WHERE delivery.Year = nextYear AND delivery.Month = nextMonth
WITH person.Name AS DU_Member,
     SUM(coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0)) AS Expected_Tasks,
     collect(DISTINCT delivery.DID) AS Delivery_IDs
RETURN DU_Member AS DU_Member,
       Expected_Tasks AS Expected_Tasks_Next_Month,
       Delivery_IDs AS Delivery_IDs_Next_Month
ORDER BY DU_Member
```

## q063: Please summarize {{status:Delivery status}} deliveries and tasks for my DU (under manager {{manager:Person name}}) in next {{period:Months}} months, and compare with other DUs in my department (under dept leader {{dept_leader:Person name}})

**Business intent**  
Auto-parameterized query to compare DU's future deliveries/tasks with department average

**Parameters**

```json
{
"manager": "tao, yuxi",
      "dept_leader": "Shen, Henry",
      "period": 3,
      "status": ["Ongoing", "Planned"]
}
```

**Cypher**

```cypher
WITH '{{manager:Person name}}' AS yourName,
     '{{dept_leader:Person name}}' AS deptLeaderName,
     (date().year * 12 + date().month) AS minMonth,
     (date().year * 12 + date().month) + {{period:Months}} AS maxMonth,
     {{status:Delivery status}} AS targetStatuses
MATCH (you:Person)
WHERE replace(toUpper(you.Name), ' ', '') = replace(toUpper(yourName), ' ', '')
OPTIONAL MATCH (you)<-[:REPORTS_TO]-(duMember:Person)
WITH duMember, you, collect(duMember) + [you] AS yourDUMembers, minMonth, maxMonth, deptLeaderName, targetStatuses
UNWIND yourDUMembers AS duPerson
OPTIONAL MATCH (duDelivery:Delivery)
WHERE duDelivery.DID_Status IN targetStatuses
  AND (duDelivery.Year * 12 + duDelivery.Month) >= minMonth
  AND (duDelivery.Year * 12 + duDelivery.Month) <= maxMonth
  AND (duPerson.Name = duDelivery.SDSL OR duPerson.Name = duDelivery.SDSA_China_PoC OR duPerson.Name = duDelivery.SDSA_US_PoC OR duPerson.Name = duDelivery.SDSA_India_PoC)
WITH you.Name AS DU_Name,
     count(DISTINCT duDelivery) AS yourDu_Future_Deliveries,
     coalesce(sum(coalesce(toFloat(duDelivery.CSR_Task_Num), 0.0) + coalesce(toFloat(duDelivery.SDA_Task_Num), 0.0) + coalesce(toFloat(duDelivery.STD_Task_Num), 0.0) + coalesce(toFloat(duDelivery.esub_Task_Data_Num), 0.0)), 0.0) AS yourDu_Future_Tasks,
     minMonth, maxMonth, deptLeaderName, targetStatuses
MATCH (deptLeader:Person)
WHERE replace(toUpper(deptLeader.Name), ' ', '') = replace(toUpper(deptLeaderName), ' ', '')
OPTIONAL MATCH (deptLeader)<-[:REPORTS_TO]-(duManager:Person)
WHERE duManager.Manager IS NOT NULL AND duManager.Manager <> ''
OPTIONAL MATCH (duManager)<-[:REPORTS_TO]-(deptMember:Person)
WITH deptMember, duManager, duManager.Name AS Dept_DU_Manager,
     collect(deptMember) + [duManager] AS deptDUMembers,
     minMonth, maxMonth, DU_Name, yourDu_Future_Deliveries, yourDu_Future_Tasks, targetStatuses
UNWIND deptDUMembers AS deptPerson
OPTIONAL MATCH (deptDelivery:Delivery)
WHERE deptDelivery.DID_Status IN targetStatuses
  AND (deptDelivery.Year * 12 + deptDelivery.Month) >= minMonth
  AND (deptDelivery.Year * 12 + deptDelivery.Month) <= maxMonth
  AND (deptPerson.Name = deptDelivery.SDSL OR deptPerson.Name = deptDelivery.SDSA_China_PoC OR deptPerson.Name = deptDelivery.SDSA_US_PoC OR deptPerson.Name = deptDelivery.SDSA_India_PoC)
WITH DU_Name, yourDu_Future_Deliveries, yourDu_Future_Tasks, Dept_DU_Manager,
     count(DISTINCT deptDelivery) AS deptDu_Future_Deliveries,
     coalesce(sum(coalesce(toFloat(deptDelivery.CSR_Task_Num), 0.0) + coalesce(toFloat(deptDelivery.SDA_Task_Num), 0.0) + coalesce(toFloat(deptDelivery.STD_Task_Num), 0.0) + coalesce(toFloat(deptDelivery.esub_Task_Data_Num), 0.0)), 0.0) AS deptDu_Future_Tasks
WITH DU_Name, yourDu_Future_Deliveries, yourDu_Future_Tasks,
     collect({Dept_DU_Manager: Dept_DU_Manager, Dept_DU_Future_Deliveries: deptDu_Future_Deliveries, Dept_DU_Future_Tasks: deptDu_Future_Tasks}) AS allDeptDUs
WITH DU_Name, yourDu_Future_Deliveries, yourDu_Future_Tasks, allDeptDUs,
     [x IN allDeptDUs WHERE x.Dept_DU_Manager IS NOT NULL] AS validDeptDUs
WITH DU_Name, yourDu_Future_Deliveries, yourDu_Future_Tasks, validDeptDUs,
     CASE WHEN size(validDeptDUs) = 0 THEN 0 ELSE reduce(s = 0.0, x IN validDeptDUs | s + x.Dept_DU_Future_Deliveries) / toFloat(size(validDeptDUs)) END AS dept_Avg_Future_Deliveries,
     CASE WHEN size(validDeptDUs) = 0 THEN 0 ELSE reduce(s = 0.0, x IN validDeptDUs | s + x.Dept_DU_Future_Tasks) / toFloat(size(validDeptDUs)) END AS dept_Avg_Future_Tasks
RETURN {Your_DU: DU_Name, Future_Period_Deliveries: yourDu_Future_Deliveries, Future_Period_Tasks: yourDu_Future_Tasks} AS Your_DU_Summary,
       {Dept_Avg_Future_Deliveries: round(dept_Avg_Future_Deliveries, 1), Dept_Avg_Future_Tasks: round(dept_Avg_Future_Tasks, 1)} AS Dept_Average_Summary,
       validDeptDUs AS All_Dept_DUs_Detail
```

## q064: Please summarize tasks and deliveries of each TA from {{start_month:Month}} {{start_year:Year}} to present

**Business intent**  
Auto-parameterized query to summarize each TA's tasks/deliveries in a specific period

**Parameters**

```json
{
"start_year": 2025,
      "start_month": 1
}
```

**Cypher**

```cypher
WITH date({year: {{start_year:Year}}, month: {{start_month:Month}}, day: 1}) AS startOfPeriod, date() AS today
MATCH (taLeader:Person)
WHERE taLeader.TA_Lead IS NOT NULL AND taLeader.TA_Lead <> ''
OPTIONAL MATCH path = (subordinate:Person)-[:REPORTS_TO*0..]->(taLeader)
OPTIONAL MATCH (subordinate)-[w:WORKS_ON]->(delivery:Delivery)
WHERE delivery.DID_Status IN ['Completed']
  AND delivery.Actual_Delivery_Date >= startOfPeriod
  AND delivery.Actual_Delivery_Date <= today
WITH taLeader.Name AS TA_Leader_Name,
     collect(DISTINCT delivery.DID) AS Period_Delivery_Ids,
     coalesce(sum(coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0)), 0.0)
     + coalesce(sum(CASE WHEN subordinate.Name = delivery.SDSL THEN coalesce(toFloat(delivery.CSR_Task_Num), 0.0) + coalesce(toFloat(delivery.SDA_Task_Num), 0.0) + coalesce(toFloat(delivery.STD_Task_Num), 0.0) + coalesce(toFloat(delivery.esub_Task_Data_Num), 0.0) ELSE 0.0 END), 0.0) AS Period_Total_Tasks
WITH TA_Leader_Name, size(Period_Delivery_Ids) AS Period_Total_Deliveries, Period_Total_Tasks
WHERE Period_Total_Deliveries > 0 OR Period_Total_Tasks > 0
RETURN TA_Leader_Name, Period_Total_Deliveries, Period_Total_Tasks
ORDER BY TA_Leader_Name, Period_Total_Tasks DESC
```

## q065: Please summarize the number of tasks completed by each person in my DU (under manager {{manager:Person name}}), categorized by {{task_type:Task type}} Generation and QC

**Business intent**  
Auto-parameterized query to summarize DU members' tasks by Generation/QC for specific task types

**Parameters**

```json
{
"manager": "tao, yuxi",
      "task_type": "SDTM,ADaM,TLF"
}
```

**Cypher**

```cypher
WITH '{{manager:Person name}}' AS targetManagerName
MATCH (manager:Person)
WHERE replace(toUpper(manager.Name), ' ', '') = replace(toUpper(targetManagerName), ' ', '')
OPTIONAL MATCH (manager)<-[:REPORTS_TO]-(duMember:Person)
WITH manager, collect(duMember) + [manager] AS allDUMembers
UNWIND allDUMembers AS duPerson
OPTIONAL MATCH (duPerson)-[workOn:WORKS_ON]->(delivery:Delivery)
WHERE delivery.DID_Status = 'Completed'
RETURN delivery.Study AS Study_Name,
       delivery.DID AS Study_DID,
       duPerson.Name AS DU_Member_Name,
       workOn.CSR_{{task_type:Task type}}_Num_Generation AS {{task_type:Task type}}_Generation_Tasks,
       workOn.CSR_{{task_type:Task type}}_Num_QC AS {{task_type:Task type}}_QC_Tasks,
       workOn.CSR_{{task_type:Task type}}_Num_Total AS Total_Completed_Tasks_Per_Study
ORDER BY Study_Name, Study_DID, DU_Member_Name
```

## q068: Please let me know how many {{status:Delivery status}} deliveries my DU (under manager {{manager:Person name}}) will have in next {{period:Months}} months

**Business intent**  
Auto-parameterized query to count DU's upcoming deliveries in next N months

**Parameters**

```json
{
"manager": "Ma, Xin",
      "period": 1,
      "status": ["Ongoing", "Planned"]
}
```

**Cypher**

```cypher
WITH "{{manager:Person name}}" AS yourName, date() AS today, (date().year * 12 + date().month) + {{period:Months}} AS nextPeriodCode MATCH (you:Person) WHERE replace(toUpper(you.Name), " ", "") = replace(toUpper(yourName), " ", "") OPTIONAL MATCH (you)-[:REPORTS_TO]->(duManager:Person) OPTIONAL MATCH (duManager)<-[:REPORTS_TO]-(duColleague:Person) WITH you, duManager, collect(duColleague) + [you] + CASE WHEN duManager IS NOT NULL THEN [duManager] ELSE [] END AS allDuMembers, nextPeriodCode UNWIND allDuMembers AS duMember MATCH (delivery:Delivery) WHERE (delivery.Year * 12 + delivery.Month) <= nextPeriodCode AND delivery.DID_Status IN {{status:Delivery status}} AND (delivery.SDSL = duMember.Name OR delivery.SDSA_US_PoC = duMember.Name OR delivery.SDSA_China_PoC = duMember.Name OR delivery.SDSA_India_PoC = duMember.Name OR delivery.FSP_Ephicacy_PoC = duMember.Name OR delivery.FSP_Fortrea_PoC = duMember.Name OR delivery.FSP_TCS_PoC = duMember.Name OR delivery.FSP_Other_PoC = duMember.Name) AND delivery.Year IS NOT NULL AND delivery.Month IS NOT NULL RETURN you.Name AS Your_Name, duManager.Name AS DU_Manager_Name, COUNT(DISTINCT delivery.DID) AS Total_DU_Upcoming_Deliveries_Next_Period, collect(DISTINCT {DID: delivery.DID, Study_Name: delivery.Study, Planned_Delivery_Date: delivery.Planned_Delivery_Date}) AS DU_Upcoming_Delivery_Details ORDER BY Your_Name, DU_Manager_Name;
```
