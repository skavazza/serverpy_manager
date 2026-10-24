<#
.SYNOPSIS
    FindPort - Gerenciador Interativo de Portas e Firewall para Windows
.DESCRIPTION
    Audita portas abertas (TCP e UDP), detecta nivel de exposicao (Local vs Rede Exposta),
    identifica servicos conhecidos, permite encerrar processos ou bloquear portas no Firewall
    sem fechar a aplicacao, registra acoes em log de auditoria e permite restaurar regras.
#>

[CmdletBinding()]
param(
    [switch]$ApenasSeguras,
    [switch]$LibraryOnly
)

# Configuracao de codificacao para UTF-8 limpo no console
try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
    $OutputEncoding = [System.Text.Encoding]::UTF8
} catch {}

# Constantes globais
$Script:LogPath = Join-Path -Path $PSScriptRoot -ChildPath "findport_audit.log"

$Script:ProcessosCriticos = @(
    "System", "Idle", "Registry", "smss", "csrss", "wininit", 
    "services", "lsass", "svchost", "fontdrvhost", "winlogon", "spoolsv"
)

$Script:DicionarioPortas = @{
    21    = "FTP (Transferencia de arquivos)"
    22    = "SSH (Acesso remoto seguro)"
    53    = "DNS (Resolucao de nomes)"
    80    = "HTTP (Servidor Web)"
    135   = "RPC (Chamada de Procedimento Windows)"
    137   = "NetBIOS Name Service"
    138   = "NetBIOS Datagram Service"
    139   = "NetBIOS Session Service"
    443   = "HTTPS (Web Seguro / SSL)"
    445   = "SMB (Compartilhamento de Arquivos Windows)"
    1433  = "Microsoft SQL Server"
    1521  = "Oracle Database"
    2049  = "NFS (Network File System)"
    3000  = "Node.js / React / Grafana"
    3306  = "MySQL / MariaDB"
    3389  = "RDP (Area de Trabalho Remota)"
    4200  = "Angular Dev Server"
    5000  = "Flask / .NET / Docker Registry"
    5037  = "ADB (Android Debug Bridge)"
    5173  = "Vite Dev Server"
    5432  = "PostgreSQL Database"
    6379  = "Redis Cache"
    7070  = "AnyDesk (Acesso Remoto)"
    8000  = "Django / HTTP Dev Server"
    8080  = "HTTP Alternativo / Apache Tomcat / Dev"
    8081  = "Proxy / Metro Bundler / Dev"
    8086  = "InfluxDB / Dev Server"
    8888  = "Jupyter Notebook"
    9000  = "Portainer / SonarQube / PHP-FPM"
    9200  = "Elasticsearch"
    27017 = "MongoDB"
}

# =========================================================================
# FUNCOES DE SUPORTE E UTILITARIOS
# =========================================================================

function Test-IsAdmin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = [Security.Principal.WindowsPrincipal]$identity
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Write-AuditLog {
    param(
        [Parameter(Mandatory=$true)][string]$Acao,
        [Parameter(Mandatory=$true)][int]$Porta,
        [string]$Proto = "TCP",
        [int]$PIDNum = 0,
        [string]$Processo = "N/A",
        [string]$Detalhes = ""
    )

    $timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    $linhaLog = "[$timestamp] [$Acao] Proto: $Proto | Porta: $Porta | PID: $PIDNum | Processo: $Processo | $Detalhes"
    
    try {
        Add-Content -Path $Script:LogPath -Value $linhaLog -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch {}
}

function Get-ServicoConhecido {
    param([int]$Porta)
    if ($Script:DicionarioPortas.ContainsKey($Porta)) {
        return $Script:DicionarioPortas[$Porta]
    }
    return "-"
}

function Get-TipoExposicao {
    param([string]$Endereco)
    if ($Endereco -eq "127.0.0.1" -or $Endereco -eq "::1" -or $Endereco -like "*localhost*") {
        return "Local (PC)"
    }
    return "Rede / Aberta"
}

# =========================================================================
# AUDITORIA DE REGRAS DE FIREWALL
# =========================================================================

function Obter-RegrasBloqueadas {
    param([switch]$Strict)
    $regras = @()
    try {
        $fwRules = Get-NetFirewallRule -ErrorAction Stop | Where-Object { $_.Name -match '^FindPort_Block_(TCP|UDP)_[0-9]+$' }
        foreach ($r in $fwRules) {
            $portFilter = $r | Get-NetFirewallPortFilter -ErrorAction Stop
            $portaNum = if ($portFilter.LocalPort) { $portFilter.LocalPort } else { "N/A" }
            $proto = switch ([string]$portFilter.Protocol) { '6' { 'TCP' } '17' { 'UDP' } default { [string]$portFilter.Protocol } }
            $regras += [PSCustomObject]@{
                RuleName    = $r.Name
                DisplayName = $r.DisplayName
                Porta       = $portaNum
                Protocolo   = $proto
                Descricao   = $r.Description
                Enabled     = $r.Enabled
            }
        }
    } catch { if ($Strict) { throw } }
    return $regras
}

# =========================================================================
# COLETA E CLASSIFICACAO DE PORTAS (TCP & UDP)
# =========================================================================

function Obter-PortasAbertas {
    param(
        [bool]$FiltrarSeguras = $false,
        [string]$TermoBusca = "",
        [switch]$Strict
    )

    $regrasBloqueadas = Obter-RegrasBloqueadas
    $mapaBloqueadas = @{}
    foreach ($rb in $regrasBloqueadas) {
        if ($rb.Porta -ne "N/A" -and ([string]$rb.Enabled).ToLower() -in @('true', '1')) {
            $mapaBloqueadas["$($rb.Protocolo)_$($rb.Porta)"] = $true
        }
    }

    # 1. Coleta TCP Listen
    try {
        $tcpConns = @(Get-NetTCPConnection -ErrorAction Stop | Where-Object { $_.State -eq 'Listen' })
    } catch {
        if ($Strict) { throw }
        $tcpConns = @()
    }

    # 2. Coleta UDP
    try {
        $udpConns = @(Get-NetUDPEndpoint -ErrorAction Stop)
    } catch {
        if ($Strict) { throw }
        $udpConns = @()
    }

    # Cache de processos para otimizar desempenho
    $todosPids = @(@($tcpConns | ForEach-Object { $_.OwningProcess }) + @($udpConns | ForEach-Object { $_.OwningProcess })) | Select-Object -Unique
    $tabelaProcessos = @{}

    foreach ($pidItem in $todosPids) {
        if ($pidItem -eq 0) {
            $tabelaProcessos[$pidItem] = [PSCustomObject]@{
                ProcessName = "System Idle"
                Path        = "Kernel/Sistema"
            }
            continue
        }
        try {
            $proc = Get-Process -Id $pidItem -ErrorAction Stop
            $caminho = try { $proc.Path } catch { "Elevacao necessaria" }
            $inicio = try { $proc.StartTime.ToUniversalTime().Ticks.ToString() } catch { "" }
            $tabelaProcessos[$pidItem] = [PSCustomObject]@{
                ProcessName = $proc.ProcessName
                Path        = if ($caminho) { $caminho } else { "N/A" }
                Inicio      = $inicio
            }
        } catch {
            $tabelaProcessos[$pidItem] = [PSCustomObject]@{
                ProcessName = "Desconhecido"
                Path        = "N/A"
            }
        }
    }

    $lista = [System.Collections.Generic.List[PSCustomObject]]::new()

    # Processamento TCP
    foreach ($conn in $tcpConns) {
        $pidNum = $conn.OwningProcess
        $procInfo = $tabelaProcessos[$pidNum]
        $procName = if ($procInfo) { $procInfo.ProcessName } else { "PID: $pidNum" }
        $procPath = if ($procInfo) { $procInfo.Path } else { "N/A" }
        $porta = [int]$conn.LocalPort
        $endereco = $conn.LocalAddress
        $exposicao = Get-TipoExposicao -Endereco $endereco
        $servico = Get-ServicoConhecido -Porta $porta

        $podeFechar = "Nao"
        $categoria = "Outro"
        $motivo = ""

        if ($pidNum -eq 4 -or $Script:ProcessosCriticos -contains $procName) {
            $categoria = "Sistema Critico"
            $podeFechar = "NUNCA"
            $motivo = "Processo essencial do Windows"
        }
        elseif ($procName -like "*node*" -or $procName -like "*python*" -or $procName -like "*java*" -or $procName -like "*mysqld*" -or $procName -like "*postgres*" -or $Script:DicionarioPortas.ContainsKey($porta)) {
            $categoria = "Dev / Servidor Local"
            $podeFechar = "SIM"
            $motivo = "Servidor local ou ferramenta de desenvolvimento"
        }
        elseif ($procName -like "*steam*" -or $procName -like "*discord*" -or $procName -like "*spotify*" -or $procName -like "*torrent*" -or $procName -like "*anydesk*" -or $procName -like "*adb*" -or $procName -like "*Code*") {
            $categoria = "Aplicativo de Usuario"
            $podeFechar = "SIM"
            $motivo = "Aplicativo em segundo plano"
        }
        elseif ($procName -eq "svchost") {
            $categoria = "Servico do Windows"
            $podeFechar = "CUIDADO"
            $motivo = "Servico de rede/compartilhamento"
        }
        else {
            $categoria = "Aplicativo / Terceiros"
            $podeFechar = "SIM (Se inativo)"
            $motivo = "Aplicativo terceiro"
        }

        $estaBloqueada = $mapaBloqueadas.ContainsKey("TCP_$porta")
        $statusFw = if ($estaBloqueada) { "BLOQUEADA" } else { "Livre" }

        $lista.Add([PSCustomObject]@{
            Porta       = $porta
            Proto       = "TCP"
            Endereco    = $endereco
            Exposicao   = $exposicao
            PID         = $pidNum
            Processo    = $procName
            PodeFechar  = $podeFechar
            Firewall    = $statusFw
            Categoria   = $categoria
            Servico     = $servico
            Motivo      = $motivo
            Caminho     = $procPath
            Inicio      = $procInfo.Inicio
        })
    }

    # Processamento UDP
    foreach ($conn in $udpConns) {
        $pidNum = $conn.OwningProcess
        $procInfo = $tabelaProcessos[$pidNum]
        $procName = if ($procInfo) { $procInfo.ProcessName } else { "PID: $pidNum" }
        $procPath = if ($procInfo) { $procInfo.Path } else { "N/A" }
        $porta = [int]$conn.LocalPort
        $endereco = $conn.LocalAddress
        $exposicao = Get-TipoExposicao -Endereco $endereco
        $servico = Get-ServicoConhecido -Porta $porta

        $podeFechar = "Nao"
        $categoria = "Outro"
        $motivo = ""

        if ($pidNum -eq 4 -or $Script:ProcessosCriticos -contains $procName) {
            $categoria = "Sistema Critico"
            $podeFechar = "NUNCA"
            $motivo = "Processo essencial do Windows"
        }
        elseif ($procName -like "*steam*" -or $procName -like "*discord*" -or $procName -like "*torrent*") {
            $categoria = "Aplicativo de Usuario"
            $podeFechar = "SIM"
            $motivo = "Aplicativo de usuario (Voz/Streaming/Jogos)"
        }
        elseif ($procName -eq "svchost") {
            $categoria = "Servico do Windows"
            $podeFechar = "CUIDADO"
            $motivo = "Servico do Windows (DNS/DHCP/SSDP)"
        }
        else {
            $categoria = "Aplicativo / Terceiros"
            $podeFechar = "SIM (Se inativo)"
            $motivo = "Endpoint UDP terceiro"
        }

        $estaBloqueada = $mapaBloqueadas.ContainsKey("UDP_$porta")
        $statusFw = if ($estaBloqueada) { "BLOQUEADA" } else { "Livre" }

        $lista.Add([PSCustomObject]@{
            Porta       = $porta
            Proto       = "UDP"
            Endereco    = $endereco
            Exposicao   = $exposicao
            PID         = $pidNum
            Processo    = $procName
            PodeFechar  = $podeFechar
            Firewall    = $statusFw
            Categoria   = $categoria
            Servico     = $servico
            Motivo      = $motivo
            Caminho     = $procPath
            Inicio      = $procInfo.Inicio
        })
    }

    # Preserve diferentes enderecos e processos na mesma porta.
    $itens = $lista | Sort-Object Porta, Proto, Endereco, PID -Unique

    if ($FiltrarSeguras) {
        $itens = $itens | Where-Object { $_.PodeFechar -like "SIM*" }
    }

    if (-not [string]::IsNullOrWhiteSpace($TermoBusca)) {
        $termo = $TermoBusca.Trim().ToLower()
        $itens = $itens | Where-Object {
            $_.Porta.ToString() -like "*$termo*" -or
            $_.Processo.ToLower() -like "*$termo*" -or
            $_.Servico.ToLower() -like "*$termo*" -or
            $_.Categoria.ToLower() -like "*$termo*"
        }
    }

    return $itens
}

# =========================================================================
# ACOES: BLOQUEIO / DESBLOQUEIO / ENCERRAMENTO
# =========================================================================

function Bloquear-PortaFirewall {
    param(
        [int]$Porta,
        [string]$Proto = "TCP",
        [int]$PIDNum = 0,
        [string]$NomeProcesso = ""
    )

    if (-not (Test-IsAdmin)) {
        Write-Host ""
        Write-Host "ERRO: O bloqueio de portas no Firewall exige privilegios de Administrador!" -ForegroundColor Red
        Write-Host "Dica: Use o arquivo 'run.bat' ou a opcao [A] para reiniciar como Administrador." -ForegroundColor Yellow
        Start-Sleep -Seconds 2
        return $false
    }

    $ruleName = "FindPort_Block_${Proto}_${Porta}"
    $displayName = "FindPort: Bloqueio Porta $Porta ($Proto)"
    $desc = "Bloqueado pelo FindPort em $(Get-Date -Format 'dd/MM/yyyy HH:mm:ss') - App: $NomeProcesso"

    try {
        Remove-NetFirewallRule -Name $ruleName -ErrorAction SilentlyContinue

        New-NetFirewallRule -Name $ruleName `
                            -DisplayName $displayName `
                            -Direction Inbound `
                            -LocalPort $Porta `
                            -Protocol $Proto `
                            -Action Block `
                            -Description $desc `
                            -ErrorAction Stop | Out-Null

        Write-AuditLog -Acao "FIREWALL_BLOQUEADO" -Porta $Porta -Proto $Proto -PIDNum $PIDNum -Processo $NomeProcesso -Detalhes "Regra criada: $displayName"

        Write-Host ""
        Write-Host "[OK] Porta $Porta ($Proto) bloqueada com sucesso no Firewall do Windows!" -ForegroundColor Green
        Write-Host "O aplicativo continuara rodando normalmente, mas conexoes de rede serao rejeitadas." -ForegroundColor Cyan
        Start-Sleep -Seconds 2
        return $true
    } catch {
        Write-Host "Falha ao criar regra de Firewall: $_" -ForegroundColor Red
        Start-Sleep -Seconds 2
        return $false
    }
}

function Desbloquear-PortaFirewall {
    param(
        [string]$RuleName,
        [int]$Porta = 0,
        [string]$Proto = "TCP"
    )

    if (-not (Test-IsAdmin)) {
        Write-Host ""
        Write-Host "ERRO: O desbloqueio no Firewall exige privilegios de Administrador!" -ForegroundColor Red
        Write-Host "Dica: Use o arquivo 'run.bat' ou a opcao [A] para reiniciar como Administrador." -ForegroundColor Yellow
        Start-Sleep -Seconds 2
        return $false
    }

    try {
        Remove-NetFirewallRule -Name $RuleName -ErrorAction Stop
        Write-AuditLog -Acao "FIREWALL_DESBLOQUEADO" -Porta $Porta -Proto $Proto -Detalhes "Regra removida: $RuleName"

        Write-Host ""
        Write-Host "[OK] Regra removida com sucesso! A porta foi DESBLOQUEADA no Firewall." -ForegroundColor Green
        Start-Sleep -Seconds 2
        return $true
    } catch {
        Write-Host "Falha ao remover regra do Firewall: $_" -ForegroundColor Red
        Start-Sleep -Seconds 2
        return $false
    }
}

function Executar-Elevado {
    $scriptPath = $MyInvocation.MyCommand.Path
    if (-not $scriptPath) {
        $scriptPath = "$PSScriptRoot\find_ports.ps1"
    }
    Write-Host "Solicitando elevacao do Windows (UAC) para executar como Administrador..." -ForegroundColor Cyan
    Start-Process powershell -Verb RunAs -ArgumentList "-ExecutionPolicy Bypass -NoExit -File `"$scriptPath`""
}

# =========================================================================
# LOOP PRINCIPAL DA INTERFACE
# =========================================================================
if ($LibraryOnly) { return }
$filtroSegurasAtivo = $ApenasSeguras
$termoPesquisaAtivo = ""

while ($true) {
    Clear-Host
    $isAdmin = Test-IsAdmin

    Write-Host "===================================================================================================" -ForegroundColor Cyan
    Write-Host "                     FINDPORT - AUDITORIA DE REDE, PORTAS & FIREWALL (WINDOWS)                     " -ForegroundColor Cyan
    Write-Host "===================================================================================================" -ForegroundColor Cyan
    
    if ($isAdmin) {
        Write-Host "  STATUS: ADMINISTRADOR [Permissao Total: Processos & Regras de Firewall]" -ForegroundColor Green
    } else {
        Write-Host "  STATUS: USUARIO COMUM [Para gerenciar o Firewall, use o arquivo run.bat ou a opcao [A]]" -ForegroundColor Yellow
    }
    Write-Host "---------------------------------------------------------------------------------------------------" -ForegroundColor DarkGray

    # 1. Painel de portas bloqueadas no Firewall
    $regrasBloqueadas = Obter-RegrasBloqueadas
    if ($regrasBloqueadas.Count -gt 0) {
        Write-Host "  🛡️  PORTAS ATUALMENTE BLOQUEADAS POR VOCE NO FIREWALL:" -ForegroundColor Magenta
        $bIndex = 1
        foreach ($rb in $regrasBloqueadas) {
            Write-Host "     [B$bIndex] Porta $($rb.Porta) ($($rb.Protocolo)) - $($rb.DisplayName) | $($rb.Descricao)" -ForegroundColor Yellow
            $bIndex++
        }
        Write-Host "     (Pressione 'D' no menu abaixo para desbloquear qualquer uma delas)" -ForegroundColor DarkGray
        Write-Host "---------------------------------------------------------------------------------------------------" -ForegroundColor DarkGray
    }

    # 2. Carrega lista de portas
    Write-Host "Coletando conexoes de rede ativas (TCP Listen & UDP)..." -ForegroundColor Gray
    $portasAbertas = Obter-PortasAbertas -FiltrarSeguras $filtroSegurasAtivo -TermoBusca $termoPesquisaAtivo

    $filtroTxt = if ($filtroSegurasAtivo) { "Apenas seguras para fechar [ATIVO]" } else { "Todas as portas" }
    $buscaTxt = if (-not [string]::IsNullOrWhiteSpace($termoPesquisaAtivo)) { " | Busca: '$termoPesquisaAtivo'" } else { "" }
    Write-Host "Filtro: $filtroTxt$buscaTxt | Total encontrado: $($portasAbertas.Count)" -ForegroundColor White
    Write-Host ""

    # Cabecalho da tabela formatada
    $formato = "{0,-5} | {1,-6} | {2,-5} | {3,-7} | {4,-18} | {5,-13} | {6,-13} | {7,-11} | {8,-18}"
    Write-Host ($formato -f "#", "PORTA", "PROTO", "PID", "PROCESSO", "EXPOSICAO", "FECHAR?", "FIREWALL", "SERVICO / NOTA") -ForegroundColor Cyan
    Write-Host ("-" * 105) -ForegroundColor DarkGray

    $contador = 1
    $mapaIndices = @{}

    foreach ($item in $portasAbertas) {
        $mapaIndices[$contador] = $item
        
        $corLinha = "White"
        if ($item.PodeFechar -eq "NUNCA") {
            $corLinha = "DarkGray"
        } elseif ($item.Firewall -like "*BLOQUEADA*") {
            $corLinha = "Magenta"
        } elseif ($item.Exposicao -like "*Rede*") {
            $corLinha = "Yellow"
        } elseif ($item.PodeFechar -like "SIM*") {
            $corLinha = "Green"
        }

        $numFmt = "[$contador]"
        $procTrunc = if ($item.Processo.Length -gt 17) { $item.Processo.Substring(0, 14) + "..." } else { $item.Processo }
        $servTrunc = if ($item.Servico.Length -gt 17) { $item.Servico.Substring(0, 14) + "..." } else { $item.Servico }

        Write-Host ($formato -f $numFmt, $item.Porta, $item.Proto, $item.PID, $procTrunc, $item.Exposicao, $item.PodeFechar, $item.Firewall, $servTrunc) -ForegroundColor $corLinha
        $contador++
    }

    Write-Host ("-" * 105) -ForegroundColor DarkGray
    Write-Host "MENU DE OPCOES:" -ForegroundColor Cyan
    Write-Host "  [1-$($contador-1)] Selecionar numero para gerenciar (Encerrar Processo ou Bloquear no Firewall)" -ForegroundColor White
    Write-Host "  [B]     Buscar / Filtrar por texto (Porta, Processo ou Servico)" -ForegroundColor Yellow
    if (-not [string]::IsNullOrWhiteSpace($termoPesquisaAtivo)) {
        Write-Host "  [C]     Limpar busca ativa" -ForegroundColor Yellow
    }
    if ($regrasBloqueadas.Count -gt 0) {
        Write-Host "  [D]     Desbloquear porta(s) no Firewall" -ForegroundColor Magenta
    }
    Write-Host "  [F]     Alternar filtro de seguras: $(if ($filtroSegurasAtivo) {'[DESATIVAR]'} else {'[ATIVAR]'})" -ForegroundColor White
    Write-Host "  [R]     Recarregar lista" -ForegroundColor White
    if (-not $isAdmin) {
        Write-Host "  [A]     Reiniciar como Administrador (Elevar UAC)" -ForegroundColor Cyan
    }
    Write-Host "  [S/Q]   Sair" -ForegroundColor Gray
    Write-Host ""

    $escolha = Read-Host "Digite sua opcao"
    $escolha = $escolha.Trim()

    if ($escolha -match "^[sSqQ]$") {
        Write-Host "Encerrando FindPort. Ate logo!" -ForegroundColor Cyan
        break
    }
    elseif ($escolha -match "^[rR]$") {
        continue
    }
    elseif ($escolha -match "^[fF]$") {
        $filtroSegurasAtivo = -not $filtroSegurasAtivo
        continue
    }
    elseif ($escolha -match "^[bB]$") {
        $termo = Read-Host "Digite o termo para filtrar (ex: node, 8080, mysql, etc.)"
        $termoPesquisaAtivo = $termo
        continue
    }
    elseif ($escolha -match "^[cC]$") {
        $termoPesquisaAtivo = ""
        continue
    }
    elseif ($escolha -match "^[aA]$" -and -not $isAdmin) {
        Executar-Elevado
        break
    }
    elseif ($escolha -match "^[dD]$") {
        # Menu de Desbloqueio
        Clear-Host
        Write-Host "===================================================================================================" -ForegroundColor Magenta
        Write-Host "                             DESBLOQUEIO DE PORTAS NO FIREWALL                                    " -ForegroundColor Magenta
        Write-Host "===================================================================================================" -ForegroundColor Magenta
        
        $regrasBloqueadas = Obter-RegrasBloqueadas
        if ($regrasBloqueadas.Count -eq 0) {
            Write-Host "Nenhuma regra de bloqueio encontrada." -ForegroundColor Yellow
            Start-Sleep -Seconds 2
            continue
        }

        $i = 1
        foreach ($rb in $regrasBloqueadas) {
            Write-Host "  [$i] Porta $($rb.Porta) ($($rb.Protocolo)) - Nome: $($rb.DisplayName)" -ForegroundColor White
            if ($rb.Descricao) {
                Write-Host "      Info: $($rb.Descricao)" -ForegroundColor DarkGray
            }
            $i++
        }
        Write-Host ""
        Write-Host "  [T] Desbloquear TODAS as portas bloqueadas" -ForegroundColor Yellow
        Write-Host "  [0] Voltar ao menu principal" -ForegroundColor Gray
        Write-Host ""

        $desbEscolha = Read-Host "Escolha o numero da porta para desbloquear"
        if ($desbEscolha -eq "0" -or [string]::IsNullOrWhiteSpace($desbEscolha)) {
            continue
        }
        elseif ($desbEscolha -match "^[tT]$") {
            foreach ($rb in $regrasBloqueadas) {
                $pNum = if ($rb.Porta -as [int]) { [int]$rb.Porta } else { 0 }
                Desbloquear-PortaFirewall -RuleName $rb.RuleName -Porta $pNum -Proto $rb.Protocolo
            }
        }
        elseif ($desbEscolha -as [int] -and [int]$desbEscolha -ge 1 -and [int]$desbEscolha -le $regrasBloqueadas.Count) {
            $regraSelecionada = $regrasBloqueadas[[int]$desbEscolha - 1]
            $pNum = if ($regraSelecionada.Porta -as [int]) { [int]$regraSelecionada.Porta } else { 0 }
            Desbloquear-PortaFirewall -RuleName $regraSelecionada.RuleName -Porta $pNum -Proto $regraSelecionada.Protocolo
        } else {
            Write-Host "Opcao invalida." -ForegroundColor Red
            Start-Sleep -Seconds 1
        }
        continue
    }

    # Se selecionou um numero da tabela
    if ($escolha -as [int] -and $mapaIndices.ContainsKey([int]$escolha)) {
        $selecionado = $mapaIndices[[int]$escolha]

        Clear-Host
        Write-Host "===================================================================================================" -ForegroundColor Cyan
        Write-Host "                  GERENCIAR PORTA $($selecionado.Porta) ($($selecionado.Proto))                    " -ForegroundColor Cyan
        Write-Host "===================================================================================================" -ForegroundColor Cyan
        Write-Host "  Porta:           $($selecionado.Porta) ($($selecionado.Proto))" -ForegroundColor White
        Write-Host "  Endereco IP:     $($selecionado.Endereco) -> Exposicao: $($selecionado.Exposicao)" -ForegroundColor $(if ($selecionado.Exposicao -like "*Rede*") { "Yellow" } else { "Green" })
        Write-Host "  Servico Notavel: $($selecionado.Servico)" -ForegroundColor White
        Write-Host "  Processo:        $($selecionado.Processo) (PID: $($selecionado.PID))" -ForegroundColor White
        Write-Host "  Executavel:      $($selecionado.Caminho)" -ForegroundColor DarkGray
        Write-Host "  Categoria:       $($selecionado.Categoria)" -ForegroundColor White
        Write-Host "  Pode Fechar?:    $($selecionado.PodeFechar) - $($selecionado.Motivo)" -ForegroundColor Yellow
        Write-Host "  Status Firewall: $($selecionado.Firewall)" -ForegroundColor White
        Write-Host "---------------------------------------------------------------------------------------------------" -ForegroundColor DarkGray
        Write-Host "O QUE VOCE DESEJA FAZER?" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  [1] Encerrar o processo (Finaliza o aplicativo e libera a porta)" -ForegroundColor Red
        Write-Host "  [2] Bloquear a porta no Firewall (SEM fechar o aplicativo)" -ForegroundColor Yellow
        Write-Host "  [0] Voltar ao menu principal" -ForegroundColor Gray
        Write-Host ""

        $acao = Read-Host "Selecione a acao desejada (1, 2 ou 0)"

        if ($acao -eq "1") {
            # Finalizar processo
            if ($selecionado.PodeFechar -eq "NUNCA") {
                Write-Host ""
                Write-Host "⚠️ BLOQUEIO DE SEGURANCA: O processo '$($selecionado.Processo)' (PID $($selecionado.PID)) e vital para o Windows!" -ForegroundColor Red
                Write-Host "Finaliza-lo causara tela azul ou travamento imediato do sistema." -ForegroundColor Red
                $forcar = Read-Host "Tem certeza absoluta? Digite 'SIM' em maiusculo para forcar"
                if ($forcar -ne "SIM") {
                    Write-Host "Operacao cancelada por seguranca." -ForegroundColor Green
                    Start-Sleep -Seconds 2
                    continue
                }
            } else {
                $conf = Read-Host "Confirma o encerramento de '$($selecionado.Processo)' (PID $($selecionado.PID))? (S/N)"
                if ($conf -notmatch "^[sSyY]") {
                    Write-Host "Operacao cancelada." -ForegroundColor Gray
                    Start-Sleep -Seconds 1
                    continue
                }
            }

            try {
                Stop-Process -Id $selecionado.PID -Force -ErrorAction Stop
                Write-AuditLog -Acao "PROCESSO_ENCERRADO" -Porta $selecionado.Porta -Proto $selecionado.Proto -PIDNum $selecionado.PID -Processo $selecionado.Processo -Detalhes "Processo encerrado pelo usuario"

                Write-Host ""
                Write-Host "[OK] Processo '$($selecionado.Processo)' (PID $($selecionado.PID)) encerrado! Porta $($selecionado.Porta) liberada." -ForegroundColor Green
                Start-Sleep -Seconds 2
            } catch {
                Write-Host ""
                Write-Host "Falha ao finalizar processo: $_" -ForegroundColor Red
                Write-Host "Dica: Execute via 'run.bat' como Administrador para obter permissao." -ForegroundColor Yellow
                Start-Sleep -Seconds 3
            }
        }
        elseif ($acao -eq "2") {
            # Bloquear porta no Firewall
            Bloquear-PortaFirewall -Porta $selecionado.Porta -Proto $selecionado.Proto -PIDNum $selecionado.PID -NomeProcesso $selecionado.Processo
        }
        else {
            Write-Host "Voltando ao menu..." -ForegroundColor Gray
        }
    } else {
        Write-Host "Opcao invalida. Digite o numero da porta ou uma letra do menu." -ForegroundColor Red
        Start-Sleep -Seconds 1
    }
}
