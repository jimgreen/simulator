param(
  [int]$WebPort = 8780,
  [int]$Iec104Port = 2404,
  [string]$HostAddress = "127.0.0.1",
  [string]$Iec104Bind = "127.0.0.1"
)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
python .\server.py --host $HostAddress --port $WebPort --scada-root D:\codex\scada --iec104-bind $Iec104Bind --iec104-port $Iec104Port
