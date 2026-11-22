from __future__ import annotations
import re
import unicodedata
import numpy as np
import pandas as pd

NA_TOKENS = {"", "na", "n/a", "nan", "null", "none", "nil", "-", "--", "?", "#n/a", "#na", "#null!", "undefined"}


def is_text(s: pd.Series) -> bool:
    return pd.api.types.is_string_dtype(s) or pd.api.types.is_object_dtype(s)


def is_num(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s) and not pd.api.types.is_bool_dtype(s)


def is_date(s: pd.Series) -> bool:
    return pd.api.types.is_datetime64_any_dtype(s)


def norm_name(name: str) -> str:
    """Lower-case alphanumeric token used to compare column names across files."""
    return re.sub(r"[^a-z0-9]+", "", str(name).lower())


def clean_col_name(name, seen: set) -> str:
    s = re.sub(r"\s+", " ", str(name).replace("\ufeff", "")).strip()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^0-9A-Za-z]+", "_", s).strip("_")
    if not s:
        s = "Column"
    if s[0].isdigit():
        s = "C_" + s
    base, i = s, 2
    while s.lower() in seen:
        s = f"{base}_{i}"
        i += 1
    seen.add(s.lower())
    return s


def pretty(name: str) -> str:
    return re.sub(r"\s+", " ", str(name).replace("_", " ")).strip()


def human(n, kind: str = "num") -> str:
    """Compact human readable number (K / M / B)."""
    if n is None or (isinstance(n, float) and (np.isnan(n) or np.isinf(n))):
        return "n/a"
    if kind == "pct":
        return f"{n * 100:.1f}%"
    a = abs(n)
    if a >= 1e9:
        return f"{n / 1e9:.2f}B"
    if a >= 1e6:
        return f"{n / 1e6:.2f}M"
    if a >= 1e4:
        return f"{n / 1e3:.1f}K"
    if float(n).is_integer():
        return f"{int(n):,}"
    return f"{n:,.2f}"


def safe_div(a, b):
    try:
        return float(a) / float(b) if b not in (0, None) and not pd.isna(b) else float("nan")
    except Exception:
        return float("nan")


def jsonable(o):
    """Make numpy / pandas objects JSON serialisable."""
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return None if np.isnan(o) or np.isinf(o) else float(o)
    if isinstance(o, float):
        return None if np.isnan(o) or np.isinf(o) else o
    if isinstance(o, pd.Timestamp):
        return o.strftime("%Y-%m-%d")
    if isinstance(o, np.bool_):
        return bool(o)
    if isinstance(o, pd.DataFrame):
        return jsonable(o.to_dict(orient="records"))
    if o is pd.NaT:
        return None
    return o
