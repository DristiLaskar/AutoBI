"""End-to-end orchestration: load -> clean -> model -> analyse -> export (CSV, HTML, Excel, Power BI)."""
from __future__ import annotations
import json
import logging
import platform
import re
from datetime import datetime
from pathlib import Path
import pandas as pd
from .loader import load_tables
from .clean import clean_table
from .model import build_model, flatten, flat_profile
from .profile import quality_flags
from .analysis import analyze
from .viz import render_html
from .excel_report import write_excel
from .powerbi import write_project
from .utils import jsonable, pretty

log = logging.getLogger("autobi")


def _fmt_csv(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for c in out.columns:
        if pd.api.types.is_datetime64_any_dtype(out[c]):
            has_time = (out[c].dropna() != out[c].dropna().dt.normalize()).any()
            out[c] = out[c].dt.strftime("%Y-%m-%d %H:%M:%S" if has_time else "%Y-%m-%d")
    return out


def run_pipeline(input_path, out_dir="output", name=None, config: dict | str | Path | None = None,
                 pbi_data_folder: str | None = None, pbi_visuals: bool = True, make_pbi: bool = True) -> dict:
    cfg = {}
    if isinstance(config, (str, Path)):
        cfg = json.loads(Path(config).read_text(encoding="utf-8"))
    elif isinstance(config, dict):
        cfg = config
    out = Path(out_dir)
    for sub in ("clean", "report", "powerbi"):
        (out / sub).mkdir(parents=True, exist_ok=True)
    for stale in (out / "clean").glob("*.csv"):
        stale.unlink()
    name = name or cfg.get("name") or Path(input_path).stem.replace("_", " ").title()

    # 1 load + clean ------------------------------------------------------------------
    raw = load_tables(input_path)
    log.info("loaded %d table(s)", len(raw))
    cleaned, cleaning_logs, sources = {}, [], {}
    for tname, df, meta in raw:
        c, lg = clean_table(df, tname, cfg)
        lg["source"] = meta
        cleaned[tname] = c
        cleaning_logs.append(lg)
        sources[tname] = meta

    # 2 model -------------------------------------------------------------------------
    model = build_model(cleaned, cfg)
    flat = flatten(model)
    fprof = flat_profile(model, flat)
    quality = []
    for t, df in model["tables"].items():
        if t != "Dim_Date":
            quality += quality_flags(df, model["profiles"][t], t)

    # 3 analyse -----------------------------------------------------------------------
    res = analyze(model, flat, fprof, quality, cfg)

    # 4 export ------------------------------------------------------------------------
    for t, df in model["tables"].items():
        _fmt_csv(df).to_csv(out / "clean" / f"{t}.csv", index=False, encoding="utf-8")
    if res.get("segments"):
        seg = flat[[res["entity"]]].copy() if res.get("entity") else pd.DataFrame(index=flat.index)
        seg["Segment"] = res["segments"]["labels"].values
        seg.to_csv(out / "report" / "segments.csv", index=False)
    meta = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M")}
    html = render_html(name, model, res, flat, fprof, cleaning_logs, quality, meta)
    (out / "report" / "dashboard.html").write_text(html, encoding="utf-8")
    write_excel(out / "report" / "analysis.xlsx", model, res, quality, cleaning_logs)

    pbi = None
    if make_pbi:
        if pbi_data_folder:
            folder = pbi_data_folder
        elif platform.system() == "Windows":
            folder = str((out / "clean").resolve())
        else:  # Power BI Desktop is Windows-only; leave an obvious placeholder and tell the user how to fix it
            folder = "C:\\\\AutoBI\\\\" + re.sub(r"[^A-Za-z0-9]+", "_", name) + "\\\\clean"
            folder = folder.replace("\\\\", "\\")
        pbi = write_project(out / "powerbi", name, model, res, folder, with_visuals=pbi_visuals)
        pbi["data_folder"] = folder

    summary = {
        "name": name, "generated": meta["generated"], "sources": sources,
        "tables": {t: {"rows": int(len(df)), "cols": int(df.shape[1])} for t, df in model["tables"].items()},
        "fact": model["fact"], "dims": model["dims"], "relationships": model["relationships"], "date": model["date"],
        "appends": model["appends"], "model_log": model["log"], "cleaning": cleaning_logs, "quality": quality,
        "primary_measure": res["primary"], "target": res["target_col"], "entity": res["entity"],
        "kpis": [{k: v for k, v in x.items() if k in ("label", "value", "fmt", "agg", "column")} for x in res["kpis"]],
        "insights": res["insights"], "warnings": res["warnings"],
        "powerbi": {k: v for k, v in (pbi or {}).items() if k != "measures"},
    }
    (out / "report" / "summary.json").write_text(json.dumps(jsonable(summary), indent=2), encoding="utf-8")
    (out / "report" / "insights.md").write_text(
        f"# {name} - automatic insights\n\n" + "\n".join(f"## {i['title']}\n{i['text']}\n" for i in res["insights"]), encoding="utf-8")
    return {"model": model, "flat": flat, "res": res, "quality": quality, "cleaning": cleaning_logs, "pbi": pbi, "out": out, "summary": summary}
