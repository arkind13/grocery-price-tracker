@echo off
rem WEDNESDAY RUN — the 5am scheduled task's action. Woolworths first
rem (~1h, no browser). Coles: SPECIALS SWEEP ONLY since 2026-11-05 (user
rem ruling: "not worth 2 days of trying every week to get the whole
rem catalogue") — the full-catalogue walk is RETIRED; the Coles catalogue
rem rides on what is banked + whatever live searches save into it, and
rem only the specials shelf (~30-45 min) is swept weekly. If the sweep
rem gets robot-blocked it reports and gives up — nobody is pestered.

cd /d "%~dp0.."
setlocal
rem token lives in laptop\ww-upload.env (untracked - never committed)
if exist laptop\ww-upload.env (
  for /f "usebackq tokens=1,* delims==" %%A in ("laptop\ww-upload.env") do set "%%A=%%B"
)

echo === Woolworths walk ===
"C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe" core\ww_catalogue_walk.py --polite-ms 2200
echo.

echo === Coles specials sweep (full walk retired 2026-11-05) ===
"C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe" -u core\coles_catalogue_walk.py --specials-only --polite-ms 4500
echo.

echo Wednesday runs done. Server receipts sent to Telegram.
timeout /t 30
