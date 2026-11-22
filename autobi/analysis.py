"""Automatic analysis that works on any tabular data (uses the semantic roles from profile.py)."""
from __future__ import annotations
import re
import warnings
import numpy as np
import pandas as pd
from scipy import stats
from .utils import pretty, human, safe_div, is_num
from .profile import TARGET_NAME

PRIMARY_PRIORITY = ["revenue", "net_sales", "sales", "gmv", "profit", "income_earned", "interest", "amount", "amt", "spend",
                    "total", "value", "price", "income"]


def _entity_label(entity: str) -> str:
    base = re.sub(r"[ _](num|id|no|number|key|code)$", "", pretty(entity), flags=re.I).strip().title() or "Records"
    return f"Unique {base}s" if not base.endswith("s") else f"Unique {base}"


def lab(prefix: str, col: str) -> str:
    """'Total' + 'Total_Trans_Amt' -> 'Total Trans Amt' (no stuttering)."""
    name = pretty(col)
    return name if name.lower().startswith(prefix.lower() + " ") else f"{prefix} {name}"


def fmt_p(p) -> str:
    if p is None or not np.isfinite(p):
        return "n/a"
    return "p<0.001" if p < 0.001 else f"p={p:.3f}"


# ============================================================================== selection helpers
def pick_primary(flat: pd.DataFrame, fprof: dict, cfg: dict):
    if cfg.get("primary_measure") in flat.columns:
        return cfg["primary_measure"]
    cands = [c for c, p in fprof.items() if p["role"] == "numeric" and p["kind"] == "additive"]
    if not cands:
        cands = [c for c, p in fprof.items() if p["role"] == "numeric"]
    if not cands:
        return None
    for key in PRIMARY_PRIORITY:
        hit = [c for c in cands if key in c.lower()]
        if hit:
            return max(hit, key=lambda c: abs(flat[c].astype(float)).sum())
    return max(cands, key=lambda c: abs(flat[c].astype(float)).sum())


def pick_target(flat: pd.DataFrame, fprof: dict, cfg: dict):
    if cfg.get("target") == "none":
        return None
    if cfg.get("target") in flat.columns:
        return cfg["target"]
    for c, p in fprof.items():
        if p["role"] == "binary" and TARGET_NAME.search(c):
            rate = float(flat[c].astype(float).mean())
            if 0.005 <= rate <= 0.6:
                return c
    return None


def pick_entity(model: dict) -> str | None:
    prof = model["profiles"][model["fact"]]
    ids = [c for c, p in prof.items() if p["role"] == "id"]
    pref = [c for c in ids if re.search(r"(client|customer|user|account|member|cust)", c, re.I)]
    return (pref or ids or [None])[0]


# ============================================================================== KPI specs
def build_kpi_specs(model: dict, fprof: dict, primary, target, entity, cfg: dict) -> list[dict]:
    fact = model["fact"]
    specs = [{"key": "records", "label": "Records", "table": fact, "column": None, "agg": "rows", "fmt": "int"}]
    if entity:
        specs.append({"key": "entities", "label": _entity_label(entity),
                      "table": fact, "column": entity, "agg": "distinct", "fmt": "int"})
    order = []
    if primary:
        order.append(primary)
    order += [c for c, p in fprof.items() if p["role"] == "numeric" and p["kind"] == "additive" and c != primary]
    for c in order[:7]:
        specs.append({"key": f"sum_{c}", "label": lab("Total", c), "table": fprof[c]["table"], "column": c, "agg": "sum", "fmt": "num"})
    if primary:
        specs.append({"key": f"avg_{primary}", "label": f"{lab('Avg', primary)} per Record", "table": fprof[primary]["table"],
                      "column": primary, "agg": "avg", "fmt": "num"})
    for c, p in fprof.items():
        if p["role"] == "numeric" and p["kind"] in ("rate", "attribute") and len([s for s in specs if s["agg"] == "avg"]) < 6:
            specs.append({"key": f"avg_{c}", "label": lab("Avg", c), "table": p["table"], "column": c, "agg": "avg",
                          "fmt": "pct" if p["kind"] == "rate" else "num"})
        elif p["role"] == "binary" and len([s for s in specs if s["agg"] == "rate"]) < 3:
            specs.append({"key": f"rate_{c}", "label": f"{pretty(c)} Rate" if not pretty(c).lower().endswith("rate") else pretty(c), "table": p["table"], "column": c, "agg": "rate", "fmt": "pct"})
    return specs


def eval_kpi(spec: dict, flat: pd.DataFrame):
    c, a = spec["column"], spec["agg"]
    if a == "rows":
        return int(len(flat))
    if a == "distinct":
        return int(flat[c].nunique())
    s = flat[c].astype(float)
    return float(s.sum() if a == "sum" else s.mean())


# ============================================================================== breakdowns
def _group_table(flat, dim, measure, target=None, order_by_label=False):
    g = flat.groupby(dim, observed=True, dropna=False)
    out = pd.DataFrame({"records": g.size()})
    if measure:
        m = flat[measure].astype(float)
        out["total"] = m.groupby(flat[dim], observed=True, dropna=False).sum()
        out["avg_per_record"] = m.groupby(flat[dim], observed=True, dropna=False).mean()
        out["share"] = out["total"] / out["total"].sum() if out["total"].sum() else np.nan
    if target:
        out["target_rate"] = flat[target].astype(float).groupby(flat[dim], observed=True, dropna=False).mean()
    out = out.reset_index().rename(columns={dim: "group"})
    out["group"] = out["group"].astype(str)
    out = out.sort_values("group" if order_by_label else ("total" if measure else "records"), ascending=order_by_label)
    return out.reset_index(drop=True)


def _effect(flat, dim, measure):
    """eta-squared + Kruskal-Wallis p for the measure across groups of a dimension."""
    y = flat[measure].astype(float)
    ok = y.notna() & flat[dim].notna()
    y, d = y[ok], flat.loc[ok, dim]
    if y.nunique() < 3 or d.nunique() < 2:
        return np.nan, np.nan
    grp = y.groupby(d)
    ssb = (grp.count() * (grp.mean() - y.mean()) ** 2).sum()
    sst = ((y - y.mean()) ** 2).sum()
    eta = float(ssb / sst) if sst else np.nan
    try:
        p = float(stats.kruskal(*[g.values for _, g in grp if len(g) > 1])[1])
    except Exception:
        p = np.nan
    return eta, p


def breakdowns(flat, fprof, primary, target, max_dims=8):
    dims = [c for c, p in fprof.items() if p["chartable_dim"] and c != target and p["role"] != "binary"]
    dims += [c for c, p in fprof.items() if p["role"] == "binary" and p["chartable_dim"] and c != target and c not in dims][:3]
    out = []
    for d in dims:
        ordered = fprof[d]["role"] == "ordinal" or fprof[d].get("kind") == "band" or bool(re.search(r"(qtr|quarter|month|year)", d, re.I))
        tbl = _group_table(flat, d, primary, target, order_by_label=ordered)
        eta, p = _effect(flat, d, primary) if primary else (np.nan, np.nan)
        out.append({"dim": d, "table": tbl, "eta2": eta, "p_value": p, "ordered": ordered, "n_groups": int(len(tbl))})
    out.sort(key=lambda r: (-(r["eta2"]) if not np.isnan(r["eta2"]) else 0))
    return out[:max_dims] if max_dims else out


# ============================================================================== time series & forecast
def _holt(y, alpha, beta, phi):
    level, trend = y[0], y[1] - y[0]
    sse = 0.0
    fitted = [y[0]]
    for t in range(1, len(y)):
        f = level + phi * trend
        fitted.append(f)
        sse += (y[t] - f) ** 2
        new_level = alpha * y[t] + (1 - alpha) * f
        trend = beta * (new_level - level) + (1 - beta) * phi * trend
        level = new_level
    return sse, level, trend, np.array(fitted)


def holt_forecast(y: np.ndarray, h: int, phi: float = 0.9):
    best = None
    for a in (0.1, 0.2, 0.3, 0.5, 0.7, 0.9):
        for b in (0.05, 0.1, 0.2, 0.4):
            sse, lv, tr, fit = _holt(y, a, b, phi)
            if best is None or sse < best[0]:
                best = (sse, lv, tr, fit, a, b)
    sse, lv, tr, fit, a, b = best
    fc = np.array([lv + sum(phi ** i for i in range(1, k + 1)) * tr for k in range(1, h + 1)])
    sigma = float(np.sqrt(sse / max(len(y) - 1, 1)))
    band = 1.96 * sigma * np.sqrt(np.arange(1, h + 1))
    return fc, fc - band, fc + band, fit, {"alpha": a, "beta": b, "phi": phi}


def time_analysis(flat, date_col, primary, date_info) -> dict | None:
    if not date_col or not primary:
        return None
    df = flat[[date_col, primary]].dropna(subset=[date_col]).copy()
    df[primary] = df[primary].astype(float)
    n_dates = df[date_col].nunique()
    freq_label = date_info.get("grain", "")
    if n_dates > 120:
        per = df[date_col].dt.to_period("M")
        ts = df.groupby(per)[primary].agg(["sum", "size"])
        ts.index = ts.index.to_timestamp()
        freq_label = "monthly"
        step = pd.DateOffset(months=1)
    else:
        ts = df.groupby(date_col)[primary].agg(["sum", "size"])
        days = pd.Series(ts.index).diff().dt.days.dropna()
        step = pd.Timedelta(days=int(days.mode().iloc[0]) if len(days) else 7)
    ts.columns = ["value", "records"]
    ts = ts.sort_index()
    res = {"freq": freq_label, "series": ts.reset_index().rename(columns={ts.index.name or "index": "period"})}
    res["series"].columns = ["period", "value", "records"]
    # partial last period?
    partial = bool(len(ts) > 4 and ts["records"].iloc[-1] < 0.5 * ts["records"].iloc[:-1].median())
    core = ts.iloc[:-1] if partial else ts
    res["partial_last_period"] = partial
    y = core["value"].values.astype(float)
    n = len(y)
    res["n_periods"] = n
    if n >= 6:
        x = np.arange(n)
        lr = stats.linregress(x, y)
        res["trend"] = {"slope": float(lr.slope), "pct_per_period": float(lr.slope / y.mean()) if y.mean() else np.nan,
                        "r2": float(lr.rvalue ** 2), "p_value": float(lr.pvalue)}
        half = n // 2
        res["first_vs_second_half"] = {"first": float(y[:half].mean()), "second": float(y[half:].mean()),
                                       "change": safe_div(y[half:].mean() - y[:half].mean(), y[:half].mean())}
        med = np.median(y)
        mad = np.median(np.abs(y - med))
        if mad > 0:
            z = 0.6745 * (y - med) / mad
            idx = np.where(np.abs(z) > 3.5)[0]
            res["anomalies"] = [{"period": core.index[i], "value": float(y[i]), "robust_z": float(z[i])} for i in idx]
        else:
            res["anomalies"] = []
        res["peak"] = {"period": core.index[int(np.argmax(y))], "value": float(y.max())}
        res["trough"] = {"period": core.index[int(np.argmin(y))], "value": float(y.min())}
        res["volatility_cv"] = float(y.std() / y.mean()) if y.mean() else np.nan
    # forecast
    if n >= 12:
        h = int(min(8, max(2, n // 6)))
        test = max(3, int(round(n * 0.2)))
        fc_bt, _, _, _, _ = holt_forecast(y[:-test], test)
        actual = y[-test:]
        mape = lambda f: float(np.mean(np.abs((actual - f) / np.where(actual == 0, np.nan, actual))))  # noqa: E731
        res["backtest"] = {"holdout_periods": test, "holt_mape": mape(fc_bt), "naive_mape": mape(np.repeat(y[:-test][-1], test)),
                           "mean_mape": mape(np.repeat(y[:-test].mean(), test))}
        fc, lo, hi, fit, par = holt_forecast(y, h)
        idx = [core.index[-1] + step * (i + 1) for i in range(h)]
        res["forecast"] = pd.DataFrame({"period": idx, "forecast": fc, "lower": lo, "upper": hi})
        res["forecast_params"] = par
    return res


# ============================================================================== correlations
def correlations(flat, fprof, derived=None):
    derived = derived or {}
    comp = {d: set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", expr)) for d, expr in derived.items()}
    cols = [c for c, p in fprof.items() if p["role"] in ("numeric", "ordinal") and p["n_unique"] > 3][:30]
    if len(cols) < 2:
        return None
    X = flat[cols].astype(float)
    pear, spear = X.corr(method="pearson"), X.corr(method="spearman")
    pairs = []
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            r = pear.loc[a, b]
            trivial = ((a in comp and b in comp[a]) or (b in comp and a in comp[b])
                       or (a in comp and b in comp and bool(comp[a] & comp[b])))
            if np.isfinite(r) and not trivial:
                pairs.append({"a": a, "b": b, "pearson": float(r), "spearman": float(spear.loc[a, b])})
    pairs.sort(key=lambda d: -abs(d["pearson"]))
    return {"columns": cols, "matrix": pear, "pairs": pairs[:15]}


# ============================================================================== target / risk drivers
def _cramers_v(ct: pd.DataFrame):
    chi2, p, _, _ = stats.chi2_contingency(ct, correction=False)
    n = ct.values.sum()
    k = min(ct.shape) - 1
    return float(np.sqrt(chi2 / (n * k))) if n and k else np.nan, float(p)


def target_by_period(flat, target, date_col):
    if not date_col or date_col not in flat:
        return None
    d = flat[date_col]
    key = d if d.nunique() <= 120 else d.dt.to_period("M").dt.to_timestamp()
    ct = pd.crosstab(key, flat[target].astype(int))
    if ct.shape[1] < 2 or ct.shape[0] < 4:
        return None
    v, p = _cramers_v(ct)
    tbl = pd.DataFrame({"period": ct.index, "n": ct.sum(axis=1).values, "positives": ct[1].values})
    tbl["rate"] = tbl["positives"] / tbl["n"]
    ok = tbl[tbl["n"] >= 30].sort_values("rate", ascending=False)
    return {"table": tbl.reset_index(drop=True), "cramers_v": v, "p_value": p,
            "top": ok.head(3).to_dict("records"), "bottom": ok.tail(3).to_dict("records")}


def target_analysis(flat, fprof, target, seed=42, date_col=None, exclude=()):
    y = flat[target].astype(float)
    res = {"target": target, "rate": float(y.mean()), "positives": int(y.sum()), "n": int(len(y)), "segments": [], "numeric": []}
    for d, p in fprof.items():
        if d == target or not p["chartable_dim"]:
            continue
        ct = pd.crosstab(flat[d].astype(str), y)
        if ct.shape[0] < 2 or ct.shape[1] < 2:
            continue
        v, pv = _cramers_v(ct)
        rates = (ct[1.0] / ct.sum(axis=1)) if 1.0 in ct.columns else None
        if rates is None:
            continue
        sizes = ct.sum(axis=1)
        ok = sizes[sizes >= max(30, 0.01 * len(y))].index
        r_ok = rates.loc[ok]
        if r_ok.empty:
            continue
        hi, lo = r_ok.idxmax(), r_ok.idxmin()
        res["segments"].append({"dim": d, "cramers_v": v, "p_value": pv, "highest": str(hi), "highest_rate": float(r_ok[hi]),
                                "highest_n": int(sizes[hi]), "lowest": str(lo), "lowest_rate": float(r_ok[lo]),
                                "lift": float(r_ok[hi] / res["rate"]) if res["rate"] else np.nan})
    res["segments"].sort(key=lambda d: -(d["cramers_v"] if np.isfinite(d["cramers_v"]) else 0))
    sample = flat if len(flat) <= 20000 else flat.sample(20000, random_state=seed)
    ys = sample[target].astype(float)
    for c, p in fprof.items():
        if c == target or p["role"] not in ("numeric", "ordinal") or p["n_unique"] < 4:
            continue
        x = sample[c].astype(float)
        ok = x.notna()
        a, b = x[ok & (ys == 1)], x[ok & (ys == 0)]
        if len(a) < 10 or len(b) < 10:
            continue
        try:
            u, pv = stats.mannwhitneyu(a, b, alternative="two-sided")
        except Exception:
            continue
        auc = u / (len(a) * len(b))
        res["numeric"].append({"column": c, "mean_target": float(a.mean()), "mean_other": float(b.mean()),
                               "auc": float(max(auc, 1 - auc)), "p_value": float(pv)})
    res["numeric"].sort(key=lambda d: -d["auc"])
    try:
        res["by_period"] = target_by_period(flat, target, date_col)
    except Exception as e:
        res["by_period"] = None
        res.setdefault("warnings", []).append(f"time-risk skipped: {e}")
    res["model"] = _driver_model(flat, fprof, target, seed, exclude)
    return res


def _driver_model(flat, fprof, target, seed, exclude=()):
    from sklearn.ensemble import HistGradientBoostingClassifier
    from sklearn.inspection import permutation_importance
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import StratifiedKFold, train_test_split
    y = flat[target].astype(int).values
    if y.sum() < 30 or (len(y) - y.sum()) < 30:
        return {"skipped": "too few positive/negative cases to model"}
    feats, cat_mask = [], []
    X = pd.DataFrame(index=flat.index)
    for c, p in fprof.items():
        if c == target or c in exclude or p["role"] in ("id", "text", "constant", "meta", "date"):
            continue
        if p["role"] in ("numeric", "ordinal", "binary"):
            col = flat[c].astype(float)
            if col.notna().sum() > 10 and abs(np.corrcoef(col.fillna(col.median()), y)[0, 1]) > 0.95:
                continue  # leakage guard
            X[c] = col
            cat_mask.append(False)
            feats.append(c)
        elif p["chartable_dim"] or p["role"] in ("category", "binary_text"):
            if p["n_unique"] > 200:
                continue
            X[c] = pd.factorize(flat[c].astype(str))[0]
            cat_mask.append(True)
            feats.append(c)
    if len(feats) < 2:
        return {"skipped": "not enough usable features"}
    mk = lambda: HistGradientBoostingClassifier(max_iter=120, learning_rate=0.08, max_depth=4, categorical_features=cat_mask,  # noqa: E731
                                                 random_state=seed, early_stopping=False)
    aucs = []
    for tr, te in StratifiedKFold(5, shuffle=True, random_state=seed).split(X, y):
        m = mk().fit(X.iloc[tr], y[tr])
        aucs.append(roc_auc_score(y[te], m.predict_proba(X.iloc[te])[:, 1]))
    Xtr, Xte, ytr, yte = train_test_split(X, y, test_size=0.25, stratify=y, random_state=seed)
    m = mk().fit(Xtr, ytr)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        pi = permutation_importance(m, Xte, yte, scoring="roc_auc", n_repeats=5, random_state=seed, n_jobs=1)
    imp = sorted(zip(feats, pi.importances_mean, pi.importances_std), key=lambda t: -t[1])[:10]
    auc = float(np.mean(aucs))
    verdict = ("no usable predictive signal (AUC ~ coin-flip)" if auc < 0.55 else "weak signal" if auc < 0.65 else
               "moderate signal" if auc < 0.75 else "strong signal")
    return {"cv_auc_mean": auc, "cv_auc_std": float(np.std(aucs)), "verdict": verdict, "n_features": len(feats),
            "importance": [{"feature": f, "auc_drop": float(m_), "std": float(s_), "significant": bool(m_ > 2 * s_ and m_ > 0.002)}
                           for f, m_, s_ in imp]}


# ============================================================================== segmentation
def segmentation(flat, fprof, primary, seed=42, exclude=()):
    from sklearn.cluster import KMeans
    from sklearn.metrics import silhouette_score
    from sklearn.preprocessing import StandardScaler
    cols = [c for c, p in fprof.items() if p["role"] in ("numeric", "ordinal") and p["n_unique"] > 3 and c not in exclude][:15]
    if len(cols) < 2 or len(flat) < 100:
        return None
    X = flat[cols].astype(float)
    X = X.fillna(X.median())
    for c in cols:
        if X[c].min() >= 0 and abs(X[c].skew()) > 2:
            X[c] = np.log1p(X[c])
    Z = StandardScaler().fit_transform(X)
    samp = np.random.RandomState(seed).choice(len(Z), size=min(len(Z), 4000), replace=False)
    best = None
    for k in range(2, 7):
        km = KMeans(n_clusters=k, n_init=5, random_state=seed).fit(Z[samp])
        sil = silhouette_score(Z[samp], km.labels_, sample_size=min(3000, len(samp)), random_state=seed)
        if best is None or sil > best[0]:
            best = (sil, k, km)
    sil, k, km = best
    labels = km.predict(Z)
    prof = pd.DataFrame(flat[cols].astype(float))
    prof["_seg"] = labels
    glob_mean, glob_std = prof[cols].mean(), prof[cols].std().replace(0, np.nan)
    segs = []
    for s in range(k):
        sub = prof[prof["_seg"] == s]
        zs = ((sub[cols].mean() - glob_mean) / glob_std).dropna()
        top = zs.reindex(zs.abs().sort_values(ascending=False).index)[:3]
        name = " / ".join(f"{'High' if v > 0 else 'Low'} {pretty(c)}" for c, v in top.items()) or f"Segment {s + 1}"
        row = {"segment": s + 1, "name": name, "size": int(len(sub)), "share": float(len(sub) / len(flat)),
               "drivers": {c: float(v) for c, v in top.items()}}
        if primary:
            row["avg_primary"] = float(flat.loc[sub.index, primary].astype(float).mean())
        segs.append(row)
    return {"k": k, "silhouette": float(sil), "features": cols, "segments": segs, "labels": pd.Series(labels + 1, index=flat.index, name="Segment"),
            "structure": "clear" if sil >= 0.35 else "moderate" if sil >= 0.2 else "weak"}


# ============================================================================== insights
def _fmt_m(v):
    return human(v)


def make_insights(res: dict, model: dict, quality: list, cfg: dict) -> list[dict]:
    ins = []
    P = res.get("primary")
    flat_n = res["n_records"]
    # overview
    d = model.get("date")
    span = f" from {d['min']} to {d['max']} ({d['grain']} data)" if d else ""
    ins.append({"type": "overview", "title": "Dataset overview",
                "text": f"{flat_n:,} records across {len(model['tables'])} table(s){span}. Primary measure analysed: {pretty(P) if P else 'none'}."})
    # concentration / drivers
    for b in res["breakdowns"][:3]:
        t = b["table"]
        if "total" not in t or t["total"].sum() == 0 or len(t) < 2:
            continue
        top = t.sort_values("total", ascending=False).iloc[0]
        eta, p = b["eta2"], b["p_value"]
        sig = "statistically significant" if (np.isfinite(p) and p < 0.05) else "not statistically significant"
        eff = "meaningful" if (np.isfinite(eta) and eta >= 0.01) else "negligible"
        txt = (f"'{top['group']}' contributes {top['share']*100:.1f}% of total {pretty(P)} "
               f"({top['records']/t['records'].sum()*100:.1f}% of records). ")
        if len(t) >= 2:
            lo = t[t["records"] >= max(20, 0.01 * t["records"].sum())].sort_values("avg_per_record")
            if len(lo) >= 2:
                a, z = lo.iloc[0], lo.iloc[-1]
                txt += (f"Average {pretty(P)} per record ranges from {human(a['avg_per_record'])} ('{a['group']}') to "
                        f"{human(z['avg_per_record'])} ('{z['group']}'); difference is {sig} (Kruskal {fmt_p(p)}) with a {eff} effect size "
                        f"(eta²={eta:.3f}).")
        ins.append({"type": "driver", "title": f"{pretty(b['dim'])}: where {pretty(P)} comes from", "text": txt})
    # time
    ta = res.get("time")
    if ta and "trend" in ta:
        tr = ta["trend"]
        direction = "rising" if tr["slope"] > 0 else "falling"
        sig = "statistically significant" if tr["p_value"] < 0.05 else "no statistically significant trend"
        txt = (f"{pretty(P)} per {ta['freq'].replace('ly','').replace('dai','day')} period is {direction} by "
               f"{abs(tr['pct_per_period'])*100:.2f}% per period ({sig}, {fmt_p(tr['p_value'])}, R²={tr['r2']:.2f}). "
               f"Peak: {ta['peak']['period']:%Y-%m-%d} ({human(ta['peak']['value'])}); low: {ta['trough']['period']:%Y-%m-%d} "
               f"({human(ta['trough']['value'])}).")
        h = ta["first_vs_second_half"]
        txt += f" Second half vs first half: {h['change']*100:+.1f}%."
        if ta.get("anomalies"):
            txt += f" {len(ta['anomalies'])} anomalous period(s) detected (robust z>3.5)."
        if ta.get("partial_last_period"):
            txt += " The last period looks incomplete and was excluded from trend statistics."
        ins.append({"type": "trend", "title": "Trend & seasonality", "text": txt})
    if ta and "backtest" in ta:
        bt = ta["backtest"]
        better = bt["holt_mape"] < min(bt["naive_mape"], bt["mean_mape"])
        ins.append({"type": "forecast", "title": "Forecast reliability",
                    "text": (f"Damped-trend forecast backtest on the last {bt['holdout_periods']} periods: MAPE {bt['holt_mape']*100:.1f}% vs "
                             f"naive {bt['naive_mape']*100:.1f}% vs mean {bt['mean_mape']*100:.1f}%. "
                             + ("The model beats both baselines - use the forecast as a planning guide." if better else
                                "It does NOT beat a simple baseline, so treat the forecast as indicative only."))})
    # correlations
    cr = res.get("correlations")
    if cr and cr["pairs"]:
        strong = [p for p in cr["pairs"] if abs(p["pearson"]) >= 0.5]
        if strong:
            s = strong[0]
            ins.append({"type": "correlation", "title": "Strongest relationship",
                        "text": f"{pretty(s['a'])} and {pretty(s['b'])} move together (Pearson r={s['pearson']:.2f}, Spearman {s['spearman']:.2f})."
                                + (f" {len(strong)-1} more pair(s) with |r|>=0.5." if len(strong) > 1 else "")})
        else:
            ins.append({"type": "correlation", "title": "Relationships between numeric fields",
                        "text": f"No strongly correlated numeric pair (largest |r| = {abs(cr['pairs'][0]['pearson']):.2f}) - fields are largely independent."})
    # target
    tg = res.get("target")
    if tg:
        txt = f"{pretty(tg['target'])}: {tg['rate']*100:.2f}% of records ({tg['positives']:,} of {tg['n']:,})."
        sig = [s for s in tg["segments"] if s["p_value"] < 0.01 and s["cramers_v"] >= 0.05]
        if sig:
            s = sig[0]
            txt += (f" Strongest segment effect: {pretty(s['dim'])} - '{s['highest']}' at {s['highest_rate']*100:.1f}% vs "
                    f"'{s['lowest']}' at {s['lowest_rate']*100:.1f}% (Cramér's V={s['cramers_v']:.2f}, {fmt_p(s['p_value'])}).")
        else:
            txt += " No categorical segment shows a statistically significant and practically meaningful difference in rate."
        bp = tg.get("by_period")
        if bp and bp["p_value"] < 0.01 and bp["cramers_v"] >= 0.05 and bp["top"]:
            hi_, lo_ = bp["top"][0], bp["bottom"][-1]
            txt += (f" The rate is NOT uniform over time (chi-square {fmt_p(bp['p_value'])}, V={bp['cramers_v']:.2f}): it peaks at "
                    f"{hi_['rate']*100:.1f}% in the period starting {pd.Timestamp(hi_['period']):%Y-%m-%d} and drops to "
                    f"{lo_['rate']*100:.1f}% in the period starting {pd.Timestamp(lo_['period']):%Y-%m-%d}.")
        m = tg.get("model", {})
        if "cv_auc_mean" in m:
            txt += (f" A gradient-boosting model using {m['n_features']} fields reaches cross-validated AUC {m['cv_auc_mean']:.3f} "
                    f"(±{m['cv_auc_std']:.3f}) -> {m['verdict']}.")
            top = [i for i in m.get("importance", []) if i["significant"]][:3]
            if top:
                txt += " Most informative fields: " + ", ".join(f"{pretty(i['feature'])} (AUC drop {i['auc_drop']:.3f})" for i in top) + "."
        ins.append({"type": "risk", "title": f"Drivers of {pretty(tg['target'])}", "text": txt})
    # segmentation
    sg = res.get("segments")
    if sg:
        ins.append({"type": "segments", "title": "Customer / record segmentation",
                    "text": f"K-means found k={sg['k']} segments (silhouette {sg['silhouette']:.2f} -> {sg['structure']} structure). "
                            + ("; ".join(f"{s['name']} ({s['share']*100:.0f}%)" for s in sg["segments"][:4]) + "."
                               if sg["structure"] != "weak" else "Natural clusters are weak, so segments are exploratory rather than actionable.")})
    # data quality
    hi = [q for q in quality if q["severity"] in ("high", "medium")]
    if hi:
        ins.append({"type": "quality", "title": "Data quality caveats",
                    "text": "; ".join(f"{q['table']}.{q['column']}: {q['detail']}" for q in hi[:6])})
    return ins


# ============================================================================== orchestrator
def analyze(model: dict, flat: pd.DataFrame, fprof: dict, quality: list, cfg: dict) -> dict:
    res: dict = {"warnings": [], "n_records": int(len(flat))}

    def guard(name, fn, *a, **k):
        try:
            return fn(*a, **k)
        except Exception as e:  # never let one section kill the run
            res["warnings"].append(f"{name} skipped: {type(e).__name__}: {e}")
            return None

    primary = pick_primary(flat, fprof, cfg)
    target = pick_target(flat, fprof, cfg)
    entity = pick_entity(model)
    res.update(primary=primary, target=None, target_col=target, entity=entity)
    specs = build_kpi_specs(model, fprof, primary, target, entity, cfg)
    res["kpi_specs"] = specs
    res["kpis"] = [{**s, "value": guard(f"KPI {s['label']}", eval_kpi, s, flat)} for s in specs]
    res["breakdowns"] = guard("breakdowns", breakdowns, flat, fprof, primary, target) or []
    date_col = model["date"]["fact_column"] if model.get("date") else None
    res["time"] = guard("time analysis", time_analysis, flat, date_col, primary, model.get("date") or {})
    res["correlations"] = guard("correlations", correlations, flat, fprof, cfg.get("derived"))
    if target:
        res["target"] = guard("target analysis", target_analysis, flat, fprof, target, 42, date_col, tuple((cfg.get("derived") or {}).keys()))
    res["segments"] = guard("segmentation", segmentation, flat, fprof, primary, 42, tuple((cfg.get("derived") or {}).keys()))
    res["insights"] = guard("insights", make_insights, res, model, quality, cfg) or []
    return res
