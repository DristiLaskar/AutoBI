@echo off
REM Usage: drag a CSV/Excel file (or a folder of them) onto this file, or:  Run_AutoBI.bat data\sales.xlsx -o output\sales
python -m pip install -q -r requirements.txt
python run_autobi.py %*
pause
