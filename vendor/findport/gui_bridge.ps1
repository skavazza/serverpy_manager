# Non-interactive adapter. The console entry point remains available unchanged.
[CmdletBinding()]
param(
    [ValidateSet('Snapshot', 'Block', 'Unblock', 'Stop')][string]$Action = 'Snapshot',
    [ValidateRange(0, 65535)][int]$Port = 0,
    [ValidateSet('TCP', 'UDP')][string]$Protocol = 'TCP',
    [int]$ProcessId = 0,
    [string]$ExpectedStarted = '',
    [int]$ProtectedProcessId = 0,
    [string]$ResultPath = '',
    [switch]$ImportOnly
)
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
. "$PSScriptRoot\find_ports.ps1" -LibraryOnly

function Invoke-GuiAction {
    if ($Action -eq 'Snapshot') {
        $warnings = @()
        $rules = @()
        try { $rules = @(Obter-RegrasBloqueadas -Strict) }
        catch { $warnings += $_.Exception.Message }
        $ports = @(Obter-PortasAbertas -Strict)
        return @{ ok = $true; ports = $ports; rules = $rules; warnings = $warnings }
    }
    if ($Port -lt 1) { throw 'Invalid port.' }
    if ($Action -eq 'Stop' -and ($ProcessId -le 4 -or $ProcessId -eq $ProtectedProcessId -or $ExpectedStarted -notmatch '^[0-9]+$')) {
        throw 'Protected process or missing process identity. Refresh the list.'
    }
    if (-not (Test-IsAdmin)) {
        if (-not $ResultPath) { throw 'A result path is required for elevation.' }
        $scriptLiteral = $PSCommandPath.Replace("'", "''")
        $resultLiteral = $ResultPath.Replace("'", "''")
        # Only validated enum/integer values and escaped path literals enter the command.
        $command = "& '$scriptLiteral' -Action '$Action' -Port $Port -Protocol '$Protocol' -ProcessId $ProcessId -ProtectedProcessId $ProtectedProcessId -ResultPath '$resultLiteral'"
        if ($Action -eq 'Stop') { $command += " -ExpectedStarted '$ExpectedStarted'" }
        $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($command))
        $child = Start-Process -FilePath "$PSHOME\powershell.exe" -Verb RunAs -WindowStyle Hidden -Wait -PassThru -ArgumentList @('-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-EncodedCommand', $encoded)
        if (-not (Test-Path -LiteralPath $ResultPath)) { throw 'The elevated operation did not return a result.' }
        return Get-Content -LiteralPath $ResultPath -Raw -Encoding UTF8 | ConvertFrom-Json
    }
    $ruleName = "FindPort_Block_${Protocol}_${Port}"
    $auditAction = ''
    $processName = 'N/A'
    # Verify audit-log access before performing a mutation.
    $auditStream = [IO.File]::Open($Script:LogPath, 'Append', 'Write', 'ReadWrite')
    $auditStream.Dispose()
    switch ($Action) {
        'Block' {
            $existing = @(Get-NetFirewallRule -ErrorAction Stop | Where-Object { $_.Name -eq $ruleName })
            if ($existing.Count) {
                $existing | Set-NetFirewallRule -Enabled True -Direction Inbound -Action Block -Profile Any -ErrorAction Stop | Out-Null
                $existing | Get-NetFirewallPortFilter -ErrorAction Stop | Set-NetFirewallPortFilter -Protocol $Protocol -LocalPort $Port -RemotePort Any -ErrorAction Stop | Out-Null
            } else {
                New-NetFirewallRule -Name $ruleName -DisplayName "FindPort: Bloqueio Porta $Port ($Protocol)" -Direction Inbound -Protocol $Protocol -LocalPort $Port -Action Block -Enabled True -Profile Any -ErrorAction Stop | Out-Null
            }
            $auditAction = 'FIREWALL_BLOQUEADO'
        }
        'Unblock' {
            # Exact managed name only: never remove unrelated firewall rules.
            $existing = @(Get-NetFirewallRule -ErrorAction Stop | Where-Object { $_.Name -eq $ruleName })
            if ($existing.Count) { $existing | Remove-NetFirewallRule -ErrorAction Stop }
            $auditAction = 'FIREWALL_DESBLOQUEADO'
        }
        'Stop' {
            $process = Get-Process -Id $ProcessId -ErrorAction Stop
            if ($Script:ProcessosCriticos -contains $process.ProcessName -or $process.Id -le 4 -or $process.Id -eq $ProtectedProcessId) {
                throw 'This process is protected.'
            }
            if ($process.StartTime.ToUniversalTime().Ticks.ToString() -ne $ExpectedStarted) {
                throw 'The process changed. Refresh the list.'
            }
            $endpoints = if ($Protocol -eq 'TCP') {
                @(Get-NetTCPConnection -ErrorAction Stop | Where-Object { $_.State -eq 'Listen' })
            } else { @(Get-NetUDPEndpoint -ErrorAction Stop) }
            if (-not ($endpoints | Where-Object { $_.LocalPort -eq $Port -and $_.OwningProcess -eq $ProcessId })) {
                throw 'The endpoint changed. Refresh the list.'
            }
            $processName = $process.ProcessName
            # Use the verified process object, not a fresh PID lookup.
            $process | Stop-Process -Force -ErrorAction Stop
            $auditAction = 'PROCESSO_ENCERRADO'
        }
    }
    $timestamp = (Get-Date).ToString('yyyy-MM-dd HH:mm:ss')
    Add-Content -LiteralPath $Script:LogPath -Encoding UTF8 -ErrorAction Stop -Value "[$timestamp] [$auditAction] Proto: $Protocol | Porta: $Port | PID: $ProcessId | Processo: $processName | GUI: $Action"
    return @{ ok = $true; message = 'Operation completed.' }
}

if ($ImportOnly) { return }
try { $result = Invoke-GuiAction }
catch { $result = @{ ok = $false; error = $_.Exception.Message } }
$json = ConvertTo-Json -InputObject $result -Depth 8 -Compress
if ($ResultPath) { [IO.File]::WriteAllText($ResultPath, $json, (New-Object System.Text.UTF8Encoding($false))) }
else { Write-Output $json }
if (-not $result.ok) { exit 1 }
