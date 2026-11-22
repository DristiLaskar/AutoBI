# Power BI guide

AutoBI writes a **Power BI Project (PBIP)** - plain-text files that Power BI Desktop opens directly:

```
powerbi/
  <Name>.pbip                      <- double-click this
  <Name>.SemanticModel/            tables (Power Query M), relationships, 20+ DAX measures, Dim_Date
  <Name>.Report/                   4 pages: Overview, Segments, <Target> Risk, Data  (PBIR format)
  theme/AutoBI_Theme.json          optional colour theme
  measures.dax / power_query.m     plain-text copies (paste manually if you ever need to)
```

## Honest status

* The Python engine, the cleaned data and every number are **tested** (20 automated tests, see `tests/`).
* The Power BI files are written to Microsoft's documented PBIP / TMDL / PBIR formats and are checked by
  `autobi/validate.py` (every DAX and visual field exists, types match the CSVs, keys are unique, no overlapping visuals).
* Power BI Desktop only runs on Windows and was **not available where this project was generated**, so the `.pbip` has not
  been opened in Desktop by the author. If Desktop rejects something, use the fallbacks below - the data, DAX and
  model definitions are all still valid.

## Open it (3 minutes)

1. Install the latest Power BI Desktop. If `.pbip` files do not open, enable preview features under
   *File > Options > Preview features*: **Power BI Project (.pbip) save option**, **Store semantic model using TMDL format**,
   **Store reports using enhanced metadata format (PBIR)**. (Newer builds have these on by default.) Restart Desktop.
2. On Windows run `python run_autobi.py <your file or folder>` - the data folder is wired in automatically.
   If you copied a project generated elsewhere (e.g. the sample in `outputs/`), re-point it once:
   `python -m autobi set-data-folder outputs\credit_card\powerbi outputs\credit_card\clean`
   (or in Power BI: *Home > Transform data > Edit parameters > DataFolder*).
3. Open `<Name>.pbip`, click **Refresh**. Optional: *View > Themes > Browse for themes* -> `theme/AutoBI_Theme.json`.
4. *File > Save as* `.pbix` if you want a single shareable file.

## How the model is built (so you can explain it)

* **Star schema**: one fact table, dimension tables, and a generated `Dim_Date` marked as the date table.
  Relationships are many-to-one, single direction (dimension filters fact).
* **Measures live on the fact table.** Measures that use a *dimension* attribute (e.g. average income) are written with
  `AVERAGEX(Fact, RELATED(Dim[col]))`, so they respond to slicers on **both** sides. (The old project's customer-job table
  showed identical totals precisely because of this kind of filter-direction problem.)
* `discourageImplicitMeasures` is on: charts use explicit measures only - no accidental `Sum of Client_Num`.
* Time intelligence (`MoM %`, `YTD`, and `PY / YoY %` when the data spans more than one year) works because `Dim_Date` is contiguous.
* The data is loaded from the cleaned CSVs in `clean/` with explicit types and `"en-US"` culture, so dates and decimals
  parse identically on every machine.

## If something does not open

| Symptom | Fix |
|---------|-----|
| Desktop says it cannot open the project / report | Re-generate with `--no-pbi-visuals`. This produces the full semantic model (tables, relationships, measures, date table) and a blank report page; build the visuals by dragging fields (the layout of `report/dashboard.html` is a template). |
| A table fails to load: *file not found* | `DataFolder` parameter is wrong - see step 2. |
| Manual route (no PBIP at all) | *Get data > Text/CSV* for each file in `clean/`; relate the key columns shown in `report/summary.json`; mark `Dim_Date[Date]` as date table; paste `measures.dax` into *New measure*; paste `power_query.m` into the Advanced Editor if you prefer. |
| A later Desktop release changes the project format | Use the manual route above - the measures, M queries and CSVs do not depend on the project format. |
