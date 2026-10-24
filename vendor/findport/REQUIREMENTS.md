# Especificação e Requisitos Técnicos para IAs e Desenvolvedores (FindPort)

Este documento define a arquitetura, regras de negócio, convenções de código e diretrizes de desenvolvimento para qualquer Inteligência Artificial (IA) ou desenvolvedor que for manter ou expandir o projeto **FindPort**.

---

## 1. Visão Geral do Projeto
O **FindPort** é uma ferramenta de auditoria e gerenciamento de portas de rede para **Windows** (desenvolvida em PowerShell e batch), permitindo a identificação de serviços em escuta, mitigação de riscos de rede e controle seletivo entre:
1. **Encerrar processo** (derrubar a aplicação associada).
2. **Bloquear a porta no Firewall do Windows** (isolar a porta da rede sem fechar o software).
3. **Desbloquear portas gerenciadas** (rastreabilidade reversível de regras criadas).

---

## 2. Princípios de Engenharia e Boas Práticas
Ao alterar o código, siga rigorosamente:
- **Clean Code & Single Responsibility**: Cada função do PowerShell deve ter apenas uma responsabilidade (ex: auditoria, firewall, manipulação de processos, interface de usuário).
- **Tratamento de Exceções Resiliente**: Chamadas como `Get-NetTCPConnection`, `Get-NetUDPEndpoint`, `Get-Process`, `New-NetFirewallRule` e `Stop-Process` devem sempre ser encapsuladas em blocos `try/catch` com fallback defensivo.
- **Segurança Operacional Primária**:
  - Processos vitais do Windows (PID 4, `System`, `svchost`, `lsass`, `wininit`, `csrss`, etc.) **nunca** devem ser finalizados silenciosamente. O script deve conter trava de confirmação explícita.
- **Rastreabilidade e Idempotência**:
  - Regras de firewall criadas pelo FindPort **devem** seguir a convenção de nomenclatura única `FindPort_Block_<PROTO>_<PORTA>`.
  - Se uma regra idêntica já existir, ela deve ser sobrescrita ou tratada sem lançar erro de duplicação.
  - Todas as ações destrutivas ou de firewall devem ser registradas em `findport_audit.log`.
- **Codificação de Caracteres**:
  - Sempre garantir saída `[Console]::OutputEncoding = [System.Text.Encoding]::UTF8` e scripts salvos com UTF-8 sem BOM para evitar corrupção de caracteres em consoles Windows.

---

## 3. Matriz de Componentes e Estrutura de Arquivos

```text
findport/
├── find_ports.ps1       # Script principal com lógica de auditoria, regras e menu interativo
├── run.bat              # Launcher para execução em 1 clique com auto-elevação UAC (Admin)
├── findport_audit.log   # Log de auditoria gerado automaticamente com histórico de ações
├── REQUIREMENTS.md      # Este documento de referência para IAs e desenvolvedores
└── README.md            # Documentação de uso amigável para o usuário final
```

---

## 4. Requisitos Funcionais

### RF-01: Auditoria Multi-Protocolo (TCP & UDP)
- Coletar portas em escuta TCP (`Get-NetTCPConnection -State Listen`).
- Coletar portas UDP ativas (`Get-NetUDPEndpoint`).
- Mapear cada endpoint para seu Processo (`ProcessName`, `PID`, `Path`).

### RF-02: Classificação de Exposição de Rede
- Analisar o IP de escuta (`LocalAddress`):
  - `127.0.0.1`, `::1` ou `localhost` ➔ Classificar como **`Apenas Local` (Baixo Risco)**.
  - `0.0.0.0`, `::`, `*` ou IP de interface de rede ➔ Classificar como **`Rede / Exposta` (Atenção/Risco)**.

### RF-03: Dicionário de Portas e Serviços Conhecidos
- Mapear portas padrão para rótulos explicativos:
  - `21`: FTP | `22`: SSH | `53`: DNS | `80`: HTTP | `443`: HTTPS
  - `135`/`139`/`445`: Windows RPC & Compartilhamento SMB
  - `1433`: MS SQL Server | `3306`: MySQL | `5432`: PostgreSQL | `6379`: Redis | `27017`: MongoDB
  - `3000`/`5000`/`5173`/`8080`/`8086`: Servidores Web de Desenvolvimento (Node/React/Vite/Python)
  - `3389`: Área de Trabalho Remota (RDP)
  - `5037`: Android Debug Bridge (ADB)
  - `7070`: AnyDesk

### RF-04: Gerenciamento de Firewall Idempotente
- **Bloqueio**: Criação de regra de entrada (`Direction Inbound`) bloqueando a porta específica no protocolo correto com `Action Block`.
- **Desbloqueio**: Identificação das regras com prefixo `FindPort_Block_*` e exclusão limpa via `Remove-NetFirewallRule`.

### RF-05: Busca e Filtros Rápidos
- Opção de filtrar portas por termo de busca (porta numérica, nome do processo ou categoria).
- Opção de alternar entre "Todas as Portas" e "Apenas Seguras para Fechar".

### RF-06: Log de Auditoria (`findport_audit.log`)
- Formato padrão em texto simples:
  `[YYYY-MM-DD HH:mm:ss] [ACAO] Protocolo: <PROTO> | Porta: <PORTA> | PID: <PID> | Processo: <NOME> | Detalhes: <MSG>`
- Ações registradas: `PROCESSO_ENCERRADO`, `FIREWALL_BLOQUEADO`, `FIREWALL_DESBLOQUEADO`.

### RF-07: Auto-Elevação UAC
- `run.bat` deve verificar se o processo possui privilégios de Administrador. Se não possuir, solicitar elevação via PowerShell `Start-Process powershell -Verb RunAs`.

---

## 5. Diretrizes para Modificações Futuras por IAs

### Integração com ServerPy HTTP Manager

- `find_ports.ps1 -LibraryOnly` disponibiliza as funções sem abrir o menu.
- `gui_bridge.ps1` fornece consultas e ações com resultado JSON. Consultas
  usam coleta estrita para distinguir falhas de uma lista vazia.
- O campo adicional `Inicio` contém os ticks UTC do início do processo,
  quando disponíveis; a GUI exige essa identidade para encerrar processos.
- A integração preserva endpoints com endereço/PID distintos na mesma porta.
- Ações da GUI pedem confirmação, solicitam UAC quando necessário e registram
  operações bem-sucedidas no mesmo arquivo de auditoria. Processos críticos
  são bloqueados para encerramento pela GUI, sem opção de forçar.
- Detalhes de uso e validação: [docs/findport.md](../docs/findport.md).

1. **Não quebre o formato do console**: O console interativo deve caber em uma largura padrão de 100-120 colunas sem quebras de linha desalinhadas.
2. **Preserve a consistência de tipos**: Campos retornados por funções de coleta devem manter nomes consistentes (`Porta`, `Proto`, `PID`, `Processo`, `Exposicao`, `PodeFechar`, `Firewall`, `ServicoConhecido`).
3. **Validação prévia**: Sempre use o analisador sintático do PowerShell para garantir que o script não possui erros antes de concluir edições.
