# WW LAPTOP AGENT INSTALLER (Phase B, 2026-10-23).
# Registers the Wednesday 05:00 Sydney self-waking task that walks
# Woolworths' aisles from this home PC and uploads the weekly catalogue.
# Run ONCE from PowerShell (admin not required for current-user tasks):
#   powershell -ExecutionPolicy Bypass -File laptop\install-ww-wednesday.ps1
#
# Wake rules (plan Phase B): lid closed is FINE (task wakes from sleep);
# only a full shutdown stops it — missed weeks catch up automatically on
# the next wake ("as at" labels cover the gap) and the server's watcher
# messages the user with the failure history + how to run it by hand.

$ErrorActionPreference = "Stop"
$tracker = Split-Path -Parent $PSScriptRoot
$bat = Join-Path $tracker "laptop\run-ww-walk.bat"

# allow wake timers on the active power plan (best-effort; needs no admin
# for the current scheme in most configs)
powercfg /setacvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 2>$null
powercfg /setdcvalueindex SCHEME_CURRENT SUB_SLEEP RTCWAKE 1 2>$null
powercfg /setactive SCHEME_CURRENT 2>$null

$action = New-ScheduledTaskAction -Execute $bat
# Wednesday 05:00 local (Sydney) — user-set 2026-10-23 ("5 am is ideal",
# WW's new prices are live from ~04:00)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Wednesday -At 5:00am
$settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable `
  -ExecutionTimeLimit (New-TimeSpan -Hours 3) -DontStopIfGoingOnBatteries `
  -AllowStartIfOnBatteries -RestartCount 2 -RestartInterval (New-TimeSpan -Minutes 5)
Register-ScheduledTask -TaskName "WW Catalogue Walk (Wednesday 5am)" `
  -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Write-Host "Task registered: 'WW Catalogue Walk (Wednesday 5am)' -> $bat"
Write-Host "Wake-to-run enabled; lid closed is fine. Manual run: double-click run-ww-walk.bat"
