// ---- Fact_Orders
let
    Source = Csv.Document(File.Contents(DataFolder & "\Fact_Orders.csv"), [Delimiter=",", Columns=8, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers", {{"order_id", Int64.Type}, {"order_date", type date}, {"customer_id", type text}, {"product_id", type text}, {"quantity", Int64.Type}, {"discount_pct", type number}, {"net_amount", type number}, {"returned", Int64.Type}}, "en-US")
in
    #"Changed Type"

// ---- Dim_Customers
let
    Source = Csv.Document(File.Contents(DataFolder & "\Dim_Customers.csv"), [Delimiter=",", Columns=6, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers", {{"customer_id", type text}, {"city", type text}, {"gender", type text}, {"age", Int64.Type}, {"signup_date", type date}, {"age_Group", type text}}, "en-US")
in
    #"Changed Type"

// ---- Dim_Products
let
    Source = Csv.Document(File.Contents(DataFolder & "\Dim_Products.csv"), [Delimiter=",", Columns=4, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers", {{"product_id", type text}, {"brand", type text}, {"category", type text}, {"mrp", Int64.Type}}, "en-US")
in
    #"Changed Type"

// ---- Dim_Date
let
    Source = Csv.Document(File.Contents(DataFolder & "\Dim_Date.csv"), [Delimiter=",", Columns=11, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),
    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),
    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers", {{"Date", type date}, {"Year", Int64.Type}, {"Quarter_Num", Int64.Type}, {"Quarter", type text}, {"Month_Num", Int64.Type}, {"Month", type text}, {"Year_Month", type text}, {"Week_Of_Year", Int64.Type}, {"Day_Of_Week_Num", Int64.Type}, {"Day_Name", type text}, {"Is_Weekend", Int64.Type}}, "en-US")
in
    #"Changed Type"