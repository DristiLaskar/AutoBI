# Audit of the original "Credit Card Financial Dashboard"

Scope: `README.md`, the four CSVs, the two screenshots and the internals of `credit_card_report.pbix`
(report layout extracted from the .pbix; the compressed data model itself cannot be read outside Power BI Desktop).
Every number below was recomputed from the shipped CSVs with pandas.

## A. Numbers that cannot be trusted

| # | Severity | Finding | Evidence |
|---|----------|---------|----------|
| 1 | **Critical** | **Dashboard totals are ~1.96x the real data.** Every additive measure on the screenshots is inflated by the same factor. | Screenshot vs CSV: Transaction amount 89.04M vs **45.53M** (1.96x); Interest 15.69M vs **7.98M** (1.97x); Transaction count ≈1.31M vs **667,234** (1.96x). Consistent with ~20k rows loaded instead of 10,293 (the README itself says "20,086 accounts"; the CSVs hold **10,293** unique clients). |
| 2 | **Critical** | **"Revenue" is defined wrongly.** The dashboard's Revenue (110.63M) = spend + interest + annual fees. Customer *spend* (`Total_Trans_Amt`) is the cardholders' purchases, not the bank's income. | Real income = interest + fees = **10.98M**. The old headline number overstates revenue ~10x (5x even after fixing #1). v2 defines `Revenue = Interest_Earned + Annual_Fees` (editable in `configs/credit_card.json`). |
| 3 | **Critical** | **README KPIs match neither the CSVs nor the screenshots.** | README: Interest $2.4M, Fees $1.4M, Trans $17.5M, 20,086 accounts, 17,043 active, **3,043 delinquent**. CSVs: Interest 7.98M, Fees 3.00M, Trans 45.5M, 10,293 accounts, 5,914 activated, **624 delinquent**. |
| 4 | High | **The job table shows the same revenue for every job.** Revenue 11,06,30,820.46 and interest 1,56,86,764.46 repeat on every row (Blue-collar, Businessman, Govt ...). The customer table does not filter the transaction table (missing/inactive relationship or cross-filter problem). | Screenshot 2, table "customer_job". |
| 5 | High | **Wrong aggregations.** Three treemaps use `Sum(client_num)` - summing an ID column (meaningless). "Income 1bn" is `Sum(income)` - summing a per-customer attribute. "Revenue by Dependent" plots `Sum(dependent_count)`. | Extracted from the .pbix report layout. |
| 6 | High | **Chart titles contradict what is plotted.** Five charts are all titled "Reveneu by Expenditure type"; the education and job charts actually plot `CountNonNull(education_level)` / `CountNonNull(customer_job)`. "Revenue by Income group / Age group" plot customer *counts*, not revenue. | Layout vs screenshot. |
| 7 | High | **"Top 5 States" is not the top 5.** It shows TX, WA, UT, VA, SC (each is ≤0.3% of customers). The real top five by customers are CA 2,516, TX 2,439, NY 2,305, FL 1,740, NJ 732. | Screenshot 2 vs `value_counts()`. |

## B. Pipeline / reproducibility errors

| # | Severity | Finding | Evidence |
|---|----------|---------|----------|
| 8 | **Critical** | **Schema drift between the two transaction files.** `credit_card.csv` has `Total_Trans_Vol`; `cc_add.csv` has `Total_Trans_Ct`. A Power Query *Append* matches on column names, so it creates two half-empty columns: 185 rows with `Total_Trans_Vol = null` and 10,108 rows with `Total_Trans_Ct = null`. The README's "append" step silently breaks the transaction-count KPI. | Header diff of the two files. v2 detects and repairs this automatically (`Total_Trans_Ct -> Total_Trans_Vol`, 0 nulls). |
| 9 | High | **The .pbix does not read the CSVs.** Its report queries `public.cc_detail` / `public.cust_detail` (database-style tables) which are not in the repo, while the README describes a CSV + Power Query pipeline. Nobody can refresh or verify the report from what was published. | Field references `public cc_detail.*` in the layout; no database script in the repo. |
| 10 | Medium | **Relationship cardinality is documented wrongly.** README says 1-to-many on `Client_Num`; in the data both tables have exactly one row per client (true 1:1, 10,293 = 10,293, no orphans). | `Client_Num` is unique in both files. |
| 11 | Medium | **Date format risk.** `Week_Start_Date` is `dd-mm-yyyy` text. Parsed as month-first, 6,004 of 10,293 values fail outright and the rest silently become wrong dates (`08-01-2023` -> 1 Aug). | `pd.to_datetime(..., format="%m-%d-%Y")`. v2 detects the order from the values (and from the weekly cadence when ambiguous). |
| 12 | Medium | **README promises visuals that do not exist**: "Active vs Delinquent by State (Map)", "Delinquent Accounts by Education Level", slicers for Card Type/Expense/Gender/Job. The file has no map visual and uses treemaps as slicers. | Visual types in the layout. |

## C. Data-quality problems never handled

| # | Finding | Evidence |
|---|---------|----------|
| 13 | `Use Chip` values carry trailing spaces (`"Swipe "`, `"Chip "`, `"Online "`) in 100% of rows - the same category would split if any file were cleaned differently. | repr of values. |
| 14 | `Zipcode` is a placeholder: 97.8% of rows are `91750` (a California zip), and zips conflict with states (CA has 27 distinct zips, FL has 1). Unusable as a geographic key. | `value_counts`, groupby. |
| 15 | `current_year` is constant (2023) - wasted slicer/column. Week 53 is a single-day "week" (31-Dec-2023). | `nunique`. |
| 16 | `Customer_Job` contains the typo `Selfemployeed`; `Reveneu` is misspelled on every visual. | strings. |
| 17 | Mixed number formats: Indian digit grouping in tables (`9,22,78,795.48`) beside `M`-suffixed cards, no currency. | Screenshots. |

## D. What the data actually says (that the old dashboard could not show)

* Delinquency is **not** random over time: Week 1 runs at **21.1%** vs 6.1% overall, Week 52 at 0% (chi-square p ≈ 1e-22, Cramér's V = 0.15). No customer attribute explains it (cross-validated AUC 0.58 -> weak).
* Transaction amount is very strongly tied to income (Pearson 0.93, Spearman 0.99), so income band is the biggest revenue driver (eta² = 0.35).
* Weekly revenue is flat (trend p = 0.10) and Blue cards are 91% of accounts but 85% of revenue; Gold earns ~2.3x revenue per account.
