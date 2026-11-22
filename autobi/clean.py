"""Automatic cleaning: header normalisation, whitespace, numeric / date / text type recovery."""
from __future__ import annotations
import re
import numpy as np
import pandas as pd
from .utils import NA_TOKENS, clean_col_name, is_text, is_num, is_date

DATE_NAME_HINT = re.compile(r"(date|time|timestamp|datetime|_dt$|^dt_|created|updated|_at$|week_start|period_start|month_start|day$)", re.I)
DATE_VALUE_PATTERN = re.compile(
    r"^\s*(\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|\d{1,2}[-/ ][A-Za-z]{3,9}[-/ ,]+\d{2,4}|[A-Za-z]{3,9}[ -]\d{1,2},? \d{2,4})([ T]\d{1,2}:\d{2}(:\d{2})?)?\s*$")

# order matters only for tie-breaking; ambiguity is resolved in _pick_date_format
DATE_FORMATS = [
    "%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d",
    "%d-%m-%Y", "%m-%d-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%d-%m-%Y %H:%M", "%m/%d/%Y %H:%M",
    "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%m/%d/%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S",
    "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%m-%y", "%m/%d/%y", "%d/%m/%y",
]


# ----------------------------------------------------------------------------- numerics
_CURRENCY = re.compile(r"[\$€£₹¥]|\bUSD\b|\bINR\b|\bRs\.?\b|\bEUR\b", re.I)


def parse_numeric(s: pd.Series):
    """Try to turn a text column into numbers ($1,200 / (300) / 12% / 1 234). Returns (series|None, info)."""
    nn = s.dropna().astype(str)
    if nn.empty:
        return None, {}
    sample = nn.head(2000)
    # keep identifiers with leading zeros as text (zip codes, product codes ...)
    if sample.str.fullmatch(r"0\d+").mean() > 0.02:
        return None, {}
    t = nn.str.strip()
    is_pct = t.str.endswith("%").mean() > 0.9
    t = t.str.replace(_CURRENCY, "", regex=True).str.replace("%", "", regex=False).str.strip()
    neg = t.str.fullmatch(r"\(.*\)")
    t = t.str.replace(r"^\((.*)\)$", r"\1", regex=True)
    has_thousands = t.str.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?")
    t = t.where(~has_thousands, t.str.replace(",", "", regex=False))
    t = t.str.replace(r"(?<=\d) (?=\d{3}\b)", "", regex=True)
    num = pd.to_numeric(t, errors="coerce")
    num = num.where(~neg, -num)
    ok = num.notna().mean()
    if ok < 0.97:
        return None, {}
    out = pd.Series(np.nan, index=s.index, dtype="float64")
    out.loc[num.index] = num.values / (100.0 if is_pct else 1.0)
    return out, {"bad_values": int(num.isna().sum()), "percent": bool(is_pct)}


def _tidy_numeric(s: pd.Series) -> pd.Series:
    """Float -> integer dtype when every value is a whole number (keeps NaN as <NA>)."""
    v = s.dropna()
    if len(v) and np.isfinite(v).all() and (np.mod(v, 1) == 0).all() and v.abs().max() < 9e15:
        return s.astype("Int64") if s.isna().any() else s.astype("int64")
    return s.astype("float64")


# ----------------------------------------------------------------------------- dates
def _regularity(dates: pd.Series) -> int:
    u = pd.Series(dates.dropna().unique()).sort_values()
    if len(u) < 3:
        return 10 ** 6
    return int(u.diff().dropna().nunique())


def parse_dates(s: pd.Series, name: str = "", dayfirst: bool | None = None):
    """Detect and parse a text date column. Returns (series|None, info). Resolves dd/mm vs mm/dd ambiguity."""
    nn = s.dropna().astype(str).str.strip()
    if nn.empty:
        return None, {}
    sample = nn.sample(min(len(nn), 300), random_state=0)
    pattern_ok = sample.str.match(DATE_VALUE_PATTERN).mean() > 0.9
    if not pattern_ok:
        return None, {}
    cands = []
    for fmt in DATE_FORMATS:
        parsed = pd.to_datetime(nn, format=fmt, errors="coerce")
        ratio = parsed.notna().mean()
        if ratio >= 0.97:
            cands.append((fmt, ratio, parsed))
    if not cands:
        return None, {}
    best_ratio = max(c[1] for c in cands)
    cands = [c for c in cands if c[1] >= best_ratio - 1e-9]
    ambiguous = False
    if len(cands) > 1:
        # different formats parse everything -> day/month ambiguity. Prefer the more regular calendar cadence.
        scored = sorted(cands, key=lambda c: (_regularity(c[2]), c[2].nunique()))
        if _regularity(scored[0][2]) == _regularity(scored[1][2]):
            ambiguous = True
            pref = [c for c in cands if (c[0].startswith("%d") == (dayfirst is not False))]
            scored = pref or scored
        cands = scored
    fmt, _, parsed = cands[0]
    out = pd.Series(pd.NaT, index=s.index, dtype="datetime64[ns]")
    out.loc[parsed.index] = parsed.values
    return out, {"format": fmt, "ambiguous": ambiguous, "unparsed": int(parsed.isna().sum())}


# ----------------------------------------------------------------------------- main entry
def clean_table(df: pd.DataFrame, name: str, cfg: dict | None = None):
    cfg = cfg or {}
    log: dict = {"table": name, "rows_in": int(len(df)), "cols_in": int(df.shape[1]), "warnings": [], "actions": []}
    df = df.copy().reset_index(drop=True)

    # 1. headers
    seen: set = set()
    mapping = {}
    for c in df.columns:
        mapping[c] = clean_col_name(c, seen)
    renamed = {k: v for k, v in mapping.items() if str(k) != v}
    df.columns = list(mapping.values())
    if renamed:
        log["renamed_columns"] = renamed

    # 2. drop empty rows / columns (and pandas "Unnamed" artefacts)
    for c in list(df.columns):
        if is_text(df[c]):
            df[c] = df[c].astype("object")
    df = df.replace(r"^\s*$", np.nan, regex=True)
    drop_cols = [c for c in df.columns if df[c].isna().all()]
    if drop_cols:
        df = df.drop(columns=drop_cols)
        log["actions"].append(f"dropped {len(drop_cols)} fully-empty column(s): {drop_cols}")
    n0 = len(df)
    df = df.dropna(how="all")
    if len(df) < n0:
        log["actions"].append(f"dropped {n0 - len(df)} fully-empty row(s)")

    ws_fixed, coerced, dates, case_merged, nonnum = {}, {}, {}, {}, {}
    for c in list(df.columns):
        s = df[c]
        if is_date(s):
            dates[c] = {"format": "native datetime", "ambiguous": False}
            continue
        if pd.api.types.is_bool_dtype(s):
            df[c] = s.astype("int64")
            continue
        if is_num(s):
            df[c] = _tidy_numeric(s)
            continue
        # ---- text column
        s = s.astype("object").where(s.notna(), None)
        txt = s.dropna().astype(str)
        changed = int((txt != txt.str.strip()).sum() + txt.str.contains(r"\s{2,}", regex=True).sum())
        txt_clean = txt.str.replace(r"\s+", " ", regex=True).str.strip()
        s2 = pd.Series(np.nan, index=s.index, dtype="object")
        s2.loc[txt_clean.index] = txt_clean.values
        s2 = s2.where(~s2.astype(str).str.lower().isin(NA_TOKENS), np.nan)
        if changed:
            ws_fixed[c] = changed
        # numbers hiding in text?
        num, info = parse_numeric(s2)
        if num is not None:
            df[c] = _tidy_numeric(num)
            coerced[c] = info
            if info.get("bad_values"):
                nonnum[c] = info["bad_values"]
            continue
        # dates hiding in text?
        hinted = bool(DATE_NAME_HINT.search(c))
        dt, dinfo = parse_dates(s2, c, cfg.get("dayfirst"))
        if dt is not None and (hinted or dt.notna().mean() > 0.97):
            df[c] = dt
            dates[c] = dinfo
            continue
        # plain text - merge case variants ("male" / "Male" / "MALE")
        vc = s2.value_counts()
        if 0 < len(vc) <= 500:
            low = pd.Series(vc.index.astype(str), index=vc.index).str.lower()
            canon = {}
            for variant, key in zip(vc.index, low):
                cur = canon.get(key)
                # prefer the most frequent variant, but favour a properly capitalised one over ALL-CAPS / all-lower
                if cur is None or (not (cur == cur.title()) and variant == variant.title() and vc[variant] >= 0.25 * vc[cur]):
                    canon[key] = variant
            mapper = {v: canon[k] for v, k in zip(vc.index, low)}
            merged = sum(1 for v, tgt in mapper.items() if v != tgt)
            if merged:
                s2 = s2.map(lambda v: mapper.get(v, v) if isinstance(v, str) else v)
                case_merged[c] = merged
        df[c] = s2

    if ws_fixed:
        log["whitespace_fixed"] = ws_fixed
        log["actions"].append("trimmed stray spaces in " + ", ".join(f"{k} ({v:,} cells)" for k, v in ws_fixed.items()))
    if coerced:
        log["numeric_recovered"] = list(coerced)
    if nonnum:
        log["warnings"].append("non-numeric values set to null: " + ", ".join(f"{k}={v}" for k, v in nonnum.items()))
    if dates:
        log["dates"] = dates
        for k, v in dates.items():
            if v.get("ambiguous"):
                log["warnings"].append(f"date column {k}: day/month order ambiguous - assumed "
                                       f"{'day-first' if v['format'].startswith('%d') else 'month-first'} (set dayfirst in config to override)")
            if v.get("unparsed"):
                log["warnings"].append(f"date column {k}: {v['unparsed']} value(s) could not be parsed -> null")
    if case_merged:
        log["actions"].append("merged inconsistent capitalisation in " + ", ".join(case_merged))

    # 3. exact duplicate rows
    dup = int(df.duplicated().sum())
    if dup:
        df = df.drop_duplicates().reset_index(drop=True)
        log["actions"].append(f"removed {dup} exact duplicate row(s)")
    log["duplicates_removed"] = dup
    df = df.reset_index(drop=True)
    log["rows_out"], log["cols_out"] = int(len(df)), int(df.shape[1])
    return df, log
