<#
.SYNOPSIS
    Forca o compartilhamento de rede de uma pasta no Windows 11.

.DESCRIPTION
    - Se auto-eleva para Administrador
    - Deixa o usuario escolher a pasta (janela grafica) ou recebe via -Pasta
    - Ativa servicos, SMB, descoberta de rede e regras de firewall
    - Cria o compartilhamento SMB e ajusta as permissoes NTFS (leitura ou leitura+escrita)

.EXAMPLE
    .\compartilhar-pasta.ps1
    .\compartilhar-pasta.ps1 -Pasta "D:\Projetos" -Nome "Projetos" -Usuario "Todos" -Acesso Escrita
    .\compartilhar-pasta.ps1 -SemSenha   # permite acesso sem senha (menos seguro)
#>

param(
    [string]$Pasta,
    [string]$Nome,
    [string]$Usuario,
    [ValidateSet("Leitura", "Escrita")]
    [string]$Acesso,
    [switch]$SemSenha
)

# ---------------------------------------------------------------
# 1) Auto-elevacao para Administrador
# ---------------------------------------------------------------
$id = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($id)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    Write-Host "Solicitando privilegios de administrador..." -ForegroundColor Yellow
    $argLista = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    foreach ($chave in $PSBoundParameters.Keys) {
        $valor = $PSBoundParameters[$chave]
        if ($valor -is [switch]) {
            if ($valor.IsPresent) { $argLista += "-$chave" }
        }
        else {
            $argLista += "-$chave"
            $argLista += "`"$valor`""
        }
    }
    Start-Process powershell.exe -Verb RunAs -ArgumentList $argLista
    exit
}

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------
# 2) Escolha da pasta
# ---------------------------------------------------------------
if (-not $Pasta) {
    Add-Type -AssemblyName System.Windows.Forms
    $dialogo = New-Object System.Windows.Forms.FolderBrowserDialog
    $dialogo.Description = "Escolha a pasta que deseja compartilhar na rede"
    $dialogo.ShowNewFolderButton = $true
    $topo = New-Object System.Windows.Forms.Form
    $topo.TopMost = $true
    if ($dialogo.ShowDialog($topo) -ne [System.Windows.Forms.DialogResult]::OK) {
        Write-Host "Nenhuma pasta selecionada. Saindo." -ForegroundColor Red
        Read-Host "Pressione ENTER para fechar"
        exit
    }
    $Pasta = $dialogo.SelectedPath
}

if (-not (Test-Path -LiteralPath $Pasta -PathType Container)) {
    Write-Host "A pasta '$Pasta' nao existe." -ForegroundColor Red
    Read-Host "Pressione ENTER para fechar"
    exit 1
}
$Pasta = (Resolve-Path -LiteralPath $Pasta).Path.TrimEnd('\')
if ($Pasta.Length -le 3) { $Pasta = $Pasta + '\' }

# ---------------------------------------------------------------
# 3) Nome, usuario e tipo de acesso
# ---------------------------------------------------------------
if (-not $Nome) {
    $padrao = Split-Path $Pasta -Leaf
    if (-not $padrao) { $padrao = "Compartilhado" }
    $entrada = Read-Host "Nome do compartilhamento [$padrao]"
    $Nome = if ($entrada) { $entrada } else { $padrao }
}
$Nome = ($Nome -replace '[\\/:*?"<>|]', '_').Trim()

# Resolve o grupo "Todos/Everyone" pelo SID (funciona em qualquer idioma)
$sidTodos = New-Object Security.Principal.SecurityIdentifier("S-1-1-0")
$nomeTodos = $sidTodos.Translate([Security.Principal.NTAccount]).Value

if (-not $Usuario) {
    $entrada = Read-Host "Usuario/grupo com acesso [$nomeTodos] (ENTER = todos)"
    $Usuario = if ($entrada) { $entrada } else { $nomeTodos }
}
$paraTodos = $Usuario -in @("Everyone", "Todos", $nomeTodos)
if ($paraTodos) { $Usuario = $nomeTodos }

if (-not $Acesso) {
    Write-Host ""
    Write-Host "Tipo de permissao:"
    Write-Host "  [1] Leitura e escrita"
    Write-Host "  [2] Somente leitura"
    $op = Read-Host "Escolha [1]"
    $Acesso = if ($op -eq "2") { "Leitura" } else { "Escrita" }
}

# ---------------------------------------------------------------
# 4) Preparar o Windows (servicos, SMB, rede, firewall)
# ---------------------------------------------------------------
Write-Host "`n[1/5] Ativando servicos de rede..." -ForegroundColor Cyan
$servicos = "LanmanServer", "LanmanWorkstation", "FDResPub", "fdPHost", "SSDPSRV", "upnphost"
foreach ($s in $servicos) {
    try {
        Set-Service -Name $s -StartupType Automatic -ErrorAction Stop
        if ((Get-Service $s).Status -ne "Running") { Start-Service $s -ErrorAction Stop }
        Write-Host "   OK  $s"
    }
    catch {
        Write-Host "   !!  $s : $($_.Exception.Message)" -ForegroundColor DarkYellow
    }
}

Write-Host "[2/5] Habilitando SMB..." -ForegroundColor Cyan
try {
    Set-SmbServerConfiguration -EnableSMB2Protocol $true -Force -Confirm:$false
    Write-Host "   OK  SMB2/SMB3 habilitado"
}
catch {
    Write-Host "   !!  $($_.Exception.Message)" -ForegroundColor DarkYellow
}

Write-Host "[3/5] Ajustando perfil de rede para Privado..." -ForegroundColor Cyan
try {
    Get-NetConnectionProfile |
        Where-Object { $_.NetworkCategory -eq "Public" } |
        ForEach-Object {
            Set-NetConnectionProfile -InterfaceIndex $_.InterfaceIndex -NetworkCategory Private
            Write-Host "   OK  '$($_.Name)' alterada de Publica para Privada"
        }
}
catch {
    Write-Host "   !!  $($_.Exception.Message)" -ForegroundColor DarkYellow
}

Write-Host "[4/5] Liberando firewall (Compartilhamento de Arquivos e Descoberta de Rede)..." -ForegroundColor Cyan
# Grupos identificados por recurso interno (independem do idioma do Windows)
$grupos = @(
    "@FirewallAPI.dll,-28502",  # Compartilhamento de Arquivo e Impressora
    "@FirewallAPI.dll,-32752"   # Descoberta de Rede
)
foreach ($g in $grupos) {
    try {
        Get-NetFirewallRule -Group $g -ErrorAction Stop | Set-NetFirewallRule -Enabled True -Profile Private, Domain
        Write-Host "   OK  Grupo $g"
    }
    catch {
        Write-Host "   !!  Grupo $g : $($_.Exception.Message)" -ForegroundColor DarkYellow
    }
}

if ($SemSenha) {
    Write-Host "   Desativando exigencia de senha (acesso sem senha)..." -ForegroundColor Yellow
    $lsa = "HKLM:\SYSTEM\CurrentControlSet\Control\Lsa"
    $srv = "HKLM:\SYSTEM\CurrentControlSet\Services\LanmanServer\Parameters"
    $cli = "HKLM:\SOFTWARE\Policies\Microsoft\Windows\LanmanWorkstation"
    Set-ItemProperty -Path $lsa -Name "everyoneincludesanonymous" -Value 1 -Type DWord
    Set-ItemProperty -Path $srv -Name "restrictnullsessaccess" -Value 0 -Type DWord
    if (-not (Test-Path $cli)) { New-Item -Path $cli -Force | Out-Null }
    Set-ItemProperty -Path $cli -Name "AllowInsecureGuestAuth" -Value 1 -Type DWord
    Set-SmbServerConfiguration -RejectUnencryptedAccess $false -Force -Confirm:$false
}

# ---------------------------------------------------------------
# 5) Criar o compartilhamento + permissoes NTFS
# ---------------------------------------------------------------
Write-Host "[5/5] Criando compartilhamento '$Nome'..." -ForegroundColor Cyan

if (Get-SmbShare -Name $Nome -ErrorAction SilentlyContinue) {
    Write-Host "   Ja existe um compartilhamento com esse nome. Recriando..." -ForegroundColor Yellow
    Remove-SmbShare -Name $Nome -Force -Confirm:$false
}

$parametrosShare = @{
    Name        = $Nome
    Path        = $Pasta
    Description = "Compartilhado via script PowerShell"
    ErrorAction = "Stop"
}
if ($Acesso -eq "Escrita") { $parametrosShare["ChangeAccess"] = $Usuario }
else { $parametrosShare["ReadAccess"] = $Usuario }
New-SmbShare @parametrosShare | Out-Null

# Permissao NTFS (a mais restritiva entre SMB e NTFS prevalece)
$alvoAcl = if ($paraTodos) { "*S-1-1-0" } else { $Usuario }
$nivel = if ($Acesso -eq "Escrita") { "M" } else { "RX" }
icacls "$Pasta" /grant "${alvoAcl}:(OI)(CI)$nivel" /T /C /Q | Out-Null

# ---------------------------------------------------------------
# Resultado
# ---------------------------------------------------------------
$pc = $env:COMPUTERNAME
$ips = Get-NetIPAddress -AddressFamily IPv4 |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -ExpandProperty IPAddress

Write-Host "`n=============================================" -ForegroundColor Green
Write-Host " Pasta compartilhada com sucesso!" -ForegroundColor Green
Write-Host "=============================================" -ForegroundColor Green
Write-Host " Pasta local : $Pasta"
Write-Host " Acesso      : $Usuario ($Acesso)"
Write-Host " Caminho     : \\$pc\$Nome"
foreach ($ip in $ips) { Write-Host "               \\$ip\$Nome" }
Write-Host "=============================================`n" -ForegroundColor Green

Read-Host "Pressione ENTER para fechar"
