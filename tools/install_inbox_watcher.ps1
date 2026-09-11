# One-line Windows startup story (AI-M4): registers a per-logon
# scheduled task that runs the watcher hidden. Re-runnable; removes
# any previous task first. No admin prompt needed for per-user tasks.
$ErrorActionPreference = "Stop"
$task = "InboxWatcher"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $env:USERPROFILE "anaconda3\pythonw.exe"
if (-not (Test-Path $py)) { $py = (Get-Command pythonw -ErrorAction SilentlyContinue).Source }
if (-not $py) { throw "pythonw.exe not found (needs anaconda3 or python on PATH)" }
Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
$action = New-ScheduledTaskAction -Execute $py -Argument "`"$repo\tools\inbox_watcher.py`""
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings | Out-Null
Start-ScheduledTask -TaskName $task
Write-Output "Installed + started: $task -> $py $repo\tools\inbox_watcher.py"
