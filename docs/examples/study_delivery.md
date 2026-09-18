# Study and Delivery Examples

> Use these as few-shot examples for DID Agent Text-to-Cypher. Replace parameter placeholders before execution.

## q040: Please tell me which deliveries have been completed for a specific study, and what the timelines are.

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"study_name": "C1071003"
}
```

**Cypher**

```cypher
MATCH (s:Study {Name: {{study_name:Study name}})-[:HAS_DELIVERY]->(d:Delivery)
WHERE d.DID_Status = 'Completed'
RETURN d.DID, d.Planned_Delivery_Date, d.Actual_Delivery_Date, 
       duration.between(d.Planned_Delivery_Date, d.Actual_Delivery_Date).days as Timeline_Difference_Days
ORDER BY d.Actual_Delivery_Date DESC
```

## q043: The timeline of the studies I have participated in.

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"person_name": "PERSON_NAME"
}
```

**Cypher**

```cypher
MATCH (p:Person {Name: {{person_name:Person name}})-[:WORKS_ON]->(d:Delivery)
MATCH (s)-[:HAS_DELIVERY]->(d:Delivery)
WITH s, 
     MIN(d.Planned_Delivery_Date) as Study_Start_Date,
     MAX(d.Planned_Delivery_Date) as Study_End_Date,
     COLLECT({DID: d.DID, Planned_Date: d.Planned_Delivery_Date}) as Deliveries
UNWIND Deliveries as delivery
RETURN s.Name as Study_Name,
       delivery.DID as DID_Name,
       delivery.Planned_Date as Planned_Delivery_Date,
       Study_Start_Date,
       Study_End_Date
ORDER BY Study_Start_Date, delivery.Planned_Date
```

## q066: Please summarize the number of DIDs, tasks including {{task_type:Task type}} for specific study {{study:Study name}}

**Business intent**  
Auto-parameterized query to summarize DIDs and tasks for a specific study

**Parameters**

```json
{
"study": "C3671053",
      "task_type": "SDTM,ADaM,TLF"
}
```

**Cypher**

```cypher
WITH '{{study:Study name}}' AS specificStudyName
MATCH (study:Study {Name: specificStudyName})-[:HAS_DELIVERY]->(delivery:Delivery)
WHERE delivery.DID_Status = 'Completed'
OPTIONAL MATCH (:Person)-[w:WORKS_ON]->(delivery)
RETURN study.Name AS Specific_Study_Name,
       count(DISTINCT delivery.DID) AS Total_DIDs,
       sum(coalesce(toFloat(w.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(w.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(w.STD_Task_Num_Total), 0.0) + coalesce(toFloat(w.esub_Data_Num_Total), 0.0)) AS Total_Tasks,
       sum(coalesce(toFloat(w.CSR_SDTM_Num_Total), 0.0)) AS Total_SDTM_Tasks,
       sum(coalesce(toFloat(w.CSR_ADaM_Num_Total), 0.0)) AS Total_ADaM_Tasks,
       sum(coalesce(toFloat(w.CSR_TLF_Num_Total), 0.0)) AS Total_TLF_Tasks
ORDER BY Specific_Study_Name
```

## q067: Please summarize tasks including {{task_type:Task type}} completed by each person for specific study {{study:Study name}} and DID {{delivery_id:Delivery ID}}

**Business intent**  
Auto-parameterized query to summarize person-level tasks for a specific study DID

**Parameters**

```json
{
"study": "C3671053",
      "delivery_id": "C3671053_2",
      "task_type": "SDTM,ADaM,TLF"
}
```

**Cypher**

```cypher
WITH '{{study:Study name}}' AS specificStudyName, '{{did:DID}}' AS specificDID
MATCH (study:Study {Name: specificStudyName})-[:HAS_DELIVERY]->(delivery:Delivery {Name: specificDID})
WHERE delivery.DID_Status = 'Completed'
MATCH (person:Person)-[workOn:WORKS_ON]->(delivery)
RETURN person.Name AS Person_Name,
       study.Name AS Study_Name,
       delivery.Name AS Target_DID,
       coalesce(toFloat(workOn.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(workOn.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(workOn.STD_Task_Num_Total), 0.0) + coalesce(toFloat(workOn.esub_Data_Num_Total), 0.0) AS Total_Completed_Tasks_In_DID,
       coalesce(toFloat(workOn.CSR_SDTM_Num_Total), 0.0) AS SDTM_Tasks_In_DID,
       coalesce(toFloat(workOn.CSR_ADaM_Num_Total), 0.0) AS ADaM_Tasks_In_DID,
       coalesce(toFloat(workOn.CSR_TLF_Num_Total), 0.0) AS TLF_Tasks_In_DID
ORDER BY Total_Completed_Tasks_In_DID DESC
```

## q070: Please summarize the time spent on specific study {{study:Study name}} and DID {{delivery_id:Delivery ID}} by all participants

**Business intent**  
Auto-parameterized query to summarize participants' time spent on a specific study DID

**Parameters**

```json
{
"study": "C3671053",
      "delivery_id": "C3671053_1"
}
```

**Cypher**

```cypher
WITH "{{study:Study name}}" AS specificStudyName, "{{delivery_id:Delivery ID}}" AS specificDID MATCH (study:Study {Name: specificStudyName})-[:HAS_DELIVERY]->(delivery:Delivery {Name: specificDID}) MATCH (participant:Person)-[t:TIME_ON]->(didMonth:DIDN_Month)-[:BELONGS_TO]->(delivery)<-[:WORKS_ON]-(participant) RETURN study.Name AS Specific_Study_Name, delivery.Name AS Specific_DID, participant.Name AS Participant_Name, COALESCE(SUM(t.Hour), 0) AS Total_Time_Spent_Hours, collect(DISTINCT {Year: didMonth.Year, Month: didMonth.Month, Hours_Spent: t.Hour}) AS Monthly_Time_Distribution ORDER BY Total_Time_Spent_Hours DESC;
```

## q071: Please help me summarize the number of tasks of all participants in specific DID {{delivery_id:Delivery ID}} during {{start_month:Month}} {{start_year:Year}} to {{end_month:Month}} {{end_year:Year}}

**Business intent**  
Auto-parameterized query to summarize participants' tasks in a specific DID and time period

**Parameters**

```json
{
"delivery_id": "C3671053_2",
      "start_year": 2025,
      "start_month": 1,
      "end_year": 2025,
      "end_month": 9
}
```

**Cypher**

```cypher
WITH '{{delivery_id:Delivery ID}}' AS specificDID,
     date({year: {{start_year:Year}}, month: {{start_month:Month}}, day: 1}) AS timePeriodStart,
     date({year: {{end_year:Year}}, month: {{end_month:Month}}, day: 1}) AS timePeriodEnd
MATCH (delivery:Delivery {Name: specificDID})
MATCH (participant:Person)-[workOn:WORKS_ON]->(delivery)
OPTIONAL MATCH (participant)-[timeOn:TIME_ON]->(didMonth:DIDN_Month)-[:BELONGS_TO]->(delivery)
WHERE didMonth.Year * 12 + didMonth.Month >= timePeriodStart.year * 12 + timePeriodStart.month
  AND didMonth.Year * 12 + didMonth.Month <= timePeriodEnd.year * 12 + timePeriodEnd.month
  AND delivery.DID_Status IN ['Ongoing', 'Completed', 'Planned']
WITH timePeriodStart, timePeriodEnd, delivery, participant, workOn
ORDER BY participant.Name
RETURN timePeriodStart, timePeriodEnd,
       delivery.Name AS Target_DID,
       delivery.Study AS Associated_Study_Name,
       participant.Name AS Participant_Name,
       coalesce(toFloat(workOn.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(workOn.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(workOn.STD_Task_Num_Total), 0.0) + coalesce(toFloat(workOn.esub_Data_Num_Total), 0.0) AS Total_Tasks_In_Period,
       coalesce(toFloat(workOn.CSR_SDTM_Num_Total), 0.0) AS SDTM_Tasks_In_Period,
       coalesce(toFloat(workOn.CSR_ADaM_Num_Total), 0.0) AS ADaM_Tasks_In_Period,
       coalesce(toFloat(workOn.CSR_TLF_Num_Total), 0.0) AS TLF_Tasks_In_Period
ORDER BY Total_Tasks_In_Period DESC
```

## q072: Please summarize the details of {{keyword:Delivery keyword}} deliveries for this month

**Business intent**  
Auto-parameterized query to summarize deliveries with specific keyword for the current month

**Parameters**

```json
{
"keyword": "CSR"
}
```

**Cypher**

```cypher
WITH date() AS today, (date().year * 12 + date().month) AS targetCurrentMonthCode, "{{keyword:Delivery keyword}}" AS targetKeyword MATCH (delivery:Delivery) MATCH (delivery)<-[:HAS_DELIVERY]->(study:Study) MATCH (study)-[:HAS_DETAIL]->(studyInfo:Study_Info) WHERE (delivery.Delivery_Content CONTAINS targetKeyword OR delivery.Reporting_Event CONTAINS targetKeyword OR delivery.Reporting_Detail CONTAINS targetKeyword) AND (delivery.Year * 12 + delivery.Month) = targetCurrentMonthCode AND delivery.DID_Status IN ["Ongoing", "Completed", "Planned"] AND delivery.Year = date().year AND delivery.Month = date().month AND delivery.Year IS NOT NULL AND delivery.Month IS NOT NULL RETURN COUNT(DISTINCT delivery.DID) AS Total_Target_Deliveries_This_Month, collect(DISTINCT {DID: delivery.DID, Study_Name: study.Name, Target_Context: CASE WHEN delivery.Delivery_Content CONTAINS targetKeyword THEN "Delivery Content: " + delivery.Delivery_Content WHEN delivery.Reporting_Event CONTAINS targetKeyword THEN "Reporting Event: " + delivery.Reporting_Event ELSE "Reporting Detail: " + delivery.Reporting_Detail END, Delivery_Status: delivery.DID_Status}) AS Target_Delivery_Details;
```

## q073: Please summarize the number of {{task_type:Task type}} for each DID and study

**Business intent**  
Auto-parameterized query to summarize SDTM/ADaM/TLF counts per DID and study

**Parameters**

```json
{
"task_type": "SDTM,ADaM,TLF"
}
```

**Cypher**

```cypher
MATCH (study:Study)-[:HAS_DELIVERY]->(delivery:Delivery)
WHERE delivery.CSR_SDTM_Num IS NOT NULL OR delivery.CSR_ADaM_Num IS NOT NULL OR delivery.CSR_TLF_Num IS NOT NULL
RETURN study.Name AS Study_Name,
       delivery.DID AS DID,
       delivery.DID_Status AS Delivery_Status,
       coalesce(toFloat(delivery.CSR_SDTM_Num), 0.0) AS Total_SDTM,
       coalesce(toFloat(delivery.CSR_ADaM_Num), 0.0) AS Total_ADaM,
       coalesce(toFloat(delivery.CSR_TLF_Num), 0.0) AS Total_TLF,
       coalesce(toFloat(delivery.CSR_SDTM_Num), 0.0) + coalesce(toFloat(delivery.CSR_ADaM_Num), 0.0) + coalesce(toFloat(delivery.CSR_TLF_Num), 0.0) AS Total_Tasks_Per_DID
ORDER BY Study_Name, DID
```

## q077: What is the {{date_type:Date type}} for each DID and Study

**Business intent**  
Auto-parameterized query to get specific date type (e.g., Actual_Delivery_Date) per DID and study

**Parameters**

```json
{
"date_type": "Actual_Delivery_Date"
}
```

**Cypher**

```cypher
MATCH (study:Study)-[:HAS_DELIVERY]->(delivery:Delivery) WHERE delivery.DID_Status IN ["Completed", "Ongoing", "Planned"] AND delivery.{{date_type:Date type}} IS NOT NULL RETURN study.Name AS Study_Name, delivery.DID AS DID, delivery.DID_Status AS Delivery_Status, delivery.{{date_type:Date type}} AS {{date_type:Date type}} ORDER BY Study_Name, DID;
```

## q078: Please summarize the number of tasks for specific DID {{delivery_id:Delivery ID}} and calculate the percentage of work for each participant

**Business intent**  
Auto-parameterized query to calculate participant work percentage for a specific DID

**Parameters**

```json
{
"delivery_id": "C3671053_2"
}
```

**Cypher**

```cypher
WITH '{{delivery_id:Delivery ID}}' AS specificDID
MATCH (delivery:Delivery {DID: specificDID})
MATCH (participant:Person)-[work:WORKS_ON]->(delivery)
WITH delivery, participant,
     coalesce(toFloat(work.CSR_Task_Num_Total), 0.0) + coalesce(toFloat(work.SDA_Task_Num_Total), 0.0) + coalesce(toFloat(work.STD_Task_Num_Total), 0.0) + coalesce(toFloat(work.esub_Data_Num_Total), 0.0) AS participantTaskCount
WITH delivery,
     collect({Participant_Name: participant.Name, Participant_Tasks: participantTaskCount}) AS participantTasks,
     sum(participantTaskCount) AS totalTasksForDID
UNWIND participantTasks AS participantTask
RETURN delivery.Study AS Study_Name,
       delivery.DID AS Target_DID,
       delivery.DID_Status AS Delivery_Status,
       participantTask.Participant_Name AS Participant_Name,
       participantTask.Participant_Tasks AS Tasks_For_Participant,
       totalTasksForDID AS Total_Tasks_For_DID,
       CASE WHEN totalTasksForDID = 0 THEN 0.0 ELSE round(toFloat(participantTask.Participant_Tasks) / totalTasksForDID * 100, 2) END AS Work_Percentage
ORDER BY Work_Percentage DESC
```

## q096: Quickly display the DIDs for a specific project.

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"study_name": "C1071003"
}
```

**Cypher**

```cypher
MATCH (s:Study {Name: {{study_name:Study name}})-[:HAS_DELIVERY]->(d:Delivery)
RETURN d.DID, d.DID_Status, d.Planned_Delivery_Date, d.Actual_Delivery_Date
ORDER BY d.Planned_Delivery_Date DESC
```

## q104: Quickly display the DIDs for a specific project.

**Business intent**  
Auto-parameterized query for question

**Parameters**

```json
{
"study_name": "C1071003"
}
```

**Cypher**

```cypher
MATCH (s:Study {Name: {{study_name:Study name}})-[:HAS_DELIVERY]->(d:Delivery)
RETURN d.DID, d.DID_Status, d.Planned_Delivery_Date, d.Actual_Delivery_Date
ORDER BY d.Planned_Delivery_Date
```

## q106: list programmers involved in the study C2321001 and their respective domains of responsibility.

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
MATCH (s:Study {Name: '{{study:Study name}}'})-[:HAS_DELIVERY]->(d:Delivery)<-[:WORKS_ON]-(p:Person)
OPTIONAL MATCH (d)-[:HAS_SDTM]->(sdtm:SDTM)
OPTIONAL MATCH (d)-[:HAS_ADAM]->(adam:ADaM)
OPTIONAL MATCH (d)-[:HAS_TLF]->(tlf:TLF)
RETURN DISTINCT p.Name AS Programmer_Name,
       COLLECT(DISTINCT sdtm.Name) AS SDTM_Domains,
       COLLECT(DISTINCT adam.Name) AS ADaM_Domains,
       COLLECT(DISTINCT tlf.Name) AS TLF_Domains
```

## q107: find which DIDs are available for filling in the daily survey

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

## q108: find all deliveries that occurred on a specified date.

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"deliveryDate": "2024-04-02"
}
```

**Cypher**

```cypher
MATCH (d:Delivery)
WHERE d.Actual_Delivery_Date = date({deliveryDate})
RETURN d.Name AS Eligible_DIDs
```

## q113: find the SDSL for a given study.

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
MATCH (n:Study {Name: {studyName}}) 
RETURN n.SDSL AS SDSL
```

## q120: retrieve the list of people who participated in the delivery of C2321001.

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
MATCH (s:Study {Name: {studyName}})-[:HAS_DELIVERY]->(d:Delivery)<-[:WORKS_ON]-(p:Person)
RETURN DISTINCT p.Name AS Participant_Name
```

## q121: identify the main contributor to a specified submission

**Business intent**  
Auto-parameterized query for question.

**Parameters**

```json
{
"submissionName": "B176e NDA Submission"
}
```

**Cypher**

```cypher
MATCH (p:Person)-[:LEADS_SUBMISSION]->(s:Submission {Name: {submissionName}})
RETURN p.Name AS Main_Contributor
```
