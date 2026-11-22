# Credit Card Analytics - automatic insights

## Dataset overview
10,293 records across 3 table(s) from 2023-01-01 to 2023-12-31 (weekly data). Primary measure analysed: Revenue.

## Income Band: where Revenue comes from
'3-High' contributes 51.5% of total Revenue (33.3% of records). Average Revenue per record ranges from 603.08 ('1-Low') to 1,647.27 ('3-High'); difference is statistically significant (Kruskal p<0.001) with a meaningful effect size (eta²=0.351).

## Customer Job: where Revenue comes from
'Businessman' contributes 28.8% of total Revenue (18.8% of records). Average Revenue per record ranges from 723.94 ('Selfemployeed') to 1,632.35 ('Businessman'); difference is statistically significant (Kruskal p<0.001) with a meaningful effect size (eta²=0.188).

## Card Category: where Revenue comes from
'Blue' contributes 85.1% of total Revenue (91.2% of records). Average Revenue per record ranges from 996.15 ('Blue') to 2,291.81 ('Gold'); difference is statistically significant (Kruskal p<0.001) with a meaningful effect size (eta²=0.122).

## Trend & seasonality
Revenue per week period is falling by 0.08% per period (no statistically significant trend, p=0.099, R²=0.05). Peak: 2023-07-02 (240.1K); low: 2023-12-24 (184.5K). Second half vs first half: -0.4%.

## Forecast reliability
Damped-trend forecast backtest on the last 11 periods: MAPE 4.5% vs naive 6.5% vs mean 6.1%. The model beats both baselines - use the forecast as a planning guide.

## Strongest relationship
Total Trans Amt and Income move together (Pearson r=0.93, Spearman 0.99). 12 more pair(s) with |r|>=0.5.

## Drivers of Delinquent Acc
Delinquent Acc: 6.06% of records (624 of 10,293). No categorical segment shows a statistically significant and practically meaningful difference in rate. The rate is NOT uniform over time (chi-square p<0.001, V=0.15): it peaks at 21.1% in the period starting 2023-01-01 and drops to 0.0% in the period starting 2023-12-24. A gradient-boosting model using 31 fields reaches cross-validated AUC 0.581 (±0.036) -> weak signal. Most informative fields: Week Num (AUC drop 0.061), state cd (AUC drop 0.010), Customer Acq Cost (AUC drop 0.006).

## Customer / record segmentation
K-means found k=2 segments (silhouette 0.16 -> weak structure). Natural clusters are weak, so segments are exploratory rather than actionable.

## Data quality caveats
Dim_Customer.Zipcode: 97.8% of rows share one value - unusable as a dimension / geo key
