@echo off
rem WEDNESDAY FULL RUN — the 5am scheduled task's action (user 2026-10-28:
rem "do the entire coles run on the local... the same way you did by keeping
rem a browser open and using that to keep updating it"). Woolworths first
rem (~1h, no browser), then the ENTIRE Coles walk (~8-11h, opens a REAL
rem Chromium window — leave it be; it re-checks prices against the existing
rem database, records only changes, and resumes the same day if paused).
rem Each walk uploads + publishes on the server, which sends its own
rem Telegram receipt (scanned / on special / removed).

cd /d "%~dp0.."
setlocal
rem token lives in laptop\ww-upload.env (untracked - never committed)
if exist laptop\ww-upload.env (
  for /f "usebackq tokens=1,* delims==" %%A in ("laptop\ww-upload.env") do set "%%A=%%B"
)

echo === Woolworths walk ===
"C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe" core\ww_catalogue_walk.py --polite-ms 2200
echo.

echo === Coles walk (a real browser window stays open - leave the PC on) ===
"C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe" -u core\coles_catalogue_walk.py --polite-ms 4500
echo.

echo Both walks done. Server receipts sent to Telegram.
timeout /t 30
