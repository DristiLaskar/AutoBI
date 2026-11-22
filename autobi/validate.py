"""Self-check of a generated Power BI project against the cleaned data (no Power BI needed).

Checks: JSON validity, TMDL structure, every DAX / visual field reference exists, CSV <-> Power Query type
compatibility, relationship key integrity, KPI values re-computed from the exported CSVs."""
from __future__ import annotations
import json
import re
from pathlib import Path
import numpy as np
import pandas as pd


def _parse_tmdl_table(text: str):
    cols, meas, name = [], {}, None
    for line in text.splitlines():
        if line.startswith("table "):
            name = line[6:].strip().strip("'")
        m = re.match(r"^\tcolumn (.+)$", line)
        if m:
            cols.append(m.group(1).strip().strip("'"))
        m = re.match(r"^\tmeasure (.+?) = (.*)$", line)
        if m:
            meas[m.group(1).strip().strip("'")] = m.group(2)
    return name, cols, meas


def validate_project(out_dir: str | Path, pbi: dict, model: dict, res: dict) -> list[str]:
    problems: list[str] = []
    out = Path(out_dir)
    sm, rp = Path(pbi["semantic_model"]), Path(pbi["report"])

    # 1. every json parses
    for f in list(sm.rglob("*.json")) + list(rp.rglob("*.json")) + list(sm.rglob("*.pbism")) + list(rp.rglob("*.pbir")) + [Path(pbi["pbip"])]:
        try:
            json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:
            problems.append(f"invalid JSON {f.name}: {e}")

    # 2. TMDL tables / measures
    tables, measures = {}, {}
    for f in (sm / "definition" / "tables").glob("*.tmdl"):
        text = f.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if line.startswith(" ") or re.match(r"^\t* +\t", line):
                problems.append(f"{f.name}:{i} space indentation outside an expression body")
        name, cols, meas = _parse_tmdl_table(text)
        tables[name], measures[name] = cols, meas
        if name != f.stem:
            problems.append(f"{f.name}: table name {name} != file name")
        if len(set(cols)) != len(cols):
            problems.append(f"{name}: duplicate column names")
        clash = set(cols) & set(meas)
        if clash:
            problems.append(f"{name}: measure/column name clash {clash}")
    model_txt = (sm / "definition" / "model.tmdl").read_text(encoding="utf-8")
    for t in model["tables"]:
        if f"ref table {t}" not in model_txt:
            problems.append(f"model.tmdl missing ref table {t}")
        if t not in tables:
            problems.append(f"table file missing for {t}")
        elif list(model["tables"][t].columns) != tables[t]:
            problems.append(f"{t}: TMDL columns differ from CSV columns")

    # 3. DAX references
    all_measures = {m for ms in measures.values() for m in ms}
    for t, ms in measures.items():
        for mname, expr in ms.items():
            for tb, col in re.findall(r"'([^']+)'\[([^\]]+)\]", expr):
                if tb not in tables or col not in tables[tb]:
                    problems.append(f"measure {mname}: unknown column {tb}[{col}]")
            expr2 = re.sub(r"'[^']+'\[[^\]]+\]", "", expr)
            for ref in re.findall(r"\[([^\]]+)\]", expr2):
                if ref not in all_measures:
                    problems.append(f"measure {mname}: unknown measure [{ref}]")
            if expr.count("(") != expr.count(")"):
                problems.append(f"measure {mname}: unbalanced parentheses")

    # 4. relationships
    rel_txt = (sm / "definition" / "relationships.tmdl")
    if model["relationships"]:
        txt = rel_txt.read_text(encoding="utf-8")
        for r in model["relationships"]:
            if f"fromColumn: {r['from_table']}.{r['from_col']}" not in txt or f"toColumn: {r['to_table']}.{r['to_col']}" not in txt:
                problems.append(f"relationship missing: {r}")
            one = model["tables"][r["to_table"]][r["to_col"]]
            many = model["tables"][r["from_table"]][r["from_col"]]
            if not one.dropna().is_unique:
                problems.append(f"relationship key not unique on one-side: {r['to_table']}[{r['to_col']}]")
            if one.isna().any():
                problems.append(f"null keys on one-side: {r['to_table']}[{r['to_col']}]")
            orphan = int((~many.dropna().isin(set(one.dropna()))).sum())
            if orphan:
                problems.append(f"{orphan} orphan rows {r['from_table']}[{r['from_col']}] without match in {r['to_table']}")

    # 5. report visuals
    pages = json.loads((rp / "definition" / "pages" / "pages.json").read_text())
    for pg in pages["pageOrder"]:
        pj = rp / "definition" / "pages" / pg / "page.json"
        if not pj.exists():
            problems.append(f"page file missing {pg}")
            continue
        names = set()
        boxes = []
        for vf in (rp / "definition" / "pages" / pg / "visuals").glob("*/visual.json"):
            v = json.loads(vf.read_text())
            if v["name"] != vf.parent.name:
                problems.append(f"visual name != folder {vf.parent.name}")
            if v["name"] in names:
                problems.append(f"duplicate visual name {v['name']}")
            names.add(v["name"])
            pos = v["position"]
            if pos["x"] + pos["width"] > 1281 or pos["y"] + pos["height"] > 721 or min(pos["x"], pos["y"]) < 0:
                problems.append(f"{pg}: visual outside 1280x720 canvas {v['name']}")
            boxes.append((pos["x"], pos["y"], pos["x"] + pos["width"], pos["y"] + pos["height"], v["name"]))
            for role, rv in v["visual"]["query"]["queryState"].items():
                for pr in rv["projections"]:
                    f = pr["field"]
                    kind = "Column" if "Column" in f else "Measure"
                    ent, prop = f[kind]["Expression"]["SourceRef"]["Entity"], f[kind]["Property"]
                    if ent not in tables or (prop not in (tables[ent] if kind == "Column" else measures[ent])):
                        problems.append(f"{pg}: visual references unknown {kind} {ent}[{prop}]")
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                if a[0] < b[2] - 0.5 and b[0] < a[2] - 0.5 and a[1] < b[3] - 0.5 and b[1] < a[3] - 0.5:
                    problems.append(f"{pg}: overlapping visuals {a[4]} / {b[4]}")

    # 6. CSV <-> Power Query type compatibility + KPI round-trip
    csvs = {}
    for t, df in model["tables"].items():
        f = out / "clean" / f"{t}.csv"
        raw = f.read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            problems.append(f"{t}.csv has a BOM (would corrupt the first header in Power Query)")
        back = pd.read_csv(f, dtype=str, keep_default_na=False)
        if list(back.columns) != list(df.columns):
            problems.append(f"{t}.csv header mismatch")
            continue
        if len(back) != len(df):
            problems.append(f"{t}.csv row count {len(back)} != {len(df)}")
        for c in df.columns:
            s = back[c].replace("", np.nan).dropna()
            if pd.api.types.is_integer_dtype(df[c]):
                if not s.str.fullmatch(r"-?\d+").all():
                    problems.append(f"{t}.{c}: non-integer text in Int64 column")
            elif pd.api.types.is_float_dtype(df[c]):
                if pd.to_numeric(s, errors="coerce").isna().any():
                    problems.append(f"{t}.{c}: non-numeric text in number column")
            elif pd.api.types.is_datetime64_any_dtype(df[c]):
                if pd.to_datetime(s, format="%Y-%m-%d", errors="coerce").isna().any() and pd.to_datetime(s, format="%Y-%m-%d %H:%M:%S", errors="coerce").isna().any():
                    problems.append(f"{t}.{c}: bad ISO date text")
        csvs[t] = pd.read_csv(f)
    fact = model["fact"]
    if fact in csvs:
        flat = csvs[fact]
        for r in model["relationships"]:
            if r["from_table"] == fact and r["to_table"] in csvs and r["to_table"] != "Dim_Date":
                dim = csvs[r["to_table"]]
                keep = [c for c in dim.columns if c == r["to_col"] or c not in flat.columns]
                flat = flat.merge(dim[keep], left_on=r["from_col"], right_on=r["to_col"], how="left", suffixes=("", "_d"))
        for k in res["kpis"]:
            if k["value"] is None or k["agg"] == "rows" and k["value"] != len(flat):
                if k["value"] != len(flat):
                    problems.append(f"KPI {k['label']} mismatch on rows")
                continue
            if k["agg"] == "distinct":
                v = flat[k["column"]].nunique()
            elif k["agg"] == "sum":
                v = flat[k["column"]].sum()
            elif k["agg"] in ("avg", "rate"):
                v = flat[k["column"]].mean()
            else:
                continue
            if not np.isclose(v, k["value"], rtol=1e-9, atol=1e-9):
                problems.append(f"KPI {k['label']}: CSV recompute {v} != engine {k['value']}")
    return problems
