"""Robust loading of CSV / TSV / TXT / Excel files (or a whole folder of them)."""
from __future__ import annotations
import csv
import io
from pathlib import Path
import pandas as pd

CSV_EXT = {".csv", ".tsv", ".txt"}
XLS_EXT = {".xlsx", ".xlsm", ".xls"}
ENCODINGS = ["utf-8-sig", "utf-8", "cp1252", "latin-1"]


def discover_files(path) -> list[Path]:
    p = Path(path)
    if p.is_file():
        return [p]
    if not p.exists():
        raise FileNotFoundError(f"Input path not found: {p}")
    files = sorted(f for f in p.rglob("*")
                   if f.suffix.lower() in (CSV_EXT | XLS_EXT) and not f.name.startswith(("~$", ".")))
    if not files:
        raise FileNotFoundError(f"No .csv/.tsv/.txt/.xlsx/.xls files found in {p}")
    return files


def _read_csv(path: Path) -> tuple[pd.DataFrame, dict]:
    raw = path.read_bytes()
    last_err = None
    for enc in ENCODINGS:
        try:
            text = raw.decode(enc)
        except UnicodeDecodeError as e:
            last_err = e
            continue
        sample = text[:50000]
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            delim = "\t" if path.suffix.lower() == ".tsv" else ","
        df = pd.read_csv(io.StringIO(text), sep=delim, dtype=str, keep_default_na=False)
        return df, {"encoding": enc, "delimiter": delim}
    raise ValueError(f"Could not decode {path.name}: {last_err}")


def load_tables(path) -> list[tuple[str, pd.DataFrame, dict]]:
    """Return [(table_name, raw_df, meta)] - one entry per CSV file or Excel sheet."""
    out = []
    sheet_counts: dict = {}
    for f in discover_files(path):
        ext = f.suffix.lower()
        if ext in CSV_EXT:
            df, meta = _read_csv(f)
            meta["file"] = f.name
            out.append((f.stem, df, meta))
        else:
            engine = "xlrd" if ext == ".xls" else "openpyxl"
            sheets = pd.read_excel(f, sheet_name=None, engine=engine)
            for sh, df in sheets.items():
                if df.dropna(how="all").empty:
                    continue
                sheet_counts[sh] = sheet_counts.get(sh, 0) + 1
                name = f.stem if len(sheets) == 1 else sh
                out.append((name, df, {"file": f.name, "sheet": sh, "_multi": len(sheets) > 1}))
    # sheet names that collide across workbooks get the file name prefixed
    final = []
    for name, df, meta in out:
        if meta.pop("_multi", False) and sheet_counts.get(meta["sheet"], 0) > 1:
            name = f"{Path(meta['file']).stem}_{meta['sheet']}"
        final.append((name, df, meta))
    return final
