import argparse
import logging
import sys
from .pipeline import run_pipeline
from .powerbi import set_data_folder


def main(argv=None):
    ap = argparse.ArgumentParser(prog="autobi", description="Any CSV/Excel -> clean star schema + insights + Power BI project")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="analyse a file or folder")
    r.add_argument("input", help="CSV/TSV/XLSX file, or a folder containing several")
    r.add_argument("-o", "--out", default="output", help="output folder (default: output)")
    r.add_argument("-n", "--name", help="project / dashboard name")
    r.add_argument("-c", "--config", help="optional JSON config (see configs/)")
    r.add_argument("--pbi-data-folder", help="absolute path Power BI should read the clean CSVs from (default: <out>/clean)")
    r.add_argument("--no-pbi-visuals", action="store_true", help="generate the Power BI data model + measures only (blank report)")
    r.add_argument("--no-pbi", action="store_true", help="skip Power BI project generation")
    s = sub.add_parser("set-data-folder", help="re-point an existing generated Power BI project at the clean CSV folder")
    s.add_argument("project_dir")
    s.add_argument("folder")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if a.cmd == "run":
        r_ = run_pipeline(a.input, a.out, a.name, a.config, a.pbi_data_folder, not a.no_pbi_visuals, not a.no_pbi)
        s_ = r_["summary"]
        print(f"\nDone: {s_['name']}\n  tables: {', '.join(s_['tables'])}\n  report: {r_['out'] / 'report' / 'dashboard.html'}")
        if r_["pbi"]:
            print(f"  Power BI: {r_['pbi']['pbip']}  ({r_['pbi']['n_pages']} pages, {r_['pbi']['n_visuals']} visuals, {r_['pbi']['n_measures']} measures)")
            print(f"  data folder used by Power BI: {r_['pbi']['data_folder']}")
        for w in s_["warnings"]:
            print("  warning:", w)
    elif a.cmd == "set-data-folder":
        from pathlib import Path
        print("updated", set_data_folder(a.project_dir, str(Path(a.folder).resolve())))
    else:
        ap.print_help()
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
