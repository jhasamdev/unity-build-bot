# Registers a Windows Task Scheduler job that polls every N minutes.
# Run this once, from an elevated or normal PowerShell prompt, adjusting
# $ToolPath / $ConfigPath / $IntervalMinutes as needed.

param(
    [string]$ToolPath = "$PSScriptRoot\..",
    [string]$ConfigPath = "$PSScriptRoot\..\config\config.yaml",
    [int]$IntervalMinutes = 5
)

$action = New-ScheduledTaskAction -Execute "python" `
    -Argument "-m unity_build_bot run --config `"$ConfigPath`"" `
    -WorkingDirectory $ToolPath

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

Register-ScheduledTask -TaskName "UnityBuildBot" -Action $action -Trigger $trigger -Force

Write-Host "Registered scheduled task 'UnityBuildBot' running every $IntervalMinutes minute(s)."
