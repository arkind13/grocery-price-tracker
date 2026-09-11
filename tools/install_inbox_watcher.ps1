# One-line Windows startup story (AI-M4): registers a per-logon
# scheduled task that runs the watcher hidden; when task registration
# is denied, falls back to a Startup-folder shortcut (same effect,
# zero permissions). Re-runnable; removes any previous task first.
$ErrorActionPreference = "Stop"
$task = "InboxWatcher"
$repo = Split-Path -Parent $PSScriptRoot
$py = Join-Path $env:USERPROFILE "anaconda3\pythonw.exe"
if (-not (Test-Path $py)) { $py = (Get-Command pythonw -ErrorAction SilentlyContinue).Source }
if (-not $py) { throw "pythonw.exe not found (needs anaconda3 or python on PATH)" }
$args = "`"$repo\tools\inbox_watcher.py`""

$installed = $false
try {
    Unregister-ScheduledTask -TaskName $task -Confirm:$false -ErrorAction SilentlyContinue
    $action = New-ScheduledTaskAction -Execute $py -Argument $args
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -Hidden -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)
    Register-ScheduledTask -TaskName $task -Action $action -Trigger $trigger -Settings $settings | Out-Null
    Start-ScheduledTask -TaskName $task
    $installed = $true
    Write-Output "Installed + started: scheduled task '$task' -> $py $args"
} catch {
    Write-Output "Scheduled task registration denied ($($_.Exception.Message.Substring(0, [Math]::Min(60, $_.Exception.Message.Length)))...) - using the Startup folder instead"
}

if (-not $installed) {
    # Startup-folder fallback: a hidden-window shortcut at logon.
    $startup = [Environment]::GetFolderPath("Startup")
    $lnk = Join-Path $startup "InboxWatcher.lnk"
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($lnk)
    $shortcut.TargetPath = $py
    $shortcut.Arguments = $args
    $shortcut.WindowStyle = 7   # minimized
    $shortcut.Description = "grocery watch-folder -> VPS auto-ingest pusher"
    $shortcut.Save()
    Write-Output "Installed: Startup shortcut '$lnk'"
}

# Start it NOW (hidden) unless a watcher is already running.
$running = Get-CimInstance Win32_Process -Filter "Name = 'pythonw.exe'" |
    Where-Object { $_.CommandLine -like "*inbox_watcher.py*" }
if (-not $running) {
    Start-Process -FilePath $py -ArgumentList $args -WindowStyle Hidden
    Write-Output "Watcher started now (hidden)."
} else {
    Write-Output "Watcher already running (PID $($running.ProcessId))."
}
Write-Output "Watch folder: $([Environment]::GetFolderPath('Desktop'))\shop-posts (shop subfolders are created on start)"
