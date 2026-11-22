"""Semantic profiling: decide what every column *is* (id, date, measure, dimension, flag ...)."""
from __future__ import annotations
import re
import numpy as np
import pandas as pd
from .utils import is_text, is_num, is_date

ID_NAME = re.compile(r"(^|_)(id|key|uuid|guid|num|no|number|code|ref|sku|idx|index)($|_)", re.I)
NON_ADDITIVE = re.compile(
    r"(age|score|rating|ratio|rate|pct|percent|utili[sz]ation|limit|income|salary|tenure|dependent|satisfaction|grade|rank|"
    r"temperature|lat|lon|latitude|longitude|height|weight|year|zip|postal|price|margin|discount|cost_per|per_|avg|average|mean|median|"
    r"days|duration|distance|speed)", re.I)
ADDITIVE = re.compile(
    r"(amt|amount|revenue|sales|spend|fee|cost|interest|balance|profit|total|qty|quantity|count|ct$|_ct|vol|volume|units|"
    r"orders|returns|clicks|impressions|conversions|payment|charge|tax|gmv|mrp|margin_amt|income_amt|expense)", re.I)
RATE_NAME = re.compile(r"(ratio|rate|pct|percent|utili[sz]ation|share|proportion)", re.I)
TARGET_NAME = re.compile(r"(delinq|churn|default|fraud|attrition|cancel|return(ed)?$|is_return|risk|bad_|target|label|outcome|converted$|"
                         r"^is_|flag$)", re.I)
GEO_NAME = re.compile(r"(state|country|region|city|zone|district|province|county|geo)", re.I)
ZIP_NAME = re.compile(r"(zip|postal|pincode|pin_code)", re.I)
AGE_NAME = re.compile(r"(^|_)age($|_)", re.I)


def profile_table(df: pd.DataFrame, name: str, cfg: dict | None = None) -> dict:
    """Return {column: {role, kind, dtype, n_unique, null_pct, ...}} for one cleaned table."""
    cfg = cfg or {}
    n = len(df)
    cols = {}
    for c in df.columns:
        s = df[c]
        nn = s.dropna()
        nuniq = int(nn.nunique())
        info = {"dtype": str(s.dtype), "n_unique": nuniq, "null_pct": float(s.isna().mean()) if n else 0.0,
                "unique_ratio": (nuniq / len(nn)) if len(nn) else 0.0}
        top_share = float(nn.value_counts(normalize=True).iloc[0]) if len(nn) else 0.0
        info["top_share"] = top_share
        role, kind = "category", None

        if is_date(s):
            role = "date"
        elif nuniq <= 1:
            role = "constant"
        elif is_num(s):
            vals = nn.astype(float)
            is_int = bool((np.mod(vals, 1) == 0).all())
            uniq = set(vals.unique().tolist()) if nuniq <= 2 else None
            if uniq is not None and uniq <= {0.0, 1.0}:
                role = "binary"
            elif is_int and (ID_NAME.search(c) and info["unique_ratio"] > 0.9 or (info["unique_ratio"] > 0.98 and n > 50 and not NON_ADDITIVE.search(c))):
                role = "id"
            elif ZIP_NAME.search(c):
                role = "category"
                info["geo"] = True
            elif is_int and nuniq <= 12:
                role = "ordinal"  # e.g. satisfaction 1-5, dependents 0-5: behaves like a dimension
            else:
                role = "numeric"
                if RATE_NAME.search(c) and vals.min() >= 0 and vals.max() <= 1.0000001:
                    kind = "rate"
                elif NON_ADDITIVE.search(c) and not ADDITIVE.search(c):
                    kind = "attribute"
                elif ADDITIVE.search(c):
                    kind = "additive"
                else:
                    kind = "additive" if vals.min() >= 0 else "attribute"
                if kind == "attribute" and vals.min() >= 0 and vals.max() <= 1.0000001 and nuniq > 10:
                    kind = "rate"
                info["skew"] = float(vals.skew()) if len(vals) > 2 else 0.0
        else:  # text
            lens = nn.astype(str).str.len()
            if ID_NAME.search(c) and info["unique_ratio"] > 0.9 or (info["unique_ratio"] > 0.98 and n > 50):
                role = "id"
            elif info["unique_ratio"] > 0.5 and lens.mean() > 25:
                role = "text"
            elif nuniq > max(200, 0.5 * n):
                role = "id" if ID_NAME.search(c) else "text"
            else:
                role = "category"
                if set(v.lower() for v in nn.astype(str).unique()) <= {"yes", "no", "y", "n", "true", "false"}:
                    role, kind = "binary_text", "yesno"
                if GEO_NAME.search(c):
                    info["geo"] = True
        info["role"], info["kind"] = role, kind
        # a dimension is usable in charts when it has a sensible cardinality & is not (near) constant
        info["chartable_dim"] = bool(role in ("category", "ordinal", "binary", "binary_text") and 2 <= nuniq <= 40 and top_share < 0.95)
        info["outliers_iqr3"] = 0
        if role == "numeric" and len(nn) > 20:
            q1, q3 = nn.quantile([0.25, 0.75])
            iqr = q3 - q1
            if iqr > 0:
                info["outliers_iqr3"] = int(((nn < q1 - 3 * iqr) | (nn > q3 + 3 * iqr)).sum())
        cols[c] = info

    # config overrides --------------------------------------------------------
    for c, role in (cfg.get("roles") or {}).items():
        if c in cols:
            cols[c]["role"] = role
    for c in (cfg.get("agg_overrides") or {}):
        if c in cols:
            cols[c]["kind"] = "additive" if cfg["agg_overrides"][c] == "sum" else "attribute"
    return cols


def quality_flags(df: pd.DataFrame, prof: dict, name: str) -> list[dict]:
    """Human-readable data quality findings for one table."""
    flags = []
    n = len(df)
    for c, p in prof.items():
        if p["null_pct"] > 0:
            sev = "high" if p["null_pct"] > 0.3 else "medium" if p["null_pct"] > 0.05 else "low"
            flags.append({"table": name, "column": c, "type": "missing", "severity": sev,
                          "detail": f"{p['null_pct']*100:.1f}% missing ({int(round(p['null_pct']*n)):,} rows)"
                                    + (" - labelled 'Unknown' in the clean data" if p["role"] in ("category", "binary_text") else "")})
        if p["role"] == "constant":
            flags.append({"table": name, "column": c, "type": "constant", "severity": "low",
                          "detail": "single value in every row - carries no information (hidden from slicers)"})
        elif p["role"] in ("category", "ordinal") and p["top_share"] >= 0.95 and p["n_unique"] > 1:
            flags.append({"table": name, "column": c, "type": "near_constant", "severity": "medium",
                          "detail": f"{p['top_share']*100:.1f}% of rows share one value - unusable as a dimension / geo key"})
        if p["outliers_iqr3"]:
            flags.append({"table": name, "column": c, "type": "outliers", "severity": "low",
                          "detail": f"{p['outliers_iqr3']:,} extreme values (beyond 3xIQR) - kept, not removed"})
        if p["role"] == "id":
            dup = int(df[c].duplicated().sum())
            if dup:
                flags.append({"table": name, "column": c, "type": "duplicate_id", "severity": "high",
                              "detail": f"{dup:,} repeated identifiers"})
    return flags
