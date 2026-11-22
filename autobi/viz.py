"""Static charts (matplotlib) + a single-file HTML dashboard that previews what the Power BI report shows."""
from __future__ import annotations
import base64
import html
import io
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402
from .utils import pretty, human  # noqa: E402

PAL = {"primary": "#4F46E5", "teal": "#0D9488", "amber": "#F59E0B", "rose": "#E11D48", "slate": "#475569", "light": "#E2E8F0",
       "series": ["#4F46E5", "#0D9488", "#F59E0B", "#E11D48", "#8B5CF6", "#0EA5E9", "#84CC16", "#F97316"]}
plt.rcParams.update({"font.size": 9, "axes.spines.top": False, "axes.spines.right": False, "axes.edgecolor": "#94A3B8",
                     "axes.labelcolor": "#334155", "xtick.color": "#475569", "ytick.color": "#475569", "axes.titleweight": "bold",
                     "axes.titlesize": 11, "axes.titlecolor": "#0F172A", "figure.dpi": 110})
_fmt = FuncFormatter(lambda v, _: human(v))


def _b64(fig) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def chart_trend(res) -> str | None:
    ta = res.get("time")
    if not ta or "series" not in ta:
        return None
    s = ta["series"]
    fig, ax = plt.subplots(figsize=(8.2, 3.4))
    ax.plot(s["period"], s["value"], color=PAL["primary"], lw=1.8, label=pretty(res["primary"]))
    if len(s) >= 8:
        ax.plot(s["period"], s["value"].rolling(4, min_periods=2).mean(), color=PAL["amber"], lw=1.4, ls="--", label="4-period average")
    for a in ta.get("anomalies", []):
        ax.scatter([a["period"]], [a["value"]], color=PAL["rose"], zorder=5, s=36, label="anomaly")
    if "forecast" in ta:
        f = ta["forecast"]
        ax.plot(f["period"], f["forecast"], color=PAL["teal"], lw=1.8, label="forecast")
        ax.fill_between(f["period"], f["lower"], f["upper"], color=PAL["teal"], alpha=0.15, label="~95% band")
    ax.yaxis.set_major_formatter(_fmt)
    ax.set_title(f"{pretty(res['primary'])} over time ({ta['freq']})")
    h, l = ax.get_legend_handles_labels()
    uniq = dict(zip(l, h))
    ax.legend(uniq.values(), uniq.keys(), frameon=False, fontsize=8, ncol=4, loc="upper center", bbox_to_anchor=(0.5, -0.12))
    ax.grid(axis="y", color=PAL["light"])
    return _b64(fig)


def chart_breakdown(res, b) -> str | None:
    t = b["table"]
    if "total" not in t or t.empty:
        return None
    d = t.sort_values("total", ascending=False).head(10) if not b["ordered"] else t.head(12)
    fig, ax = plt.subplots(figsize=(4.6, max(2.4, 0.38 * len(d) + 1.0)))
    d = d.iloc[::-1] if not b["ordered"] else d.iloc[::-1]
    bars = ax.barh(d["group"], d["total"], color=PAL["primary"])
    for r, v, sh in zip(bars, d["total"], d["share"]):
        ax.text(r.get_width(), r.get_y() + r.get_height() / 2, f"  {human(v)}  ({sh*100:.0f}%)", va="center", fontsize=8, color="#334155")
    ax.xaxis.set_major_formatter(_fmt)
    ax.set_xlim(0, d["total"].max() * 1.35)
    sig = ""
    if np.isfinite(b["eta2"]):
        sig = f"  [eta²={b['eta2']:.2f}]"
    ax.set_title(f"{pretty(res['primary'])} by {pretty(b['dim'])}{sig}", loc="left")
    return _b64(fig)


def chart_target_period(res) -> str | None:
    tg = res.get("target")
    if not tg or not tg.get("by_period"):
        return None
    t = tg["by_period"]["table"]
    fig, ax = plt.subplots(figsize=(8.2, 3.0))
    ax.bar(t["period"], t["rate"] * 100, width=5 if len(t) < 70 else 20, color=PAL["rose"], alpha=0.85)
    ax.axhline(tg["rate"] * 100, color=PAL["slate"], ls="--", lw=1.2)
    ax.text(t["period"].iloc[0], tg["rate"] * 100, f"  overall {tg['rate']*100:.1f}%", va="bottom", fontsize=8, color=PAL["slate"])
    ax.set_ylabel("% of records")
    ax.set_title(f"{pretty(tg['target'])} rate by period  [chi-square V={tg['by_period']['cramers_v']:.2f}]", loc="left")
    ax.grid(axis="y", color=PAL["light"])
    return _b64(fig)


def chart_target_segments(res) -> str | None:
    tg = res.get("target")
    if not tg or not tg["segments"]:
        return None
    top = tg["segments"][:2]
    return None if not top else _target_segment_fig(res, top)


def _target_segment_fig(res, top):
    # needs group-level rates -> take them from the breakdown tables (they carry target_rate)
    tabs = {b["dim"]: b["table"] for b in res["breakdowns"]}
    use = [s for s in top if s["dim"] in tabs and "target_rate" in tabs[s["dim"]]]
    if not use:
        return None
    fig, axes = plt.subplots(1, len(use), figsize=(4.6 * len(use), 3.0), squeeze=False)
    for ax, s in zip(axes[0], use):
        t = tabs[s["dim"]].sort_values("target_rate", ascending=False).head(10)
        ax.bar(t["group"].astype(str), t["target_rate"] * 100, color=PAL["amber"])
        ax.axhline(res["target"]["rate"] * 100, color=PAL["slate"], ls="--", lw=1)
        ax.set_title(f"{pretty(res['target']['target'])} % by {pretty(s['dim'])}\n(V={s['cramers_v']:.2f}, {'significant' if s['p_value'] < 0.01 else 'not significant'})",
                     loc="left", fontsize=9)
        ax.tick_params(axis="x", rotation=35)
        for lbl in ax.get_xticklabels():
            lbl.set_ha("right")
    fig.tight_layout()
    return _b64(fig)


def chart_corr(res) -> str | None:
    cr = res.get("correlations")
    if not cr:
        return None
    m = cr["matrix"]
    n = len(m)
    fig, ax = plt.subplots(figsize=(max(4.8, 0.5 * n + 2), max(4.2, 0.5 * n + 1.5)))
    im = ax.imshow(m.values, cmap="RdBu_r", vmin=-1, vmax=1)
    ax.set_xticks(range(n), [pretty(c) for c in m.columns], rotation=60, ha="right", fontsize=7)
    ax.set_yticks(range(n), [pretty(c) for c in m.index], fontsize=7)
    if n <= 14:
        for i in range(n):
            for j in range(n):
                ax.text(j, i, f"{m.values[i, j]:.1f}", ha="center", va="center", fontsize=6, color="white" if abs(m.values[i, j]) > 0.6 else "#334155")
    fig.colorbar(im, fraction=0.04, pad=0.02)
    ax.set_title("Correlation (Pearson)", loc="left")
    ax.spines[:].set_visible(False)
    return _b64(fig)


def chart_drivers(res) -> str | None:
    tg = res.get("target")
    m = (tg or {}).get("model", {})
    if not m or "importance" not in m:
        return None
    imp = m["importance"][:8][::-1]
    fig, ax = plt.subplots(figsize=(5.2, 3.2))
    cols = [PAL["primary"] if i["significant"] else PAL["light"] for i in imp]
    ax.barh([pretty(i["feature"]) for i in imp], [i["auc_drop"] for i in imp], xerr=[i["std"] for i in imp], color=cols, ecolor="#64748B")
    ax.set_xlabel("AUC drop when the field is shuffled")
    ax.set_title(f"What predicts {pretty(tg['target'])}?  (CV AUC {m['cv_auc_mean']:.2f})", loc="left")
    return _b64(fig)


def chart_segments(res) -> str | None:
    sg = res.get("segments")
    if not sg:
        return None
    segs = sg["segments"]
    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    labels = [f"S{s['segment']}" for s in segs]
    ax.bar(labels, [s["share"] * 100 for s in segs], color=PAL["series"][: len(segs)])
    for i, s in enumerate(segs):
        ax.text(i, s["share"] * 100, f"{s['share']*100:.0f}%", ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("% of records")
    ax.set_title(f"K-means segments (k={sg['k']}, silhouette {sg['silhouette']:.2f})", loc="left")
    return _b64(fig)


def chart_distributions(flat, fprof) -> str | None:
    cols = [c for c, p in fprof.items() if p["role"] == "numeric" and p["n_unique"] > 10][:6]
    if not cols:
        return None
    n = len(cols)
    r, c = (n + 2) // 3, min(3, n)
    fig, axes = plt.subplots(r, c, figsize=(3.0 * c, 2.2 * r), squeeze=False)
    for ax, col in zip(axes.ravel(), cols):
        v = flat[col].dropna().astype(float)
        ax.hist(v, bins=30, color=PAL["teal"], alpha=0.9)
        ax.set_title(pretty(col), fontsize=8, loc="left")
        ax.xaxis.set_major_formatter(_fmt)
        ax.tick_params(labelsize=7)
    for ax in axes.ravel()[n:]:
        ax.axis("off")
    fig.tight_layout()
    return _b64(fig)


# ------------------------------------------------------------------------------------------ HTML
def _kpi_value(k) -> str:
    v = k["value"]
    if v is None:
        return "n/a"
    if k["fmt"] == "int":
        return f"{int(v):,}"
    if k["fmt"] == "pct":
        return f"{v*100:.1f}%"
    return human(v)


CSS = """
:root{--bg:#F8FAFC;--card:#fff;--ink:#0F172A;--mut:#64748B;--line:#E2E8F0;--acc:#4F46E5}
*{box-sizing:border-box}body{margin:0;font-family:Inter,Segoe UI,Roboto,Arial,sans-serif;background:var(--bg);color:var(--ink)}
header{background:linear-gradient(135deg,#312E81,#4F46E5 60%,#0D9488);color:#fff;padding:28px 40px}
header h1{margin:0 0 4px;font-size:26px}header p{margin:0;opacity:.85;font-size:13px}
main{max-width:1280px;margin:0 auto;padding:24px 28px 60px}
h2{font-size:17px;margin:34px 0 12px;border-left:4px solid var(--acc);padding-left:10px}
.kpis{display:-webkit-flex;display:flex;flex-wrap:wrap;margin:-6px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px;margin:6px;-webkit-flex:1 1 170px;flex:1 1 170px;min-width:170px;max-width:260px}
.kpi .l{font-size:11px;color:var(--mut);text-transform:uppercase;letter-spacing:.04em}.kpi .v{font-size:24px;font-weight:700;margin-top:4px}
.grid{display:-webkit-flex;display:flex;flex-wrap:wrap;margin:-7px}
.card{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px;margin:7px;-webkit-flex:1 1 380px;flex:1 1 380px;min-width:0}
.card.wide{-webkit-flex:1 1 100%;flex:1 1 100%}
.card img{max-width:100%;display:block;margin:auto}
.ins{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--acc);border-radius:10px;padding:12px 16px;margin-bottom:10px}
.ins b{display:block;margin-bottom:3px}.ins span{color:#334155;font-size:13.5px;line-height:1.5}
.ins.quality{border-left-color:#F59E0B}.ins.risk{border-left-color:#E11D48}.ins.trend,.ins.forecast{border-left-color:#0D9488}
table{border-collapse:collapse;width:100%;font-size:12.5px;background:#fff}th,td{padding:6px 10px;border-bottom:1px solid var(--line);text-align:left}
th{background:#F1F5F9;color:#334155}.tag{display:inline-block;padding:1px 8px;border-radius:99px;font-size:11px;background:#EEF2FF;color:#3730A3}
.tag.high{background:#FEE2E2;color:#991B1B}.tag.medium{background:#FEF3C7;color:#92400E}.tag.low{background:#F1F5F9;color:#475569}
details{background:#fff;border:1px solid var(--line);border-radius:10px;padding:10px 14px;margin-bottom:8px}summary{cursor:pointer;font-weight:600}
code{background:#F1F5F9;padding:1px 5px;border-radius:4px;font-size:12px}
footer{color:var(--mut);font-size:12px;text-align:center;padding:30px}
"""


def render_html(title: str, model: dict, res: dict, flat: pd.DataFrame, fprof: dict, cleaning_logs: list, quality: list, meta: dict) -> str:
    e = html.escape
    out = [f"<!doctype html><html><head><meta charset='utf-8'><title>{e(title)}</title><style>{CSS}</style></head><body>"]
    out.append(f"<header><h1>{e(title)}</h1><p>{res['n_records']:,} records · {len(model['tables'])} tables · generated {meta['generated']} · "
               f"primary measure: <b>{e(pretty(res['primary'] or 'n/a'))}</b></p></header><main>")
    out.append("<h2>Key metrics</h2><div class='kpis'>")
    for k in res["kpis"]:
        out.append(f"<div class='kpi'><div class='l'>{e(k['label'])}</div><div class='v'>{_kpi_value(k)}</div></div>")
    out.append("</div>")

    out.append("<h2>Automatic insights</h2>")
    for i in res["insights"]:
        out.append(f"<div class='ins {i['type']}'><b>{e(i['title'])}</b><span>{e(i['text'])}</span></div>")

    imgs = []
    t = chart_trend(res)
    if t:
        imgs.append(("Trend & forecast", t, "wide"))
    tp = chart_target_period(res)
    if tp:
        imgs.append(("Risk over time", tp, "wide"))
    out.append("<h2>Trend</h2><div class='grid'>")
    for name, b, _ in imgs:
        out.append(f"<div class='card wide'><img src='data:image/png;base64,{b}' alt='{e(name)}'></div>")
    out.append("</div>")

    out.append("<h2>Where the value comes from</h2><div class='grid'>")
    for b in res["breakdowns"][:6]:
        img = chart_breakdown(res, b)
        if img:
            out.append(f"<div class='card'><img src='data:image/png;base64,{img}'></div>")
    out.append("</div>")

    extra = [("Segments", chart_target_segments(res)), ("Drivers", chart_drivers(res)), ("Segmentation", chart_segments(res)),
             ("Correlation", chart_corr(res)), ("Distributions", chart_distributions(flat, fprof))]
    extra = [(n, b) for n, b in extra if b]
    if extra:
        out.append("<h2>Drivers, segments & relationships</h2><div class='grid'>")
        for n, b in extra:
            out.append(f"<div class='card'><img src='data:image/png;base64,{b}' alt='{e(n)}'></div>")
        out.append("</div>")

    # model
    out.append("<h2>Data model (star schema sent to Power BI)</h2>")
    out.append("<table><tr><th>Table</th><th>Role</th><th>Rows</th><th>Columns</th></tr>")
    for t_, df in model["tables"].items():
        role = "Fact" if t_ == model["fact"] else "Date dimension" if t_ == "Dim_Date" else "Dimension" if t_ in model["dims"] else "Standalone"
        out.append(f"<tr><td><code>{e(t_)}</code></td><td>{role}</td><td>{len(df):,}</td><td>{df.shape[1]}</td></tr>")
    out.append("</table><br><table><tr><th>Relationship (many → one)</th><th>Value match</th><th>Observed</th></tr>")
    for r in model["relationships"]:
        out.append(f"<tr><td><code>{e(r['from_table'])}[{e(r['from_col'])}] → {e(r['to_table'])}[{e(r['to_col'])}]</code></td>"
                   f"<td>{r['match_pct']}%</td><td>{'1:1 today' if r['observed_one_to_one'] else 'many:1'}</td></tr>")
    out.append("</table>")

    out.append("<h2>Data quality & cleaning log</h2>")
    for a in model["appends"]:
        drift = ", ".join(f"<code>{e(f['from'])}</code>→<code>{e(f['to'])}</code>" for f in a["schema_drift_repaired"])
        out.append(f"<div class='ins quality'><b>Appended {e(a['appended'])} onto {e(a['base'])}</b><span>{a['rows_added']:,} rows. "
                   f"{'Schema drift repaired: ' + drift if drift else 'Identical schema.'}</span></div>")
    acts = [(lg["table"], a) for lg in cleaning_logs for a in lg["actions"]] + [(lg["table"], "WARNING: " + w) for lg in cleaning_logs for w in lg["warnings"]]
    if acts or model["log"]:
        out.append("<details><summary>Cleaning actions</summary><ul>" + "".join(f"<li><code>{e(t_)}</code> {e(a)}</li>" for t_, a in acts)
                   + "".join(f"<li>{e(m)}</li>" for m in model["log"]) + "</ul></details>")
    if quality:
        out.append("<table><tr><th>Severity</th><th>Table</th><th>Column</th><th>Issue</th><th>Detail</th></tr>")
        for q in sorted(quality, key=lambda q: {"high": 0, "medium": 1, "low": 2}[q["severity"]]):
            out.append(f"<tr><td><span class='tag {q['severity']}'>{q['severity']}</span></td><td>{e(q['table'])}</td><td>{e(q['column'])}</td>"
                       f"<td>{e(q['type'])}</td><td>{e(q['detail'])}</td></tr>")
        out.append("</table>")
    if res["warnings"]:
        out.append("<div class='ins quality'><b>Sections skipped</b><span>" + e("; ".join(res["warnings"])) + "</span></div>")
    out.append("<footer>Generated by AutoBI · every number above is recomputed from the cleaned data in <code>clean/</code> and "
               "matches the DAX measures in the Power BI project.</footer></main></body></html>")
    return "".join(out)
