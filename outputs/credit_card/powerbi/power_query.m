// ---- Fact_Credit_Card
let
    Source = Csv.Document(File.Contents(DataFolder & "\Fact_Credit_Card.csv"), [Delimiter=",", Columns=22, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers", {{"Client_Num", Int64.Type}, {"Card_Category", type text}, {"Annual_Fees", Int64.Type}, {"Activation_30_Days", Int64.Type}, {"Customer_Acq_Cost", Int64.Type}, {"Week_Start_Date", type date}, {"Week_Num", type text}, {"Qtr", type text}, {"current_year", Int64.Type}, {"Credit_Limit", type number}, {"Total_Revolving_Bal", Int64.Type}, {"Total_Trans_Amt", Int64.Type}, {"Total_Trans_Vol", Int64.Type}, {"Avg_Utilization_Ratio", type number}, {"Use_Chip", type text}, {"Exp_Type", type text}, {"Interest_Earned", type number}, {"Delinquent_Acc", Int64.Type}, {"Source_File", type text}, {"Revenue", type number}, {"Net_Revenue", type number}, {"Credit_Limit_Band", type text}}, "en-US")
in
    #"Changed Type"

// ---- Dim_Customer
let
    Source = Csv.Document(File.Contents(DataFolder & "\Dim_Customer.csv"), [Delimiter=",", Columns=18, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers", {{"Client_Num", Int64.Type}, {"Customer_Age", Int64.Type}, {"Gender", type text}, {"Dependent_Count", Int64.Type}, {"Education_Level", type text}, {"Marital_Status", type text}, {"state_cd", type text}, {"Zipcode", Int64.Type}, {"Car_Owner", type text}, {"House_Owner", type text}, {"Personal_loan", type text}, {"contact", type text}, {"Customer_Job", type text}, {"Income", Int64.Type}, {"Cust_Satisfaction_Score", Int64.Type}, {"Source_File", type text}, {"Customer_Age_Group", type text}, {"Income_Band", type text}}, "en-US")
in
    #"Changed Type"

// ---- Dim_Date
let
    Source = Csv.Document(File.Contents(DataFolder & "\Dim_Date.csv"), [Delimiter=",", Columns=11, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers", {{"Date", type date}, {"Year", Int64.Type}, {"Quarter_Num", Int64.Type}, {"Quarter", type text}, {"Month_Num", Int64.Type}, {"Month", type text}, {"Year_Month", type text}, {"Week_Of_Year", Int64.Type}, {"Day_Of_Week_Num", Int64.Type}, {"Day_Name", type text}, {"Is_Weekend", Int64.Type}}, "en-US")
in
    #"Changed Type"