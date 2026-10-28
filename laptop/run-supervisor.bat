@echo off
rem One-shot supervisor launcher (2026-10-28): runs the Coles walk under
rem the freeze-detecting supervisor. Log: data\coles-catalogue\supervisor.log
cd /d "%~dp0.."
"C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe" -u core\coles_walk_supervised.py --polite-ms 4500
