"""AutoBI - drop in any CSV/Excel file(s) and get a cleaned star-schema, analysis,
an HTML/Excel report and a ready-to-open Power BI project (PBIP)."""
__version__ = "2.0.0"


def run_pipeline(*a, **k):
    from .pipeline import run_pipeline as _r
    return _r(*a, **k)
