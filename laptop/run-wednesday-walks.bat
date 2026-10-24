@echo off
rem WEDNESDAY WALKS - the laptop agent (ALDI + WOOLWORTHS, per the user's
rem 2026-10-24 ruling: "aldi and wool will still use the local computer
rem only coles will go apify route"). Also the MANUAL trigger (double-click).
rem ALDI ~2-4 min, then WW ~35 min, each uploads + publishes + sends its
rem own Telegram receipt. Coles runs separately on the server via Apify.

cd /d "%~dp0.."
setlocal
if exist laptop\ww-upload.env (
  for /f "usebackq tokens=1,* delims==" %%A in ("laptop\ww-upload.env") do set "%%A=%%B"
)
echo === ALDI walk ===
"C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe" core\aldi_catalogue_walk.py --polite-ms 900
echo.
echo === Woolworths walk ===
"C:\Users\User.DESKTOP-R2G441H\anaconda3\python.exe" core\ww_catalogue_walk.py --polite-ms 2200
echo.
echo Both walks done. Receipts sent to Telegram.
timeout /t 15
