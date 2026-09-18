# Reporting Dashboard Examples

> These are dashboard-style examples for executive summaries, KPI reporting, TLF volume, tasks, and hours. They are based on the 16 examples provided in the chat and should be used as high-priority few-shot examples for reporting questions.

## dashboard_q001: Top 10 studies with high TLF volume

**Use when user asks:** Top studies by TLF Volume, display SDSL and general study information.

```cypher
MATCH (s:Study)-[:HAS_DELIVERY]->(d:Delivery)
OPTIONAL MATCH (s)-[:HAS_DETAIL]->(info:Study_Info)
OPTIONAL MATCH (sdsl:Person)-[:WORKS_AS]->(s)
WHERE sdsl.Name = s.SDSL
OPTIONAL MATCH (sdsl)-[:REPORTS_TO*1..]->(groupLead:Person)
WHERE groupLead.Group_Lead IS NOT NULL AND groupLead.Group_Lead <> ''
OPTIONAL MATCH (sdsl)-[:REPORTS_TO*1..]->(taLead:Person)
WHERE taLead.TA_Lead IS NOT NULL AND taLead.TA_Lead <> ''
RETURN
  s.Name AS Study_Name,
  SUM(coalesce(toFloat(d.CSR_TLF_Num), 0.0)) AS TLF_Volume,
  d.SDSL AS SDSL,
  groupLead.Name AS Group_Lead,
  taLead.Name AS TA_Lead,
  s.TA AS TA,
  info.Plan_Phase AS Plan_Phase,
  info.Plan_Status AS Plan_Status,
  info.Study_Type AS Study_Type,
  info.FAP AS FAP,
  info.FSFV AS FSFV,
  info.LSLV AS LSLV,
  info.DBR AS DBR
ORDER BY TLF_Volume DESC
LIMIT 10
```

## dashboard_q002: Top 10 studies with high TLF volume in last 3 months

```cypher
WITH date() AS today
WITH today, (today.year * 12 + today.month) - 3 AS minMonth, (today.year * 12 + today.month) AS maxMonth
MATCH (s:Study)-[:HAS_DELIVERY]->(d:Delivery)
WHERE (d.Year * 12 + d.Month) >= minMonth
  AND (d.Year * 12 + d.Month) < maxMonth
  AND d.DID_Status = 'Completed'
OPTIONAL MATCH (s)-[:HAS_DETAIL]->(info:Study_Info)
OPTIONAL MATCH (sdsl:Person)-[:WORKS_AS]->(s)
WHERE sdsl.Name = d.SDSL
OPTIONAL MATCH (sdsl)-[:REPORTS_TO*1..]->(groupLead:Person)
WHERE groupLead.Group_Lead IS NOT NULL AND groupLead.Group_Lead <> ''
OPTIONAL MATCH (sdsl)-[:REPORTS_TO*1..]->(taLead:Person)
WHERE taLead.TA_Lead IS NOT NULL AND taLead.TA_Lead <> ''
RETURN
  s.Name AS Study_Name,
  SUM(coalesce(toFloat(d.CSR_TLF_Num), 0.0)) AS TLF_Volume,
  d.SDSL AS SDSL,
  groupLead.Name AS Group_Lead,
  taLead.Name AS TA_Lead,
  s.TA AS TA,
  info.Plan_Phase AS Plan_Phase,
  info.Plan_Status AS Plan_Status,
  info.Study_Type AS Study_Type,
  info.FAP AS FAP,
  info.FSFV AS FSFV,
  info.LSLV AS LSLV,
  info.DBR AS DBR
ORDER BY TLF_Volume DESC
LIMIT 10
```

## dashboard_q003: Top 10 studies with high TLF volume in a target quarter

```cypher
WITH 2025 AS targetYear, [1, 2, 3] AS targetMonths
WITH targetYear * 12 + targetMonths[0] AS minMonth,
     targetYear * 12 + targetMonths[2] AS maxMonth
MATCH (s:Study)-[:HAS_DELIVERY]->(d:Delivery)
WHERE (d.Year * 12 + d.Month) >= minMonth
  AND (d.Year * 12 + d.Month) <= maxMonth
  AND d.DID_Status = 'Completed'
OPTIONAL MATCH (s)-[:HAS_DETAIL]->(info:Study_Info)
OPTIONAL MATCH (sdsl:Person)-[:WORKS_AS]->(s)
WHERE sdsl.Name = d.SDSL
OPTIONAL MATCH (sdsl)-[:REPORTS_TO*1..]->(groupLead:Person)
WHERE groupLead.Group_Lead IS NOT NULL AND groupLead.Group_Lead <> ''
OPTIONAL MATCH (sdsl)-[:REPORTS_TO*1..]->(taLead:Person)
WHERE taLead.TA_Lead IS NOT NULL AND taLead.TA_Lead <> ''
RETURN
  s.Name AS Study_Name,
  SUM(coalesce(toFloat(d.CSR_TLF_Num), 0.0)) AS TLF_Volume,
  d.SDSL AS SDSL,
  groupLead.Name AS Group_Lead,
  taLead.Name AS TA_Lead,
  s.TA AS TA,
  info.Plan_Phase AS Plan_Phase,
  info.Plan_Status AS Plan_Status,
  info.Study_Type AS Study_Type,
  info.FAP AS FAP,
  info.FSFV AS FSFV,
  info.LSLV AS LSLV,
  info.DBR AS DBR
ORDER BY TLF_Volume DESC
LIMIT 10
```

## dashboard_q004: Completed delivery task and hands-on hour summary

```cypher
MATCH (d:Delivery)<-[:BELONGS_TO]-(dm:DIDN_Month)
WHERE d.DID_Status = 'Completed'
WITH
  d.Study AS Study_Name,
  d.Name AS DID,
  d.Reporting_Event AS Reporting_Event,
  d.Reporting_Detail AS Reporting_Detail,
  d.Planned_Delivery_Date AS Planned_Date,
  d.Actual_Delivery_Date AS Actual_Date,
  coalesce(toFloat(d.CSR_Task_Num), 0.0) + coalesce(toFloat(d.SDA_Task_Num), 0.0) + coalesce(toFloat(d.STD_Task_Num), 0.0) + coalesce(toFloat(d.esub_Task_Data_Num), 0.0) AS Task,
  toInteger(SUM(dm.Hour)) AS Delivery_HandsOn_Hours
RETURN
  Study_Name,
  DID,
  Reporting_Event,
  Reporting_Detail,
  Planned_Date,
  Actual_Date,
  Task,
  Delivery_HandsOn_Hours
ORDER BY Delivery_HandsOn_Hours DESC
```

## dashboard_q005: Person task and time spent on completed deliveries

```cypher
MATCH (p:Person)
WHERE replace(toUpper(p.Name), " ", "") = replace(toUpper("{{person_name}}"), " ", "")
MATCH (p)-[w:WORKS_ON]->(d:Delivery)
WHERE d.DID_Status = "Completed"
OPTIONAL MATCH (p)-[t:TIME_ON]->(dm:DIDN_Month)-[:BELONGS_TO]->(d)
WITH
  d.Study AS Study,
  d.Name AS DID,
  d.Reporting_Event AS Reporting_Event,
  d.Reporting_Detail AS Reporting_Detail,
  d.Actual_Delivery_Date AS Actual_Date,
  SUM(coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0)) AS Task,
  SUM(DISTINCT t.Hour) AS Time_Spent
RETURN
  Study,
  DID,
  Reporting_Event,
  Reporting_Detail,
  Actual_Date,
  Task,
  Time_Spent,
  CASE WHEN Task <> 0 THEN round(Time_Spent * 1.0 / Task, 2) ELSE NULL END AS Time_Per_Task
ORDER BY Time_Per_Task DESCENDING, DID
```

## dashboard_q006: Ongoing/planned deliveries for a specific person in next 6 months

```cypher
WITH date() AS today
WITH today, (today.year * 12 + today.month) AS currentMonth,
     (today.year * 12 + today.month) + 6 AS maxMonth
MATCH (p:Person)-[w:WORKS_ON]->(d:Delivery)
WHERE replace(toUpper(p.Name), " ", "") = replace(toUpper("{{person_name}}"), " ", "")
  AND d.DID_Status IN ["Ongoing", "Planned"]
  AND (d.Year * 12 + d.Month) >= currentMonth
  AND (d.Year * 12 + d.Month) <= maxMonth
RETURN
  d.Study AS Study,
  d.Name AS DID,
  d.DID_Status AS DID_Status,
  d.Reporting_Event AS Reporting_Event,
  d.Reporting_Detail AS Reporting_Detail,
  d.Planned_Delivery_Date AS Planned_Delivery_Date,
  coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0) AS Task_Num
ORDER BY d.Planned_Delivery_Date
```

## dashboard_q007: Studies where SDSL is from India site

```cypher
MATCH (s:Study)
MATCH (sdsl:Person)-[:FROM_SITE]->(site:Site)
WHERE sdsl.Name = s.SDSL AND site.Name = 'India'
OPTIONAL MATCH (s)-[:HAS_DETAIL]->(info:Study_Info)
RETURN
  s.Name AS Study_Name,
  s.SDSL AS SDSL_Name,
  site.Name AS Site,
  s.TA AS TA,
  info.Plan_Phase AS Plan_Phase,
  info.Plan_Status AS Plan_Status,
  info.Study_Type AS Study_Type,
  info.FAP AS FAP,
  info.FSFV AS FSFV,
  info.LSLV AS LSLV,
  info.DBR AS DBR
ORDER BY Study_Name
```

## dashboard_q008: Active Phase III studies and SDSL information

```cypher
MATCH (s:Study)-[:HAS_DETAIL]->(info:Study_Info)
WHERE toUpper(info.Plan_Phase) = 'PH III' AND toUpper(info.Plan_Status) = 'ACTIVE'
OPTIONAL MATCH (sdsl:Person)-[:WORKS_AS]->(s)
WHERE sdsl.Name = s.SDSL
OPTIONAL MATCH (sdsl)-[:REPORTS_TO*1..]->(groupLead:Person)
WHERE groupLead.Group_Lead IS NOT NULL AND groupLead.Group_Lead <> ''
OPTIONAL MATCH (sdsl)-[:REPORTS_TO*1..]->(taLead:Person)
WHERE taLead.TA_Lead IS NOT NULL AND taLead.TA_Lead <> ''
RETURN
  s.Name AS Study_Name,
  s.SDSL AS SDSL_Name,
  groupLead.Name AS Group_Lead,
  taLead.Name AS TA_Lead,
  s.TA AS TA,
  info.Plan_Phase AS Plan_Phase,
  info.Plan_Status AS Plan_Status,
  info.Study_Type AS Study_Type,
  info.FAP AS FAP,
  info.FSFV AS FSFV,
  info.LSLV AS LSLV,
  info.DBR AS DBR
ORDER BY Study_Name
```

## dashboard_q009: LoT for a specific DID

```cypher
MATCH (d:Delivery {Name: "{{delivery_name}}"})
OPTIONAL MATCH (d)-[sdtmRel:HAS_SDTM]->(sdtm:SDTM)
OPTIONAL MATCH (d)-[adamRel:HAS_ADAM]->(adam:ADaM)
OPTIONAL MATCH (d)-[tlfRel:HAS_TLF]->(tlf:TLF)
WITH d,
  collect(DISTINCT {Category: sdtm.Category, Type: sdtm.Type, Name: sdtm.Name, Generation: sdtmRel.Generation, QC: sdtmRel.QC}) +
  collect(DISTINCT {Category: adam.Category, Type: adam.Type, Name: adam.Name, Generation: adamRel.Generation, QC: adamRel.QC}) +
  collect(DISTINCT {Category: tlf.Category, Type: tlf.Type, Name: tlf.Name, Source: tlf.Source, Generation: tlfRel.Generation, QC: tlfRel.QC, File_Name: tlfRel.File_Name, TLF_Number: tlfRel.TLF_Number}) AS allItems
UNWIND allItems AS item
RETURN
  d.Name AS DID,
  item.Category AS Category,
  item.Type AS Type,
  item.Name AS Name,
  item.Generation AS Generation,
  item.QC AS QC,
  item.Source AS Source,
  item.File_Name AS File_Name,
  item.TLF_Number AS TLF_Number
ORDER BY item.Type, item.Name
```

## dashboard_q010: Person tasks for a specific delivery

```cypher
MATCH (d:Delivery {Name: "{{delivery_name}}"})
MATCH (p:Person)-[w:WORKS_ON]->(d)
WHERE toUpper(replace(p.Name, " ", "")) = toUpper(replace("{{person_name}}", " ", ""))
OPTIONAL MATCH (d)-[sdtmRel:HAS_SDTM]->(sdtm:SDTM)
WHERE sdtmRel.Generation CONTAINS "{{person_name}}" OR sdtmRel.QC CONTAINS "{{person_name}}"
OPTIONAL MATCH (d)-[adamRel:HAS_ADAM]->(adam:ADaM)
WHERE adamRel.Generation CONTAINS "{{person_name}}" OR adamRel.QC CONTAINS "{{person_name}}"
OPTIONAL MATCH (d)-[tlfRel:HAS_TLF]->(tlf:TLF)
WHERE tlfRel.Generation CONTAINS "{{person_name}}" OR tlfRel.QC CONTAINS "{{person_name}}"
WITH d, w, p,
  collect(DISTINCT {Category: sdtm.Category, Type: sdtm.Type, Name: sdtm.Name, Generation: sdtmRel.Generation, QC: sdtmRel.QC}) +
  collect(DISTINCT {Category: adam.Category, Type: adam.Type, Name: adam.Name, Generation: adamRel.Generation, QC: adamRel.QC}) +
  collect(DISTINCT {Category: tlf.Category, Type: tlf.Type, Name: tlf.Name, Source: tlf.Source, Generation: tlfRel.Generation, QC: tlfRel.QC, File_Name: tlfRel.File_Name, TLF_Number: tlfRel.TLF_Number}) AS filteredItems
UNWIND filteredItems AS item
RETURN
  d.Name AS DID,
  p.Name AS Person,
  coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0) AS Task_Num,
  item.Category AS Category,
  item.Type AS Type,
  item.Name AS Name,
  item.Generation AS Generation,
  item.QC AS QC,
  item.Source AS Source,
  item.File_Name AS File_Name,
  item.TLF_Number AS TLF_Number
ORDER BY item.Type, item.Name
```

## dashboard_q011: Team members reporting to recursively identified manager

```cypher
MATCH (x:Person)
WHERE replace(toUpper(x.Name), " ", "") = replace(toUpper("{{person_name}}"), " ", "")
OPTIONAL MATCH (x)-[:REPORTS_TO*1..]->(y:Person)
WHERE y.Manager IS NOT NULL AND y.Manager <> ''
WITH CASE WHEN x.Manager IS NOT NULL AND x.Manager <> '' THEN x ELSE y END AS managerY
MATCH (teamMember:Person)-[:REPORTS_TO]->(managerY)
RETURN
  managerY.Name AS Manager_Name,
  teamMember.Name AS Team_Member_Name
ORDER BY Team_Member_Name
```

## dashboard_q012: Members working on a study's ongoing/planned deliveries and other active workload

```cypher
MATCH (s:Study {Name: "{{study_name}}"})-[:HAS_DELIVERY]->(d:Delivery)
WHERE NOT toUpper(d.DID_Status) IN ['COMPLETED', 'CANCELLED', 'TERMINATED']
MATCH (p:Person)-[w:WORKS_ON]->(d)
WITH p, d, coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0) AS TaskNum_TargetStudy
OPTIONAL MATCH (p)-[w2:WORKS_ON]->(d2:Delivery)
WHERE d2.Study <> "{{study_name}}" AND NOT toUpper(d2.DID_Status) IN ['COMPLETED', 'CANCELLED', 'TERMINATED']
WITH p.Name AS PersonName,
     collect(DISTINCT {Delivery: d.Name, TaskNum: TaskNum_TargetStudy}) AS TargetStudy_Deliveries,
     collect(DISTINCT {Delivery: d2.Name, TaskNum: coalesce(toFloat(w2.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w2.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w2.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w2.esub_Data_Num_Total), 0.0)}) AS Other_Deliveries
RETURN PersonName, TargetStudy_Deliveries, Other_Deliveries
ORDER BY PersonName
```

## dashboard_q013: Task and hour contributions by TA Lead for one delivery

```cypher
CALL {
  MATCH (taLead:Person)
  WHERE taLead.TA_Lead IS NOT NULL AND taLead.TA_Lead <> ''
  MATCH (person:Person)-[:REPORTS_TO*1..]->(taLead)
  MATCH (person)-[w:WORKS_ON]->(d:Delivery {Name: "{{delivery_name}}"})
  WITH taLead.Name AS TA_Lead_Task, SUM(coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0)) AS Total_Tasks
  RETURN TA_Lead_Task, Total_Tasks
}
CALL {
  MATCH (taLead:Person)
  WHERE taLead.TA_Lead IS NOT NULL AND taLead.TA_Lead <> ''
  MATCH (person:Person)-[:REPORTS_TO*1..]->(taLead)
  MATCH (person)-[t:TIME_ON]->(dm:DIDN_Month)-[:BELONGS_TO]->(d:Delivery {Name: "{{delivery_name}}"})
  WITH taLead.Name AS TA_Lead_Hour, COLLECT(t.Hour) AS hourList
  RETURN TA_Lead_Hour, toInteger(SUM(REDUCE(hourSum = 0, h IN hourList | hourSum + h))) AS Total_Hours
}
WITH *
RETURN
  COALESCE(TA_Lead_Task, TA_Lead_Hour) AS TA_Lead,
  COALESCE(Total_Tasks, 0) AS Total_Tasks,
  COALESCE(Total_Hours, 0) AS Total_Hours,
  CASE WHEN COALESCE(Total_Tasks, 0) <> 0 THEN round(COALESCE(Total_Hours, 0) * 1.0 / COALESCE(Total_Tasks, 0), 2) ELSE NULL END AS Time_Per_Task
ORDER BY Total_Hours DESC
```

## dashboard_q014: Task and hour contributions by Site and Year for completed deliveries

```cypher
CALL {
  MATCH (p1:Person)-[:FROM_SITE]->(site:Site)
  MATCH (p1)-[w:WORKS_ON]->(d1:Delivery)
  WHERE d1.DID_Status = "Completed"
  RETURN site.Name AS Site, d1.Year AS Year, SUM(coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0)) AS Total_Tasks
}
WITH collect({Site: Site, Year: Year, Total_Tasks: Total_Tasks}) AS taskResults
CALL {
  MATCH (p2:Person)-[:FROM_SITE]->(site:Site)
  MATCH (p2)-[t:TIME_ON]->(dm:DIDN_Month)-[:BELONGS_TO]->(d2:Delivery)
  WHERE d2.DID_Status = "Completed"
  RETURN site.Name AS Site, dm.Year AS Year, toInteger(SUM(t.Hour)) AS Total_Hours
}
WITH taskResults, collect({Site: Site, Year: Year, Total_Hours: Total_Hours}) AS hourResults
WITH taskResults, hourResults,
     [x IN taskResults | {Site: x.Site, Year: x.Year}] + [y IN hourResults | {Site: y.Site, Year: y.Year}] AS allKeys
UNWIND allKeys AS key
WITH DISTINCT key.Site AS Site, key.Year AS Year, taskResults, hourResults
WITH Site, Year,
     [x IN taskResults WHERE x.Site = Site AND x.Year = Year | x.Total_Tasks][0] AS Total_Tasks,
     [y IN hourResults WHERE y.Site = Site AND y.Year = Year | y.Total_Hours][0] AS Total_Hours
RETURN Site, Year,
       COALESCE(Total_Tasks, 0) AS Total_Tasks,
       COALESCE(Total_Hours, 0) AS Total_Hours,
       CASE WHEN COALESCE(Total_Tasks, 0) <> 0 THEN round(COALESCE(Total_Hours, 0) * 1.0 / COALESCE(Total_Tasks, 0), 2) ELSE NULL END AS Time_Per_Task
ORDER BY Site, Year
```

## dashboard_q015: Task and hour contributions by TA Lead for completed deliveries

```cypher
CALL {
  MATCH (taLead1:Person)
  WHERE taLead1.TA_Lead IS NOT NULL AND taLead1.TA_Lead <> ''
  MATCH (person1:Person)-[:REPORTS_TO*1..]->(taLead1)
  MATCH (person1)-[w:WORKS_ON]->(d1:Delivery)
  WHERE d1.DID_Status = "Completed"
  WITH taLead1.Name AS TA_Lead, SUM(coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0)) AS Total_Tasks
  RETURN TA_Lead, Total_Tasks
}
WITH collect({TA_Lead: TA_Lead, Total_Tasks: Total_Tasks}) AS taskResults
CALL {
  MATCH (taLead2:Person)
  WHERE taLead2.TA_Lead IS NOT NULL AND taLead2.TA_Lead <> ''
  MATCH (person2:Person)-[:REPORTS_TO*1..]->(taLead2)
  MATCH (person2)-[t:TIME_ON]->(dm:DIDN_Month)-[:BELONGS_TO]->(d2:Delivery)
  WHERE d2.DID_Status = "Completed"
  WITH taLead2.Name AS TA_Lead, toInteger(SUM(t.Hour)) AS Total_Hours
  RETURN TA_Lead, Total_Hours
}
WITH taskResults, collect({TA_Lead: TA_Lead, Total_Hours: Total_Hours}) AS hourResults
WITH taskResults, hourResults,
     [x IN taskResults | x.TA_Lead] + [y IN hourResults | y.TA_Lead] AS allLeads
UNWIND allLeads AS TA_Lead
WITH DISTINCT TA_Lead, taskResults, hourResults
WITH TA_Lead,
     [x IN taskResults WHERE x.TA_Lead = TA_Lead | x.Total_Tasks][0] AS Total_Tasks,
     [y IN hourResults WHERE y.TA_Lead = TA_Lead | y.Total_Hours][0] AS Total_Hours
RETURN
  TA_Lead,
  COALESCE(Total_Tasks, 0) AS Total_Tasks,
  COALESCE(Total_Hours, 0) AS Total_Hours,
  CASE WHEN COALESCE(Total_Tasks, 0) <> 0 THEN round(COALESCE(Total_Hours, 0) * 1.0 / COALESCE(Total_Tasks, 0), 2) ELSE NULL END AS Time_Per_Task
ORDER BY Total_Hours DESC
```

## dashboard_q016: Task and hour contributions by Group Lead under a TA Lead for completed deliveries

```cypher
CALL {
  MATCH (taLead:Person)
  WHERE taLead.Name = "{{ta_lead_name}}"
  MATCH (person1:Person)-[:REPORTS_TO*1..]->(taLead)
  MATCH (gl1:Person)<-[:REPORTS_TO*1..]-(person1)
  WHERE gl1.Group_Lead IS NOT NULL AND gl1.Group_Lead <> ''
  MATCH (person1)-[w:WORKS_ON]->(d1:Delivery)
  WHERE d1.DID_Status = "Completed"
  WITH gl1.Name AS GL_Lead, SUM(coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0)) AS Total_Tasks
  RETURN GL_Lead, Total_Tasks
}
WITH collect({GL_Lead: GL_Lead, Total_Tasks: Total_Tasks}) AS taskResults
CALL {
  MATCH (taLead:Person)
  WHERE taLead.Name = "{{ta_lead_name}}"
  MATCH (person2:Person)-[:REPORTS_TO*1..]->(taLead)
  MATCH (gl2:Person)<-[:REPORTS_TO*1..]-(person2)
  WHERE gl2.Group_Lead IS NOT NULL AND gl2.Group_Lead <> ''
  MATCH (person2)-[t:TIME_ON]->(dm:DIDN_Month)-[:BELONGS_TO]->(d2:Delivery)
  WHERE d2.DID_Status = "Completed"
  WITH gl2.Name AS GL_Lead, toInteger(SUM(t.Hour)) AS Total_Hours
  RETURN GL_Lead, Total_Hours
}
WITH taskResults, collect({GL_Lead: GL_Lead, Total_Hours: Total_Hours}) AS hourResults
WITH taskResults, hourResults,
     [x IN taskResults | x.GL_Lead] + [y IN hourResults | y.GL_Lead] AS allLeads
UNWIND allLeads AS GL_Lead
WITH DISTINCT GL_Lead, taskResults, hourResults
WITH GL_Lead,
     [x IN taskResults WHERE x.GL_Lead = GL_Lead | x.Total_Tasks][0] AS Total_Tasks,
     [y IN hourResults WHERE y.GL_Lead = GL_Lead | y.Total_Hours][0] AS Total_Hours
RETURN
  GL_Lead AS Group_Lead,
  COALESCE(Total_Tasks, 0) AS Total_Tasks,
  COALESCE(Total_Hours, 0) AS Total_Hours,
  CASE WHEN COALESCE(Total_Tasks, 0) <> 0 THEN round(COALESCE(Total_Hours, 0) * 1.0 / COALESCE(Total_Tasks, 0), 2) ELSE NULL END AS Time_Per_Task
ORDER BY Total_Hours DESC
```
