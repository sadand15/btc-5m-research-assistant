$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$pidFile = Join-Path $taskRoot 'runtime\launcher.pid'
if (Test-Path -LiteralPath $pidFile) {
    $oldServiceId = [int](Get-Content -LiteralPath $pidFile)
    $oldService = Get-CimInstance Win32_Process -Filter "ProcessId=$oldServiceId"
    if ($oldService) {
        if (-not ($oldService.CommandLine.Contains("$taskRoot\.venv\Scripts\python.exe") -and $oldService.CommandLine.Contains('app.py'))) {
            throw 'Recorded PID belongs to another process; refusing to stop it.'
        }
        & taskkill.exe /PID $oldServiceId /T /F
        if ($LASTEXITCODE -ne 0) { throw 'Could not stop the previous service.' }
    }
}
$service = Start-Process -FilePath "$taskRoot\.venv\Scripts\python.exe" -ArgumentList @('-u','app.py') -WorkingDirectory $taskRoot -WindowStyle Hidden -RedirectStandardOutput "$taskRoot\runtime\background.stdout.log" -RedirectStandardError "$taskRoot\runtime\background.stderr.log" -PassThru
$service.Id | Set-Content -LiteralPath $pidFile
Write-Output "Started PID=$($service.Id). Mobile dashboard: http://<PC-LAN-IP>:8502"
