# Registers a Windows Task Scheduler job that polls every N minutes.
# Run this once, from an elevated or normal PowerShell prompt, adjusting
# $ToolPath / $ConfigPath / $IntervalMinutes as needed.

param(
    [string]$ToolPath = "$PSScriptRoot\..",
    [string]$ConfigPath = "config\config.yaml",
    [string]$PythonPath,
    [int]$IntervalMinutes = 5,
    [switch]$Uninstall
)

$ToolPath = [System.IO.Path]::GetFullPath($ToolPath)
if (-not [System.IO.Path]::IsPathRooted($ConfigPath)) {
    $ConfigPath = Join-Path $ToolPath $ConfigPath
}
$ConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
$DefaultConfigPath = [System.IO.Path]::GetFullPath((Join-Path $ToolPath "config\config.yaml"))
$TaskName = "UnityBuildBot"
if (-not [string]::Equals($ConfigPath, $DefaultConfigPath, [System.StringComparison]::OrdinalIgnoreCase)) {
    $ConfigName = [System.IO.Path]::GetFileNameWithoutExtension($ConfigPath) -replace '[^A-Za-z0-9]', '-'
    $Hasher = [System.Security.Cryptography.SHA256]::Create()
    try {
        $HashBytes = $Hasher.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($ConfigPath.ToLowerInvariant()))
    } finally {
        $Hasher.Dispose()
    }
    $ConfigHash = [System.BitConverter]::ToString($HashBytes).Replace('-', '').Substring(0, 8).ToLowerInvariant()
    $TaskName = "UnityBuildBot-$ConfigName-$ConfigHash"
}

if ($Uninstall) {
    $task = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($null -ne $task) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed scheduled task '$TaskName'."
    } else {
        Write-Host "Scheduled task '$TaskName' is not installed."
    }
    exit 0
}

if (-not $PythonPath) {
    $PythonPath = Join-Path $ToolPath ".venv\Scripts\python.exe"
}
if (-not (Test-Path -Path $PythonPath -PathType Leaf)) {
    throw "Python virtual environment not found at '$PythonPath'. Run the Python setup first."
}
if (-not (Test-Path -LiteralPath $ConfigPath -PathType Leaf)) {
    throw "Config file not found at '$ConfigPath'."
}

$action = New-ScheduledTaskAction -Execute $PythonPath `
    -Argument "-m unity_build_bot run --config `"$ConfigPath`"" `
    -WorkingDirectory $ToolPath

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)

$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 6)

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force

Write-Host "Registered scheduled task '$TaskName' for '$ConfigPath' running every $IntervalMinutes minute(s)."
