@echo off
rem Coles HEALTH & BEAUTY targeted run (user 2026-10-29: "1pm run only focus
rem on health & beauty and ignore the rest") — walks ONLY the 34 unwalked
rem H&B aisles (~2,550 items, ~1h at 9s politeness), publishes partial.
cd /d "%~dp0.."
if exist laptop\ww-upload.env (
  for /f "usebackq tokens=1,* delims==" %%A in ("laptop\ww-upload.env") do set "%%A=%%B"
)
"C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe" -u core\coles_catalogue_walk.py --aisles-file data\coles-catalogue\hb-aisles.txt --polite-ms 9000
