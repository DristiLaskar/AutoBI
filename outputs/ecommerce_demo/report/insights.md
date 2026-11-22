# Fashion Ecommerce Demo (synthetic) - automatic insights

## Dataset overview
12,000 records across 4 table(s) from 2024-01-01 to 2024-12-31 (daily data). Primary measure analysed: net amount.

## category: where net amount comes from
'Sneakers' contributes 31.3% of total net amount (17.9% of records). Average net amount per record ranges from 640.69 ('Tshirts') to 3,814.05 ('Jackets'); difference is statistically significant (Kruskal p<0.001) with a meaningful effect size (eta²=0.417).

## quantity: where net amount comes from
'3' contributes 37.9% of total net amount (20.0% of records). Average net amount per record ranges from 1,145.15 ('1') to 3,503.76 ('3'); difference is statistically significant (Kruskal p<0.001) with a meaningful effect size (eta²=0.320).

## brand: where net amount comes from
'Roadster' contributes 16.2% of total net amount (15.7% of records). Average net amount per record ranges from 1,617.53 ('Nike') to 2,292.69 ('Libas'); difference is statistically significant (Kruskal p<0.001) with a meaningful effect size (eta²=0.010).

## Trend & seasonality
net amount per month period is rising by 3.58% per period (statistically significant, p=0.010, R²=0.51). Peak: 2024-10-01 (2.55M); low: 2024-07-01 (1.59M). Second half vs first half: +22.2%. 3 anomalous period(s) detected (robust z>3.5).

## Forecast reliability
Damped-trend forecast backtest on the last 3 periods: MAPE 25.8% vs naive 25.4% vs mean 29.6%. It does NOT beat a simple baseline, so treat the forecast as indicative only.

## Strongest relationship
net amount and mrp move together (Pearson r=0.71, Spearman 0.81).

## Drivers of returned
returned: 8.18% of records (981 of 12,000). No categorical segment shows a statistically significant and practically meaningful difference in rate. A gradient-boosting model using 10 fields reaches cross-validated AUC 0.639 (±0.027) -> weak signal. Most informative fields: discount pct (AUC drop 0.144).

## Customer / record segmentation
K-means found k=2 segments (silhouette 0.28 -> moderate structure). Low mrp / Low net amount / High discount pct (58%); High mrp / High net amount / Low discount pct (42%).
