@echo off
rem Daily pipeline run (registered in Windows Task Scheduler as "cbintel-daily").
rem Output is appended to data\logs\daily.log; results are in the run log:
rem   python -m cbintel history
cd /d "%~dp0.."
if not exist data\logs mkdir data\logs
set PYTHONIOENCODING=utf-8
echo ===== %date% %time% ===== >> data\logs\daily.log
python -m cbintel all >> data\logs\daily.log 2>&1
