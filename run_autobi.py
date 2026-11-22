"""Convenience launcher:  python run_autobi.py <file-or-folder> [-o output] [-c config.json]"""
from autobi.cli import main
import sys
sys.exit(main(["run"] + sys.argv[1:]))
