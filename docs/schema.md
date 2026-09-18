# Neo4j Database Schema for DID Agent

This schema describes the DID Neo4j graph used by the DID Agent for Text-to-Cypher generation.

## Nodes

### Study

Properties:

- `Name`
- `SDSL`
- `SDSA_US_PoC`
- `SDSA_China_PoC`
- `SDSA_India_PoC`
- `FSP_Ephicacy_PoC`
- `FSP_Fortrea_PoC`
- `FSP_TCS_PoC`
- `FSP_Other_PoC`
- `IPort_Study`
- `SharePoint_ID`
- `Request_Type`

### Delivery

Properties:

- `Name`
- `DID`
- `DID_Status`
- `Work_Type`
- `Deliverable_Detail`
- `Reporting_Event`
- `Reporting_Detail`
- `Draft_or_Final`
- `Planned_Delivery_Date`
- `SDSL`
- `Actual_Delivery_Date`
- `Reporting_Path`
- `Quality`
- `Reporting_System`
- `Delivery_Content`
- `Study`
- `CSR_SDTM_Num`
- `CSR_ADaM_Num`
- `CSR_TLF_Num`
- `CSR_Task_Num`
- `SDA_Task_Num`
- `STD_Task_Num`
- `STD_Category`
- `esub_Task_Data_Num`
- `esub_Task_Xpts_Num`
- `esub_Task_Acrf_Num`
- `esub_Task_AcrfReview_Num`
- `esub_Task_Define_Num`
- `esub_Task_Drg_Num`
- `esub_Task_DrgQms_Num`
- `esub_Task_SasProgram_Num`
- `Year`
- `Month`
- `ID_in_Portfolio_Milestone_list1`
- `ID_in_Portfolio_Milestone_list2`
- `ID_in_Portfolio_Milestone_list3`
- `ID_in_Portfolio_Milestone_list4`
- `ID_in_Portfolio_Milestone_list5`
- `Urgent_Request`
- `Resource_Distribution_Type`
- `Resource_Distribution`
- `Linked_DID`
- `ReDelivery`
- `Reason_for_ReDelivery`
- `Submission_Work`

### Study_Info

Properties:

- `Name`
- `Plan_Status`
- `Plan_Phase`
- `Study_Type`
- `FAP`
- `FSFV`
- `LSLV`
- `PCD`
- `DBR`
- `Short_Name`
- `Business_Rationale`
- `Generic_Name`
- `Trade_Name`
- `Candidate_Code`
- `Compound_Name`
- `Study_Number_Reg`
- `Registry_Status`
- `Subject_Type`
- `Planned_Countries`
- `Study_Design`
- `Study_Description`
- `Program_Code`
- `Compound_Number`
- `Project_Code`
- `Project_Name`
- `TA`
- `Indications`

### Site

Properties:

- `Name`
- `Site_Category`

### Unblind

Properties:

- `Unblind_Programming_Support`

### Person

Properties:

- `Name`
- `Manager`
- `Group_Lead`
- `TA_Lead`
- `Email`
- `NTID`
- `Status`
- `Onboard_Date`
- `Offboard_Date`
- `Offboard_Year`
- `Service_Year`
- `Team_Lead_Name`
- `Group_Lead_Name`
- `TA_Lead_Name`

### DID0

Properties:

- `Name`
- `DID`

### Study_Month

Properties:

- `Name`
- `Study`
- `Year`
- `Month`
- `DID0_Hour`
- `DIDN_Hour`

### DID0_Month

Properties:

- `Name`
- `DID`
- `DID_Type`
- `Year`
- `Month`
- `Hour`

### DIDN_Month

Properties:

- `Name`
- `DID`
- `DID_Type`
- `Year`
- `Month`
- `Hour`

### SDTM

Properties:

- `Name`
- `SDTM_Category`
- `Type`

### ADaM

Properties:

- `Name`
- `ADaM_Category`
- `Type`

### TLF

Properties:

- `Name`
- `TLF_Category`
- `TLF_Type`
- `Source`

### Submission

Properties:

- `Project_Code`
- `Milestone`
- `Portfolio_ID`
- `Name`
- `Priority_Tier`
- `Submission_Lead`
- `TA`
- `Region`
- `Plan_Finish`

### Task_Force

Properties:

- `BID`
- `BID_Lead`
- `BID_Desc`
- `Start_Date`
- `Planned_Delivery_Date`
- `Actual_Delivery_Date`
- `Delivery_Frequency`
- `Repeated_Delivery`
- `Blue_Sky`
- `Goal_2025_S2`

### BID_0

Properties:

- `BID_0`
- `Title`
- `Initiative_Lead`
- `China_POC`
- `India_POC`
- `BID_0_Desc`
- `Goal_BID0_2025_S2`
- `Goal_BID0_2026_S1`

### BID_Cat

Properties:

- `Category`

## Relationships

### Study-related relationships

```cypher
(Study)-[:HAS_DELIVERY]->(Delivery)
(Study)-[:HAS_DETAIL]->(Study_Info)
(Study)-[:HAS_DID0]->(DID0)
```

### Delivery-related relationships

```cypher
(Delivery)-[:IS_UNBLIND_SUPPORT]->(Unblind)
(Delivery)-[:HAS_SDTM {Generation, QC}]->(SDTM)
(Delivery)-[:HAS_ADAM {Generation, QC}]->(ADaM)
(Delivery)-[:HAS_TLF {Generation, QC, File_Name, TLF_Number}]->(TLF)
(Delivery)-[:SUPPORT_SUBMISSION]->(Submission)
```

### Person-related relationships

```cypher
(Person)-[:WORKS_AS {Role}]->(Study)
(Person)-[:FROM_SITE]->(Site)
(Person)-[:REPORTS_TO]->(Person)
(Person)-[:WORKS_ON {
  CSR_TLF_Num_Total, CSR_TLF_Num_Generation, CSR_TLF_Num_QC,
  CSR_ADaM_Num_Total, CSR_ADaM_Num_Generation, CSR_ADaM_Num_QC,
  CSR_SDTM_Num_Total, CSR_SDTM_Num_Generation, CSR_SDTM_Num_QC,
  CSR_Task_Num_Total, CSR_Task_Num_Generation, CSR_Task_Num_QC,
  SDA_Task_Num_Total, SDA_Task_Num_Generation, SDA_Task_Num_QC,
  STD_Task_Num_Total, STD_Task_Num_Generation, STD_Task_Num_QC,
  esub_Data_Num_Total, esub_Data_Num_Generation, esub_Data_Num_QC,
  esub_Xpts_Num, esub_Acrf_Num, esub_AcrfReview_Num,
  esub_Define_Num, esub_Drg_Num, esub_DrgQms_Num, esub_SasProgram_Num
}]->(Delivery)
(Person)-[:WORKS_ON {Role, Task}]->(Task_Force)
(Person)-[:LEADS_SUBMISSION]->(Submission)
```

### Month and time relationships

```cypher
(Study_Month)-[:BELONGS_TO]->(Study)
(DID0_Month)-[:BELONGS_TO]->(DID0)
(DIDN_Month)-[:BELONGS_TO]->(Delivery)
(DID0_Month)-[:PART_OF]->(Study_Month)
(DIDN_Month)-[:PART_OF]->(Study_Month)
(Person)-[:TIME_ON {Hour, DID_Type}]->(Study_Month)
(Person)-[:TIME_ON {From_Date, To_Date, Hour}]->(DID0_Month)
(Person)-[:TIME_ON {From_Date, To_Date, Hour}]->(DIDN_Month)
```

### BID / Task Force relationships

```cypher
(BID_0)-[:BELONGS_TO]->(BID_Cat)
(Task_Force)-[:BELONGS_TO]->(BID_Cat)
```

## Controlled Values

Normalize user wording only for properties listed in this section. Use the exact value and capitalization shown below.

### `Delivery.DID_Status`

Valid values:

- `Completed`
- `Planned`
- `Ongoing`
- `Cancelled`
- `Overdue`

Interpretation examples:

- "completed deliveries" means `Delivery.DID_Status = "Completed"`.
- "planned deliveries" means `Delivery.DID_Status = "Planned"`.
- "ongoing deliveries" means `Delivery.DID_Status = "Ongoing"`.
- "cancelled deliveries" means `Delivery.DID_Status = "Cancelled"`.
- "overdue deliveries" means `Delivery.DID_Status = "Overdue"`.

### `Delivery.STD_Category`

Valid values:

- `CDARS`
- `Mapping`
- `General`

### `Study_Info.Plan_Status`

Valid values:

- `COMPLETE`
- `CONCEPT`
- `ACTIVE`
- `NA`
- `PROPOSED`
- `TERMINATED`
- `CANCELLED`
- `HOLD`
- `PROPOSED-SNI`
- `PAUSE`

### `Study_Info.Study_Type`

Valid values:

- `INTERVENTIONAL`
- `NON INTERVENTIONAL`

### `Study_Info.Subject_Type`

Valid values:

- `PATIENTS`
- `VOLUNTEERS`
- `NO SUBJECTS`
- `BOTH (PATIENTS AND VOLUNTEERS)`

### `Submission.Milestone`

Valid values:

- `MAA Submission`
- `NDA Submission`
- `CNDA Submission`
- `JNDA Submission`

### `Unblind.Unblind_Programming_Support`

Valid values:

- `TRUE`
- `FALSE`

## Example Values

The following values are examples only and are not exhaustive.

- `Delivery.Reporting_System`: `CDARS`, `SIGMA`
- `Delivery.Reporting_Event`: `Clinical Study Report`, `Basic Results`
- `Delivery.Quality`: `Fit for Purpose`, `Minor Issue`
- `Delivery.Delivery_Content`: `TLFs, ADaM and SDTM`, `Only TLFs`

## Organizational Reference

### TA Lead Reference List

The following `Person.Name` values are defined as TA Leads in the current DID data preparation logic:

- `Bukenya, Twaha`
- `Chen, Gary`
- `Hagendoorn, Michael (L-SGN US)`
- `Hintze, Rebecca E`
- `Iyer, Priya Venkatesan`
- `Pearce, Stuart`
- `Shen, Henry`
- `Smith, Matt`
- `Vacca, John D`
- `Zhang, Liping`


## Common Cypher Patterns

### Flexible person-name matching

```cypher
replace(toUpper(p.Name), " ", "") = replace(toUpper("{{person_name}}"), " ", "")
```

### Completed deliveries

```cypher
d.DID_Status = "Completed"
```

### Ongoing or planned deliveries

```cypher
d.DID_Status IN ["Ongoing", "Planned"]
```

or:

```cypher
NOT toUpper(d.DID_Status) IN ["COMPLETED", "CANCELLED", "TERMINATED"]
```

### Month range filtering

```cypher
(d.Year * 12 + d.Month) >= minMonth
AND (d.Year * 12 + d.Month) <= maxMonth
```

### Group Lead lookup

```cypher
OPTIONAL MATCH (person)-[:REPORTS_TO*1..]->(groupLead:Person)
WHERE groupLead.Group_Lead = "Y"
```

### TA Lead lookup

```cypher
OPTIONAL MATCH (person)-[:REPORTS_TO*1..]->(taLead:Person)
WHERE taLead.TA_Lead = "Y"
```

### Person task totals on WORKS_ON

```cypher
coalesce(toFloat(w.CSR_Task_Num_Total), 0.0)
+ coalesce(toFloat(w.SDA_Task_Num_Total), 0.0)
+ coalesce(toFloat(w.STD_Task_Num_Total), 0.0)
+ coalesce(toFloat(w.esub_Data_Num_Total), 0.0)
```

Do not use `Task_Num_Total`. Other `esub_*_Num` fields on `WORKS_ON` are specific eSub artifacts, not the general task total.

## Important Notes

- Use only the labels, relationships, and properties defined here.
- The ADaM node label is `ADaM`, not `ADAM`. The relationship type is still `HAS_ADAM`.
- `Site.Site_Category`, `SDTM.SDTM_Category`, `ADaM.ADaM_Category`, `TLF.TLF_Category`, and `TLF.TLF_Type` are the current property names.
- `(Person)-[:WORKS_ON]->(Delivery)` and `(Person)-[:WORKS_ON]->(Task_Force)` are different payloads.
- Do not invent labels, relationships, or properties.
- Use read-only Cypher for the Agent.
- Do not use write operations such as `CREATE`, `MERGE`, `DELETE`, `SET`, `REMOVE`, or `DROP`.
- Normalize user wording only for properties listed under **Controlled Values**.
- Values under **Example Values** are illustrative and not exhaustive.
