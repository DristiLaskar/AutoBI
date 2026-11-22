"""Combine tables into a Power-BI friendly star schema.

* appends files that are the same table split into pieces (and repairs *schema drift*,
  e.g. one file calls a column ``Total_Trans_Vol`` and the other ``Total_Trans_Ct``)
* detects join keys between different tables and validates them (uniqueness + value overlap)
* picks the fact table, builds ``Dim_Date`` and helpful band columns (age group, income band ...)
"""
from __future__ import annotations
import re
from difflib import SequenceMatcher
import numpy as np
import pandas as pd
from .utils import norm_name, is_num, is_text, is_date
from .profile import profile_table, AGE_NAME


# ------------------------------------------------------------------------------ appending
def _family(p: dict) -> str:
    r = p["role"]
    return {"numeric": "num", "ordinal": "num", "binary": "num", "id": "num", "date": "date"}.get(r, "txt")


def match_columns(a: pd.DataFrame, pa: dict, b: pd.DataFrame, pb: dict):
    """Map columns of b onto columns of a. Returns (mapping b->a, list of fuzzy matches, coverage)."""
    a_norm = {norm_name(c): c for c in a.columns}
    mapping, fuzzy = {}, []
    for c in b.columns:
        if norm_name(c) in a_norm:
            mapping[c] = a_norm[norm_name(c)]
    ua = [c for c in a.columns if c not in mapping.values()]
    ub = [c for c in b.columns if c not in mapping]
    pairs = []
    for cb in ub:
        for ca in ua:
            if _family(pa[ca]) != _family(pb[cb]):
                continue
            r = SequenceMatcher(None, norm_name(ca), norm_name(cb)).ratio()
            if r < 0.6:
                continue
            if _family(pa[ca]) == "num":  # numeric sanity: comparable scale
                ma, mb = float(a[ca].astype(float).median()), float(b[cb].astype(float).median())
                if (ma == 0) != (mb == 0) or (ma and not (0.2 <= abs(mb / ma) <= 5)):
                    continue
            pairs.append((r, ca, cb))
    used_a, used_b = set(), set()
    for r, ca, cb in sorted(pairs, reverse=True):
        if ca in used_a or cb in used_b:
            continue
        mapping[cb] = ca
        fuzzy.append({"from": cb, "to": ca, "name_similarity": round(r, 2)})
        used_a.add(ca)
        used_b.add(cb)
    coverage = len(mapping) / max(1, min(a.shape[1], b.shape[1]))
    return mapping, fuzzy, coverage


def unify_tables(tables: dict, log: list, cfg: dict):
    """tables: {name: df}. Append tables that share a schema; returns (new_tables, append_report)."""
    names = sorted(tables, key=lambda n: -len(tables[n]))  # largest file = base of an append group
    profs = {n: profile_table(tables[n], n) for n in names}
    groups = {n: [n] for n in names}
    report = []
    merged_into = {}
    for i, a in enumerate(names):
        if a in merged_into:
            continue
        for b in names[i + 1:]:
            if b in merged_into:
                continue
            mapping, fuzzy, cov = match_columns(tables[a], profs[a], tables[b], profs[b])
            if cov >= 0.9 and len(mapping) >= 2:
                merged_into[b] = a
                groups[a].append(b)
                rb = tables[b].rename(columns=mapping)
                rb = rb[[c for c in tables[a].columns if c in rb.columns]]
                for c in tables[a].columns:
                    if c not in rb.columns:
                        rb[c] = np.nan
                tables[a] = pd.concat([tables[a].assign(Source_File=a) if "Source_File" not in tables[a] else tables[a],
                                       rb.assign(Source_File=b)], ignore_index=True)
                rep = {"base": a, "appended": b, "rows_added": int(len(rb)), "columns_matched": len(mapping),
                       "schema_drift_repaired": fuzzy}
                report.append(rep)
                msg = f"appended '{b}' ({len(rb):,} rows) onto '{a}'"
                if fuzzy:
                    msg += " - repaired column-name drift: " + ", ".join(f"{f['from']}->{f['to']}" for f in fuzzy)
                log.append(msg)
                profs[a] = profile_table(tables[a], a)
    out = {n: tables[n] for n in names if n not in merged_into}
    for n, df in out.items():
        if "Source_File" in df.columns:
            df["Source_File"] = df["Source_File"].astype(str)
    return out, report


# ------------------------------------------------------------------------------ relationships
def _key_candidates(df, prof):
    return [c for c, p in prof.items() if p["role"] in ("id", "category", "ordinal", "text") and p["n_unique"] >= 2
            and c != "Source_File"]


def detect_relationships(tables: dict, profs: dict, log: list):
    rels = []
    names = list(tables)
    for i, t1 in enumerate(names):
        for t2 in names[i + 1:]:
            best = None
            for c1 in _key_candidates(tables[t1], profs[t1]):
                for c2 in _key_candidates(tables[t2], profs[t2]):
                    sim = SequenceMatcher(None, norm_name(c1), norm_name(c2)).ratio()
                    same = norm_name(c1) == norm_name(c2)
                    if not same and not (sim >= 0.85 and profs[t1][c1]["role"] == "id" and profs[t2][c2]["role"] == "id"):
                        continue
                    if is_num(tables[t1][c1]) != is_num(tables[t2][c2]):
                        continue
                    s1, s2 = tables[t1][c1].dropna(), tables[t2][c2].dropna()
                    u1, u2 = s1.is_unique, s2.is_unique
                    if not (u1 or u2):
                        continue
                    one_t, one_c, many_t, many_c = (t1, c1, t2, c2) if u1 and (not u2 or len(s1) <= len(s2)) else (t2, c2, t1, c1)
                    one_vals = set(tables[one_t][one_c].dropna().unique())
                    many_s = tables[many_t][many_c].dropna()
                    match = float(many_s.isin(one_vals).mean()) if len(many_s) else 0.0
                    if match < 0.9:
                        continue
                    cand = {"one_table": one_t, "one_col": one_c, "many_table": many_t, "many_col": many_c,
                            "match_pct": round(match * 100, 2), "one_to_one": bool(u1 and u2),
                            "key_quality": 2 if profs[t1][c1]["role"] == "id" else 1}
                    if best is None or (cand["key_quality"], cand["match_pct"]) > (best["key_quality"], best["match_pct"]):
                        best = cand
            if best:
                rels.append(best)
    return rels


def _fact_score(df, prof):
    has_date = any(p["role"] == "date" for p in prof.values())
    n_add = sum(1 for p in prof.values() if p["role"] == "numeric" and p["kind"] == "additive")
    return (3 if has_date else 0) + n_add + np.log10(max(len(df), 1))


# ------------------------------------------------------------------------------ derived columns
def add_derived(df: pd.DataFrame, derived: dict, log: list) -> pd.DataFrame:
    for name, expr in (derived or {}).items():
        try:
            df[name] = df.eval(expr)
            log.append(f"derived column {name} = {expr}")
        except Exception as e:  # pragma: no cover - reported, never fatal
            log.append(f"WARNING could not create derived column {name} = {expr}: {e}")
    return df


def add_bands(tables: dict, profs: dict, log: list, max_bands: int = 4):
    """Add readable band columns (age groups, income terciles ...) for numeric attributes."""
    cands = []
    for t, prof in profs.items():
        for c, p in prof.items():
            if p["role"] == "numeric" and p["kind"] == "attribute" and p["n_unique"] >= 15 and not p.get("geo"):
                pri = 0 if AGE_NAME.search(c) else 1 if re.search(r"income|salary|limit|price", c, re.I) else 2
                cands.append((pri, t, c))
    for pri, t, c in sorted(cands)[:max_bands]:
        s = tables[t][c].astype(float)
        if AGE_NAME.search(c):
            name = f"{c}_Group"
            lo = (np.floor(s / 10) * 10)
            band = lo.astype("Int64").astype(str) + "-" + (lo + 9).astype("Int64").astype(str)
            band = band.where(s.notna(), np.nan)
        else:
            name = f"{c}_Band"
            try:
                q = pd.qcut(s, 3, labels=["1-Low", "2-Medium", "3-High"], duplicates="drop")
            except ValueError:
                continue
            band = q.astype(object)
        tables[t][name] = band
        profs[t][name] = {"dtype": "object", "n_unique": int(band.nunique()), "null_pct": float(band.isna().mean()),
                          "unique_ratio": 0, "top_share": 0.5, "role": "category", "kind": "band", "chartable_dim": True,
                          "outliers_iqr3": 0, "derived_from": c}
        log.append(f"added band column {t}.{name} from {c}")


# ------------------------------------------------------------------------------ date dimension
def build_date_dim(dmin: pd.Timestamp, dmax: pd.Timestamp) -> pd.DataFrame:
    d = pd.DataFrame({"Date": pd.date_range(dmin.normalize(), dmax.normalize(), freq="D")})
    d["Year"] = d.Date.dt.year
    d["Quarter_Num"] = d.Date.dt.quarter
    d["Quarter"] = "Q" + d.Quarter_Num.astype(str)
    d["Month_Num"] = d.Date.dt.month
    d["Month"] = d.Date.dt.strftime("%b")
    d["Year_Month"] = d.Date.dt.strftime("%Y-%m")
    d["Week_Of_Year"] = d.Date.dt.isocalendar().week.astype(int)
    d["Day_Of_Week_Num"] = d.Date.dt.dayofweek + 1
    d["Day_Name"] = d.Date.dt.strftime("%a")
    d["Is_Weekend"] = d.Day_Of_Week_Num.isin([6, 7]).astype(int)
    return d


# ------------------------------------------------------------------------------ naming
def _label(name: str) -> str:
    parts = [p for p in re.sub(r"[^0-9A-Za-z]+", "_", str(name)).split("_") if p]
    return "_".join(p if not p.islower() else p.capitalize() for p in parts) or "Data"


def _rename_tables(model: dict, custom: dict | None) -> dict:
    custom = custom or {}
    mapping = {}
    for t in model["tables"]:
        if t == "Dim_Date":
            continue
        mapping[t] = custom.get(t) or (("Fact_" if t == model["fact"] else "Dim_") + _label(t))
    used = set()
    for k, v in list(mapping.items()):
        base, i = v, 2
        while v in used:
            v, i = f"{base}_{i}", i + 1
        used.add(v)
        mapping[k] = v
    mapping["Dim_Date"] = "Dim_Date"
    model["tables"] = {mapping.get(k, k): v for k, v in model["tables"].items()}
    model["profiles"] = {mapping.get(k, k): v for k, v in model["profiles"].items()}
    model["fact"] = mapping[model["fact"]]
    model["dims"] = [mapping[d] for d in model["dims"]]
    model["isolated"] = [mapping[d] for d in model["isolated"]]
    for r in model["relationships"]:
        r["from_table"], r["to_table"] = mapping.get(r["from_table"], r["from_table"]), mapping.get(r["to_table"], r["to_table"])
    if model.get("date"):
        model["date"]["dim_table"] = "Dim_Date"
    model["table_name_map"] = {k: v for k, v in mapping.items() if k != v}
    return model


# ------------------------------------------------------------------------------ main
def build_model(clean_tables: dict, cfg: dict | None = None) -> dict:
    cfg = cfg or {}
    log: list = []
    tables = {k: v.copy() for k, v in clean_tables.items()}
    tables, append_report = unify_tables(tables, log, cfg)
    profs = {n: profile_table(df, n, cfg) for n, df in tables.items()}
    for n, p in profs.items():
        if "Source_File" in p:
            p["Source_File"]["role"], p["Source_File"]["chartable_dim"] = "meta", False

    rels = detect_relationships(tables, profs, log) if len(tables) > 1 else []

    # fact table selection
    if cfg.get("fact_table") in tables:
        fact = cfg["fact_table"]
    else:
        fact = max(tables, key=lambda n: _fact_score(tables[n], profs[n]))
    # orient relationships so that the fact table is on the "many" side when it is a 1:1 join
    for r in rels:
        if r["one_to_one"] and r["one_table"] == fact:
            r["one_table"], r["one_col"], r["many_table"], r["many_col"] = r["many_table"], r["many_col"], r["one_table"], r["one_col"]
    dims = [t for t in tables if t != fact]

    # derived measures, then bands
    tables[fact] = add_derived(tables[fact], cfg.get("derived"), log)
    profs[fact] = profile_table(tables[fact], fact, cfg)
    if "Source_File" in profs[fact]:
        profs[fact]["Source_File"]["role"], profs[fact]["Source_File"]["chartable_dim"] = "meta", False
    for c in (cfg.get("drop_columns") or []):
        for t in tables:
            if c in tables[t].columns:
                tables[t] = tables[t].drop(columns=[c])
                profs[t].pop(c, None)
                log.append(f"dropped column {t}.{c} (config)")
    add_bands(tables, profs, log, cfg.get("max_bands", 4))

    # blanks in text dimensions become "Unknown" so slicers/charts do not show (Blank)
    for t, prof in profs.items():
        for c, p in prof.items():
            if p["role"] in ("category", "binary_text") and c in tables[t].columns and tables[t][c].isna().any():
                n_na = int(tables[t][c].isna().sum())
                tables[t][c] = tables[t][c].fillna("Unknown")
                log.append(f"{t}.{c}: {n_na:,} blank value(s) labelled 'Unknown'")

    # date dimension
    date_info = None
    date_cols = [c for c, p in profs[fact].items() if p["role"] == "date"]
    if cfg.get("date_column") in date_cols:
        date_col = cfg["date_column"]
    else:
        date_col = max(date_cols, key=lambda c: tables[fact][c].nunique()) if date_cols else None
    if date_col:
        s = tables[fact][date_col]
        key_col = date_col
        if (s.dropna() != s.dropna().dt.normalize()).any():
            key_col = f"{date_col}_Day"
            tables[fact][key_col] = s.dt.normalize()
            profs[fact][key_col] = {**profs[fact][date_col]}
            log.append(f"added {fact}.{key_col} (date without time) as relationship key")
        dd = build_date_dim(s.min(), s.max())
        tables["Dim_Date"] = dd
        profs["Dim_Date"] = profile_table(dd, "Dim_Date", {})
        for c in ("Year", "Quarter_Num", "Month_Num", "Week_Of_Year", "Day_Of_Week_Num"):
            profs["Dim_Date"][c]["role"] = "ordinal" if c == "Year" else "meta"
        date_info = {"fact_column": key_col, "dim_table": "Dim_Date", "dim_column": "Date",
                     "min": s.min().strftime("%Y-%m-%d"), "max": s.max().strftime("%Y-%m-%d"),
                     "n_dates": int(s.nunique()), "span_days": int((s.max() - s.min()).days) + 1}
        diffs = pd.Series(s.dropna().unique()).sort_values().diff().dropna().dt.days
        if len(diffs):
            mode = int(diffs.mode().iloc[0])
            date_info["grain"] = {1: "daily", 7: "weekly"}.get(mode, "monthly" if 28 <= mode <= 31 else f"every {mode} days")
        else:
            date_info["grain"] = "single date"

    relationships = []
    for r in rels:
        relationships.append({"from_table": r["many_table"], "from_col": r["many_col"], "to_table": r["one_table"],
                              "to_col": r["one_col"], "cardinality": "many_to_one", "match_pct": r["match_pct"],
                              "observed_one_to_one": r["one_to_one"]})
    if date_info:
        relationships.append({"from_table": fact, "from_col": date_info["fact_column"], "to_table": "Dim_Date",
                              "to_col": "Date", "cardinality": "many_to_one", "match_pct": 100.0, "observed_one_to_one": False})
    # keep only tables connected to the fact in a single star; others are still loaded but flagged
    connected = {fact} | {r["to_table"] for r in relationships if r["from_table"] == fact}
    isolated = [t for t in tables if t not in connected and t != "Dim_Date"]
    if isolated:
        log.append("tables without a detected relationship to the fact table: " + ", ".join(isolated))

    model = {"tables": tables, "profiles": profs, "fact": fact, "dims": [d for d in dims if d in connected],
             "isolated": isolated, "relationships": relationships, "date": date_info,
             "appends": append_report, "log": log}
    return _rename_tables(model, cfg.get("table_names"))


def flatten(model: dict) -> pd.DataFrame:
    """One wide analysis table: fact LEFT JOIN its dimensions (used for analysis only, never exported to Power BI)."""
    fact = model["tables"][model["fact"]].copy()
    for r in model["relationships"]:
        if r["from_table"] == model["fact"] and r["to_table"] in model["tables"] and r["to_table"] != "Dim_Date":
            dim = model["tables"][r["to_table"]]
            keep = [c for c in dim.columns if c == r["to_col"] or c not in fact.columns]
            dim = dim[keep].drop_duplicates(subset=[r["to_col"]])
            fact = fact.merge(dim, left_on=r["from_col"], right_on=r["to_col"], how="left", suffixes=("", "_dim"))
            if r["to_col"] != r["from_col"] and r["to_col"] in fact.columns:
                fact = fact.drop(columns=[r["to_col"]])
    return fact


def flat_profile(model: dict, flat: pd.DataFrame) -> dict:
    """Merge column profiles of all tables for the flat view."""
    prof = {}
    for t in [model["fact"]] + model["dims"]:
        for c, p in model["profiles"][t].items():
            if c in flat.columns and c not in prof:
                prof[c] = {**p, "table": t}
    return prof
