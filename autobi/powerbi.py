"""Generate a Power BI Project (PBIP): semantic model in TMDL + report in PBIR format.

What is generated
-----------------
<Name>.pbip
<Name>.SemanticModel/   tables (Power Query M -> the cleaned CSVs), relationships, DAX measures, Dim_Date
<Name>.Report/          PBIR pages: Overview, Segments, Risk (if a binary target exists), Data
theme/AutoBI_Theme.json (optional colour theme: View > Themes > Browse for themes)
measures.dax, power_query.m  plain-text copies so everything can also be pasted in manually
"""
from __future__ import annotations
import json
import re
import shutil
import uuid
from pathlib import Path
import numpy as np
import pandas as pd
from .utils import pretty, is_num, is_date, is_text
from .analysis import lab

SCHEMA = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
VISUAL_SCHEMA = f"{SCHEMA}/visualContainer/2.4.0/schema.json"
NS = uuid.UUID("6f1d3a52-8f43-4c9e-9d0e-0a0b0c0d0e0f")
PALETTE = ["#4F46E5", "#0D9488", "#F59E0B", "#E11D48", "#8B5CF6", "#0EA5E9", "#84CC16", "#F97316"]


def _id(*parts) -> str:
    return uuid.uuid5(NS, "|".join(map(str, parts))).hex[:20]


def _guid(*parts) -> str:
    return str(uuid.uuid5(NS, "|".join(map(str, parts))))


def _q(name: str) -> str:
    """TMDL object-name quoting."""
    return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) else "'" + name.replace("'", "''") + "'"


def _dq(t: str, c: str) -> str:
    return f"'{t}'[{c}]"


# ============================================================================== measures
def build_measures(model: dict, res: dict) -> list[dict]:
    """Return [{name, expr, fmt, folder, desc}] - the DAX equivalent of every KPI the Python engine computed."""
    fact = model["fact"]
    fcols = set(model["tables"][fact].columns)
    used: set = set()
    out = []

    def add(name, expr, fmt, folder, desc=""):
        base, i = name, 2
        while name in used or name in fcols:
            name = f"{base} ({i})" if name in used else f"{base} (Measure)"
            i += 1
        used.add(name)
        out.append({"name": name, "expr": expr, "fmt": fmt, "folder": folder, "desc": desc})
        return name

    def col_ref(spec):
        return _dq(spec["table"], spec["column"])

    names = {}
    for s in res["kpi_specs"]:
        t, c, a = s["table"], s["column"], s["agg"]
        on_dim = t != fact and c is not None
        if a == "rows":
            e, fm = f"COUNTROWS('{fact}')", "#,0"
        elif a == "distinct":
            e, fm = f"DISTINCTCOUNT({col_ref(s)})", "#,0"
        elif a == "sum":
            e = f"SUMX('{fact}', RELATED({col_ref(s)}))" if on_dim else f"SUM({col_ref(s)})"
            fm = "#,0"
        elif a == "avg":
            e = f"AVERAGEX('{fact}', RELATED({col_ref(s)}))" if on_dim else f"AVERAGE({col_ref(s)})"
            fm = "0.0%" if s["fmt"] == "pct" else "#,0.00"
        else:  # rate of a 0/1 flag
            e = f"AVERAGEX('{fact}', RELATED({col_ref(s)}))" if on_dim else f"AVERAGE({col_ref(s)})"
            fm = "0.00%"
        folder = "Rates" if a == "rate" or s["fmt"] == "pct" else "KPIs"
        names[s["key"]] = add(s["label"], e, fm, folder, f"Auto KPI: {a} of {c or 'rows'}")

    P = res.get("primary")
    if P and f"sum_{P}" in names:
        tot = f"[{names[f'sum_{P}']}]"
        add(f"{pretty(P)} % of Total", f"DIVIDE({tot}, CALCULATE({tot}, ALLSELECTED()))", "0.0%", "KPIs",
            "Share of the currently selected total")
        if model.get("date"):
            d = "'Dim_Date'[Date]"
            add(f"{pretty(P)} MoM %", f"VAR cur = {tot} VAR prev = CALCULATE({tot}, DATEADD({d}, -1, MONTH)) "
                                      f"RETURN IF(NOT ISBLANK(prev), DIVIDE(cur - prev, prev))", "+0.0%;-0.0%;0.0%", "Time Intelligence")
            add(f"{pretty(P)} YTD", f"TOTALYTD({tot}, {d})", "#,0", "Time Intelligence")
            if model["date"]["span_days"] > 366:
                add(f"{pretty(P)} PY", f"CALCULATE({tot}, SAMEPERIODLASTYEAR({d}))", "#,0", "Time Intelligence")
                add(f"{pretty(P)} YoY %", f"VAR cur = {tot} VAR py = CALCULATE({tot}, SAMEPERIODLASTYEAR({d})) "
                                          f"RETURN IF(NOT ISBLANK(py), DIVIDE(cur - py, py))", "+0.0%;-0.0%;0.0%", "Time Intelligence")
    T = res.get("target_col")
    if T and f"rate_{T}" in names:
        r = f"[{names[f'rate_{T}']}]"
        tt = model["profiles"][fact].get(T) is not None
        tcol = _dq(fact, T) if tt else None
        if tcol:
            add(f"{pretty(T)} Count", f"SUM({tcol})", "#,0", "Rates")
        add(f"{pretty(T)} Lift vs Overall", f"DIVIDE({r}, CALCULATE({r}, ALLSELECTED()))", '0.00"x"', "Rates",
            "How many times the overall rate the current selection runs at")
    return out


# ============================================================================== TMDL: tables
def _m_type(s: pd.Series) -> str:
    if is_date(s):
        return "type datetime" if (s.dropna() != s.dropna().dt.normalize()).any() else "type date"
    if is_num(s):
        return "Int64.Type" if pd.api.types.is_integer_dtype(s) else "type number"
    return "type text"


def _tmdl_col(name, s: pd.Series, p: dict, extra: dict | None = None) -> str:
    extra = extra or {}
    if is_date(s):
        dtype, fmt = "dateTime", "yyyy-mm-dd" if _m_type(s) == "type date" else "yyyy-mm-dd hh:nn"
    elif is_num(s):
        if pd.api.types.is_integer_dtype(s):
            dtype, fmt = "int64", "0" if p.get("role") == "id" else "#,0"
        else:
            dtype, fmt = "double", "0.0%" if p.get("kind") == "rate" else "#,0.00"
    else:
        dtype, fmt = "string", None
    L = [f"\tcolumn {_q(name)}", f"\t\tdataType: {dtype}"]
    if fmt:
        L.append(f"\t\tformatString: {fmt}")
    if extra.get("isKey"):
        L.append("\t\tisKey")
    if p.get("role") == "meta" and name == "Source_File":
        L.append("\t\tisHidden")
    L.append("\t\tsummarizeBy: none")
    L.append(f"\t\tsourceColumn: {name}")
    if extra.get("sortBy"):
        L.append(f"\t\tsortByColumn: {extra['sortBy']}")
    return "\n".join(L)


def m_query(table: str, df: pd.DataFrame) -> str:
    types = ", ".join(f'{{"{c}", {_m_type(df[c])}}}' for c in df.columns)
    return (
        "let\n"
        f'    Source = Csv.Document(File.Contents(DataFolder & "\\{table}.csv"), [Delimiter=",", Columns={df.shape[1]}, Encoding=65001, QuoteStyle=QuoteStyle.Csv]),\n'
        '    #"Promoted Headers" = Table.PromoteHeaders(Source, [PromoteAllScalars=true]),\n'
        f'    #"Changed Type" = Table.TransformColumnTypes(#"Promoted Headers", {{{types}}}, "en-US")\n'
        "in\n"
        '    #"Changed Type"'
    )


DATE_SORT = {"Month": "Month_Num", "Quarter": "Quarter_Num", "Day_Name": "Day_Of_Week_Num"}


def table_tmdl(name: str, df: pd.DataFrame, prof: dict, measures: list[dict]) -> str:
    L = [f"table {_q(name)}"]
    if name == "Dim_Date":
        L.append("\tdataCategory: Time")
    L.append("")
    for m in measures:
        expr = m["expr"]
        L.append(f"\tmeasure {_q(m['name'])} = {expr}")
        L.append(f"\t\tformatString: {m['fmt']}")
        if m.get("folder"):
            L.append(f"\t\tdisplayFolder: {m['folder']}")
        L.append("")
    for c in df.columns:
        extra = {}
        if name == "Dim_Date":
            extra = {"isKey": c == "Date", "sortBy": DATE_SORT.get(c)}
        L.append(_tmdl_col(c, df[c], prof.get(c, {}), extra))
        L.append("")
    q = m_query(name, df).replace("\n", "\n\t\t\t\t")
    L.append(f"\tpartition {_q(name)} = m")
    L.append("\t\tmode: import")
    L.append("\t\tsource =")
    L.append("\t\t\t\t" + q)
    L.append("")
    L.append("\tannotation PBI_ResultType = Table")
    return "\n".join(L) + "\n"


# ============================================================================== PBIR helpers
def _lit(v) -> dict:
    return {"expr": {"Literal": {"Value": v}}}


def _col(table, col) -> dict:
    return {"field": {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": col}},
            "queryRef": f"{table}.{col}", "nativeQueryRef": col}


def _meas(table, name) -> dict:
    return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}},
            "queryRef": f"{table}.{name}", "nativeQueryRef": name}


def _visual(page, idx, vtype, x, y, w, h, roles: dict, title: str | None = None):
    qs = {}
    for role, items in roles.items():
        projs = []
        for j, it in enumerate(items):
            it = dict(it)
            if role in ("Category", "Series", "Rows") and j == 0:
                it["active"] = True
            projs.append(it)
        qs[role] = {"projections": projs}
    body = {"$schema": VISUAL_SCHEMA, "name": _id(page, idx, vtype),
            "position": {"x": float(x), "y": float(y), "z": idx * 1000, "height": float(h), "width": float(w), "tabOrder": idx * 1000},
            "visual": {"visualType": vtype, "query": {"queryState": qs}, "drillFilterOtherVisuals": True}}
    if title:
        body["visual"]["visualContainerObjects"] = {"title": [{"properties": {"show": _lit("true"), "text": _lit("'" + title.replace("'", "''") + "'")}}]}
    return body


class _Page:
    def __init__(self, key, name):
        self.key, self.name, self.visuals = key, name, []

    def add(self, vtype, x, y, w, h, roles, title=None):
        self.visuals.append(_visual(self.key, len(self.visuals), vtype, x, y, w, h, roles, title))


def _slicers(page: _Page, model, res, dims, x=20, y=120, w=200):
    fact = model["fact"]
    ys = y
    if model.get("date"):
        page.add("slicer", x, ys, w, 80, {"Values": [_col("Dim_Date", "Date")]})
        ys += 90
    table_of = {c: t for t in [fact] + model["dims"] for c in model["tables"][t].columns}
    for d in dims[:3]:
        t = table_of.get(d)
        if not t:
            continue
        page.add("slicer", x, ys, w, 150, {"Values": [_col(t, d)]})
        ys += 160


def build_pages(model: dict, res: dict, measures: list[dict], names: dict) -> list[_Page]:
    fact = model["fact"]
    P = res.get("primary")
    table_of = {c: t for t in [fact] + model["dims"] for c in model["tables"][t].columns}
    prim_m = names.get(f"sum_{P}") if P else None
    dims_ranked = [b["dim"] for b in res["breakdowns"] if b["dim"] in table_of]
    pages = []

    # ---------------------------------------------------------------- Overview
    pg = _Page("overview", "Overview")
    kpi_keys = []
    if P:
        kpi_keys += [f"sum_{P}", f"avg_{P}"]
    kpi_keys += ["entities", "records"]
    T = res.get("target_col")
    if T:
        kpi_keys.append(f"rate_{T}")
    kpi_keys += [s["key"] for s in res["kpi_specs"] if s["key"] not in kpi_keys and s["key"] in names]
    kpi_keys = [k for k in kpi_keys if k in names][:6]
    cw = (1240 - 12 * (len(kpi_keys) - 1)) / max(len(kpi_keys), 1)
    for i, k in enumerate(kpi_keys):
        pg.add("card", 20 + i * (cw + 12), 15, cw, 90, {"Values": [_meas(fact, names[k])]})
    _slicers(pg, model, res, dims_ranked)
    if prim_m:
        if model.get("date"):
            pg.add("lineChart", 230, 120, 1030, 270, {"Category": [_col("Dim_Date", "Date")], "Y": [_meas(fact, prim_m)]},
                   f"{pretty(P)} over time")
            charts_y, charts_h = 400, 300
        else:
            charts_y, charts_h = 120, 580
        cands = dims_ranked[:2]
        wd = (1030 - 14) / 2 if len(cands) == 2 else 1030
        for i, d in enumerate(cands):
            vt = "donutChart" if (i == 1 and len(model['tables'][table_of[d]][d].unique()) <= 8) else "clusteredBarChart"
            pg.add(vt, 230 + i * (wd + 14), charts_y, wd, charts_h, {"Category": [_col(table_of[d], d)], "Y": [_meas(fact, prim_m)]},
                   f"{pretty(P)} by {pretty(d)}")
    pages.append(pg)

    # ---------------------------------------------------------------- Segments
    rest = dims_ranked[2:8]
    if prim_m and rest:
        pg = _Page("segments", "Segments")
        _slicers(pg, model, res, dims_ranked, y=15)
        ncols, wd, ht = 2, 507, 225
        for i, d in enumerate(rest):
            r, c = divmod(i, ncols)
            pg.add("clusteredBarChart", 230 + c * (wd + 16), 15 + r * (ht + 12), wd, ht,
                   {"Category": [_col(table_of[d], d)], "Y": [_meas(fact, prim_m)]}, f"{pretty(P)} by {pretty(d)}")
        pages.append(pg)

    # ---------------------------------------------------------------- Risk
    tg = res.get("target")
    if T and tg and f"rate_{T}" in names:
        rate_m = names[f"rate_{T}"]
        pg = _Page("risk", f"{pretty(T)} Risk")
        cnt = next((m["name"] for m in measures if m["name"] == f"{pretty(T)} Count"), None)
        lift = next((m["name"] for m in measures if m["name"].endswith("Lift vs Overall")), None)
        cards = [m for m in (rate_m, cnt, lift) if m]
        for i, m in enumerate(cards):
            pg.add("card", 230 + i * 350, 15, 330, 90, {"Values": [_meas(fact, m)]})
        _slicers(pg, model, res, dims_ranked, y=120)
        if model.get("date"):
            pg.add("clusteredColumnChart", 230, 120, 1030, 250, {"Category": [_col("Dim_Date", "Date")], "Y": [_meas(fact, rate_m)]},
                   f"{pretty(T)} rate over time")
        seg_dims = [s["dim"] for s in tg["segments"] if s["dim"] in table_of][:3]
        wd = (1030 - 2 * 14) / max(len(seg_dims), 1)
        for i, d in enumerate(seg_dims):
            pg.add("clusteredBarChart", 230 + i * (wd + 14), 380, wd, 320, {"Category": [_col(table_of[d], d)], "Y": [_meas(fact, rate_m)]},
                   f"{pretty(T)} rate by {pretty(d)}")
        pages.append(pg)

    # ---------------------------------------------------------------- Data
    pg = _Page("data", "Data")
    cols = []
    if res.get("entity"):
        cols.append(_col(fact, res["entity"]))
    if model.get("date"):
        cols.append(_col(fact, model["date"]["fact_column"]))
    for d in dims_ranked[:4]:
        cols.append(_col(table_of[d], d))
    if P:
        cols.append(_col(fact, P))
    pg.add("tableEx", 20, 15, 1240, 685, {"Values": cols})
    pages.append(pg)
    return pages


# ============================================================================== writer
def _write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _json(path: Path, obj):
    _write(path, json.dumps(obj, indent=2, ensure_ascii=False) + "\n")


def theme_json() -> dict:
    return {"name": "AutoBI", "dataColors": PALETTE + ["#64748B", "#0F766E", "#B45309", "#BE123C"],
            "background": "#FFFFFF", "foreground": "#0F172A", "tableAccent": "#4F46E5",
            "good": "#0D9488", "neutral": "#F59E0B", "bad": "#E11D48",
            "textClasses": {"title": {"fontSize": 12, "fontFace": "Segoe UI Semibold", "color": "#0F172A"},
                            "label": {"fontSize": 10, "fontFace": "Segoe UI", "color": "#475569"},
                            "callout": {"fontSize": 24, "fontFace": "Segoe UI Semibold", "color": "#0F172A"}}}


def write_project(out_dir: Path, name: str, model: dict, res: dict, data_folder: str, with_visuals: bool = True) -> dict:
    """Write the full PBIP folder. Returns a manifest dict (paths + measure list)."""
    safe = re.sub(r"[^A-Za-z0-9_]+", "_", name).strip("_") or "AutoBI"
    root = Path(out_dir)
    sm = root / f"{safe}.SemanticModel"
    rp = root / f"{safe}.Report"
    measures = build_measures(model, res)
    fact = model["fact"]
    # names of KPI measures by spec key (in the same order build_measures consumed them)
    names = {}
    it = iter(measures)
    for s in res["kpi_specs"]:
        names[s["key"]] = next(it)["name"]

    for old in (sm, rp, root / "theme"):  # never leave stale files from a previous run behind
        if old.exists():
            shutil.rmtree(old)

    # ---- .pbip & git ignore
    _json(root / f"{safe}.pbip", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/1.0.0/schema.json",
                                  "version": "1.0", "artifacts": [{"report": {"path": f"{safe}.Report"}}],
                                  "settings": {"enableAutoRecovery": True}})
    _write(root / ".gitignore", "**/.pbi/localSettings.json\n**/.pbi/cache.abf\n")

    # ---- semantic model
    _json(sm / "definition.pbism", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/definitionProperties/1.0.0/schema.json",
                                    "version": "4.0", "settings": {}})
    _write(sm / "definition" / "database.tmdl", "database\n\tcompatibilityLevel: 1567\n")
    table_names = list(model["tables"])
    model_lines = ["model Model", "\tculture: en-US", "\tdefaultPowerBIDataSourceVersion: powerBI_V3", "\tdiscourageImplicitMeasures",
                   "\tsourceQueryCulture: en-US", "\tdataAccessOptions", "\t\tlegacyRedirects", "\t\treturnErrorValuesAsNull", "",
                   "annotation PBI_QueryOrder = " + json.dumps(["DataFolder"] + table_names), "",
                   "ref expression DataFolder"] + [f"ref table {_q(t)}" for t in table_names]
    _write(sm / "definition" / "model.tmdl", "\n".join(model_lines) + "\n")
    _write(sm / "definition" / "expressions.tmdl",
           f'expression DataFolder = "{data_folder}" meta [IsParameterQuery=true, Type="Text", IsParameterQueryRequired=true]\n'
           "\tlineageTag: " + _guid("DataFolder") + "\n\tqueryGroup: Parameters\n\n\tannotation PBI_ResultType = Text\n")
    for t, df in model["tables"].items():
        _write(sm / "definition" / "tables" / f"{t}.tmdl", table_tmdl(t, df, model["profiles"][t], measures if t == fact else []))
    rl = []
    for r in model["relationships"]:
        rl.append(f"relationship {_guid(r['from_table'], r['from_col'], r['to_table'], r['to_col'])}\n"
                  f"\tfromColumn: {_q(r['from_table'])}.{_q(r['from_col'])}\n\ttoColumn: {_q(r['to_table'])}.{_q(r['to_col'])}\n")
    if rl:
        _write(sm / "definition" / "relationships.tmdl", "\n".join(rl))

    # ---- report (PBIR)
    _json(rp / "definition.pbir", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/report/definitionProperties/2.0.0/schema.json",
                                   "version": "4.0", "datasetReference": {"byPath": {"path": f"../{safe}.SemanticModel"}}})
    d = rp / "definition"
    _json(d / "version.json", {"$schema": f"{SCHEMA}/versionMetadata/1.0.0/schema.json", "version": "2.0.0"})
    _json(d / "report.json", {"$schema": f"{SCHEMA}/report/1.0.0/schema.json",
                              "themeCollection": {"baseTheme": {"name": "CY24SU06", "reportVersionAtImport": "5.55", "type": "SharedResources"}},
                              "layoutOptimization": "None"})
    pages = build_pages(model, res, measures, names) if with_visuals else [_Page("overview", "Overview")]
    _json(d / "pages" / "pages.json", {"$schema": f"{SCHEMA}/pagesMetadata/1.0.0/schema.json",
                                       "pageOrder": [p.key for p in pages], "activePageName": pages[0].key})
    n_visuals = 0
    for p in pages:
        _json(d / "pages" / p.key / "page.json", {"$schema": f"{SCHEMA}/page/1.0.0/schema.json", "name": p.key, "displayName": p.name,
                                                  "displayOption": "FitToPage", "height": 720, "width": 1280})
        for v in p.visuals:
            _json(d / "pages" / p.key / "visuals" / v["name"] / "visual.json", v)
            n_visuals += 1

    # ---- companions
    _json(root / "theme" / "AutoBI_Theme.json", theme_json())
    dax = ["// AutoBI generated measures (already inside the semantic model; copy if you build the model manually)\n"]
    for m in measures:
        dax.append(f"{m['name']} =\n    {m['expr']}\n")
    _write(root / "measures.dax", "\n".join(dax))
    _write(root / "power_query.m", "\n\n".join(f"// ---- {t}\n{m_query(t, df)}" for t, df in model["tables"].items()))
    return {"pbip": str(root / f"{safe}.pbip"), "semantic_model": str(sm), "report": str(rp), "n_measures": len(measures),
            "n_pages": len(pages), "n_visuals": n_visuals, "pages": [p.name for p in pages], "safe_name": safe,
            "measures": measures}


def set_data_folder(project_dir: str | Path, folder: str):
    """Point the DataFolder parameter of an existing generated project at a new folder (e.g. after moving it)."""
    for f in Path(project_dir).rglob("expressions.tmdl"):
        txt = f.read_text(encoding="utf-8")
        new = re.sub(r'(expression DataFolder = ")[^"]*(")', lambda m: m.group(1) + folder + m.group(2), txt)
        f.write_text(new, encoding="utf-8", newline="\n")
        return str(f)
    raise FileNotFoundError("expressions.tmdl not found")
