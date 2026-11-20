param(
  [int]$WebPort = 8780,
  [int]$Iec104Port = 2404,
  [string]$HostAddress = "127.0.0.1",
  [string]$Iec104Bind = "127.0.0.1",
  [string]$WorkspaceRoot = "D:\codex\workspace",
  [string]$ModelDirectory = "",
  [string]$StateDirectory = "simulation/qinling/sqldb/simulator"
)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$modelArgs = @()
if ($ModelDirectory) { $modelArgs = @('--model-directory', $ModelDirectory) }
python .\server.py --host $HostAddress --port $WebPort --workspace-root $WorkspaceRoot --state-directory $StateDirectory @modelArgs --scada-root D:\codex\scada --iec104-bind $Iec104Bind --iec104-port $Iec104Port
