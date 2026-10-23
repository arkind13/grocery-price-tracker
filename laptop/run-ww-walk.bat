@echo off
rem WW CATALOGUE WALK - MANUAL TRIGGER (double-click me)
rem This is ALSO the action the Wednesday-5am scheduled task runs.
rem Walks Woolworths' aisles from this home PC (~30-45 min, polite), then
rem uploads + publishes on the server and sends the Telegram receipt.

cd /d "%~dp0.."
setlocal
rem token lives in laptop\ww-upload.env (untracked - never committed)
if exist laptop\ww-upload.env (
  for /f "usebackq tokens=1,* delims==" %%A in ("laptop\ww-upload.env") do set "%%A=%%B"
)
"C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe" core\ww_catalogue_walk.py --polite-ms 2200
echo.
echo Done. See data\ww-catalogue\ for the walk files.
timeout /t 15
