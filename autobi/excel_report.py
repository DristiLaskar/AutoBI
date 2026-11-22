"""Excel workbook with the key results (native Excel charts on the trend and top breakdowns)."""
from __future__ import annotations
import numpy as np
import pandas as pd
from .utils import pretty


def _sheet_name(s: str, used: set) -> str:
    s = "".join(ch for ch in s if ch not in '[]:*?/\\')[:31] or "Sheet"
    base, i = s, 2
    while s.lower() in used:
        s = f"{base[:28]}_{i}"
        i += 1
    used.add(s.lower())
    return s


def write_excel(path, model, res, quality, cleaning_logs):
    used: set = set()
    with pd.ExcelWriter(path, engine="xlsxwriter") as xw:
        wb = xw.book
        hdr = wb.add_format({"bold": True, "bg_color": "#4F46E5", "font_color": "white", "border": 1})
        wrap = wb.add_format({"text_wrap": True, "valign": "top"})

        def put(df, name, index=False):
            sn = _sheet_name(name, used)
            df.to_excel(xw, sheet_name=sn, index=index, startrow=0)
            ws = xw.sheets[sn]
            for j, c in enumerate(df.reset_index().columns if index else df.columns):
                ws.write(0, j, str(c), hdr)
                ws.set_column(j, j, max(12, min(40, len(str(c)) + 4)))
            ws.freeze_panes(1, 0)
            return sn, ws

        k = pd.DataFrame([{"KPI": x["label"], "Value": x["value"], "Format": x["fmt"]} for x in res["kpis"]])
        put(k, "KPIs")
        ins = pd.DataFrame([{"Type": i["type"], "Title": i["title"], "Insight": i["text"]} for i in res["insights"]])
        sn, ws = put(ins, "Insights")
        ws.set_column(2, 2, 120, wrap)
        ta = res.get("time")
        if ta and "series" in ta:
            sn, ws = put(ta["series"], "Trend")
            n = len(ta["series"])
            ch = wb.add_chart({"type": "line"})
            ch.add_series({"name": pretty(res["primary"]), "categories": [sn, 1, 0, n, 0], "values": [sn, 1, 1, n, 1]})
            ch.set_title({"name": f"{pretty(res['primary'])} over time"})
            ch.set_legend({"none": True})
            ch.set_size({"width": 720, "height": 320})
            ws.insert_chart("F2", ch)
            if "forecast" in ta:
                put(ta["forecast"], "Forecast")
        for b in res["breakdowns"]:
            t = b["table"]
            sn, ws = put(t, f"By {b['dim']}")
            if "total" in t and len(t) <= 30:
                ch = wb.add_chart({"type": "bar"})
                ch.add_series({"name": "total", "categories": [sn, 1, 0, len(t), 0], "values": [sn, 1, t.columns.get_loc("total"), len(t), t.columns.get_loc("total")]})
                ch.set_title({"name": f"{pretty(res['primary'])} by {pretty(b['dim'])}"})
                ch.set_legend({"none": True})
                ws.insert_chart("H2", ch)
        cr = res.get("correlations")
        if cr:
            put(pd.DataFrame(cr["pairs"]), "Top correlations")
            put(cr["matrix"].round(3), "Correlation matrix", index=True)
        tg = res.get("target")
        if tg:
            put(pd.DataFrame(tg["segments"]), "Risk segments")
            put(pd.DataFrame(tg["numeric"]), "Risk numeric")
            if tg.get("by_period"):
                put(tg["by_period"]["table"], "Risk by period")
            m = tg.get("model", {})
            if "importance" in m:
                put(pd.DataFrame(m["importance"]), "Risk drivers (ML)")
        sg = res.get("segments")
        if sg:
            put(pd.DataFrame([{k: (", ".join(f"{a}:{b:+.2f}z" for a, b in v.items()) if k == "drivers" else v) for k, v in s.items()} for s in sg["segments"]]), "Segments")
        put(pd.DataFrame(quality) if quality else pd.DataFrame({"note": ["no data quality issues detected"]}), "Data quality")
        rows = [{"table": l["table"], "action": a} for l in cleaning_logs for a in l["actions"]]
        rows += [{"table": "model", "action": m} for m in model["log"]]
        put(pd.DataFrame(rows or [{"table": "-", "action": "nothing to clean"}]), "Cleaning log")
        rel = pd.DataFrame(model["relationships"]) if model["relationships"] else pd.DataFrame({"note": ["single table - no relationships"]})
        put(rel, "Relationships")
