param([string]$Python = 'python')
$ErrorActionPreference = 'Stop'
$pythonExe = (Get-Command $Python -ErrorAction Stop).Source
$launcher = Join-Path $PSScriptRoot 'run.py'
$requirements = Join-Path $PSScriptRoot 'requirements.txt'
& $pythonExe -c 'import numpy, scipy'
if ($LASTEXITCODE -ne 0) { throw ('Install dependencies: "' + $pythonExe + '" -m pip install -r "' + $requirements + '"') }
$settings = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'startup.json') -Raw | ConvertFrom-Json
$webHost = if ($settings.host -eq '0.0.0.0') { '127.0.0.1' } else { $settings.host }
$url = 'http://' + $webHost + ':' + $settings.port
$listener = @(Get-NetTCPConnection -LocalPort $settings.port -State Listen -ErrorAction SilentlyContinue)
if ($listener.Count) {
    $existing = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $listener[0].OwningProcess)
    if (-not $existing -or $existing.CommandLine -notlike ('*' + $launcher + '*')) {
        throw ('Port is occupied by another service: ' + $settings.port)
    }
    $health = Invoke-RestMethod ($url + '/api/health') -TimeoutSec 35
    if (-not $health.ok) { throw 'Service health check failed.' }
    [pscustomobject]@{Role='trainee';URL=$url;ProcessId=$existing.ProcessId;State='already running'}
    return
}
$logDir = Join-Path $PSScriptRoot 'log'
New-Item -ItemType Directory -Path $logDir -Force | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$stdout = Join-Path $logDir ('launcher-' + $stamp + '.log')
$stderr = Join-Path $logDir ('launcher-' + $stamp + '.err.log')
$process = Start-Process -FilePath $pythonExe -ArgumentList @('-X','utf8','-u',('"' + $launcher + '"')) -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
try {
    $deadline = [DateTime]::UtcNow.AddSeconds(40)
    $healthy = $false
    while ([DateTime]::UtcNow -lt $deadline) {
        $process.Refresh()
        if ($process.HasExited) { throw ('Startup failed: ' + (Get-Content -LiteralPath $stderr -Raw)) }
        try {
            $health = Invoke-RestMethod ($url + '/api/health') -TimeoutSec 35
            if ($health.ok) { $healthy = $true; break }
        } catch { Start-Sleep -Milliseconds 200 }
    }
    if (-not $healthy) { throw ('Health check timed out; inspect ' + $stderr) }
} catch {
    if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue }
    throw
}
[pscustomobject]@{Role='trainee';URL=$url;ProcessId=$process.Id;State='started'}
