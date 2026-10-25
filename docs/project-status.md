# Estado do projeto e melhorias

Atualizado em 2026-10-24. Este documento resume o estado funcional e o trabalho
que ainda merece atenção. Os guias por funcionalidade estão em [`docs/`](.).

## Funcionalidades implementadas

- **Servidor HTTP e arquivos:** servidor desktop integrado, navegador web,
  pastas adicionais com permissões, autenticação, TLS, restrições de IP,
  operações de arquivos e PWA.
- **Rede e compartilhamento:** QR Codes, diagnóstico DNS/TCP/HTTP(S), atividade
  HTTP, Cloudflare Tunnel documentado e links temporários protegidos.
- **Transferências:** fila, progresso, cancelamento e publicação de uploads
  após conclusão.
- **SSH/SFTP:** autenticação por chave ou senha, verificação de chaves de host,
  terminal/comandos remotos, navegador SFTP e transferências em segundo plano.
- **Android:** ADB autorizado por USB, transferência de arquivos e
  encaminhamento reverso; espelhamento/controle scrcpy com configurações de
  vídeo e áudio, gravação, captura e instalação de APK com confirmação.
- **Integrações locais:** câmeras, scanners, impressoras, armazenamento USB,
  compartilhamento Windows e FindPort, conforme suporte do sistema e dos
  dispositivos.
- **Interface:** português e inglês; barra superior de ações com ícones para
  iniciar/parar, registros, copiar URL, navegador, QR Code e Sobre. Idioma pelo
  menu, sem a linha anterior de seletor e botão Sobre duplicados.

Veja os guias [Android](android.md), [SSH](ssh.md),
[transferências](transfers.md), [FindPort](findport.md),
[câmera](camera.md), [digitalização](scanning.md),
[impressão](printing.md) e [Cloudflare Tunnel](cloudflare-tunnel.md).

## Validação observada

- Suíte completa em Linux: 257 testes executados, 253 aprovados e 4 ignorados
  por dependências de PowerShell/Windows.
- Android real em Linux: Samsung SM_G990E autorizado; instalação existente do
  scrcpy reparada e controle visual confirmado pelo usuário.
- Suíte completa em Windows em 2026-10-24: 264 testes executados, 260 aprovados,
  3 falhas de permissões executáveis e 1 erro no teste de autostart Linux.
  Também foi observado `UnicodeEncodeError` no log HTTP com saída cp1252.
  Esses resultados não substituem a validação com dispositivos reais.
- Após a etapa de segurança de comandos: 277 testes executados em Windows,
  273 aprovados, mantendo as 3 falhas e o erro anteriores de compatibilidade.
  Os 24 testes direcionados de comandos e permissões/perfis/interface passaram.
- Após os limites HTTP: 286 testes executados em Windows, 282 aprovados,
  mantendo os mesmos 4 problemas anteriores de compatibilidade. Os 9 testes
  novos cobrem corpos inválidos/grandes/incompletos, timeout, saturação,
  expiração de IPs e limites/limpeza de ZIP, com preservação de arquivos.
- Após a etapa de instalação/compatibilidade: 296 testes aprovados em Windows,
  sem falhas ou erros. As quatro falhas anteriores de simulação foram corrigidas;
  o teste de log HTTP cp1252 também passou. `setup_env.py --check`, os launchers
  em modo `--check` e `pip check` passaram no ambiente existente.
- Instalação limpa Windows: dependências instaladas em venv novo sobre snapshot
  dos fontes, launcher/imports/`pip check` aprovados e 296 testes aprovados.
  Abertura Qt automatizada e Chrome passaram na raiz e em pasta adicional,
  incluindo 1440 px e 390 px com eventos de toque. Veja a [rodada Windows](windows-validation.md).
- ADB e scrcpy responderam no Windows; Samsung SM-G990E detectado como
  autorizado. Visualizador de câmera passou com imagens sintéticas.
- Instalação e execução da suíte atual em Linux nativo permanecem pendentes;
  Git Bash foi verificado em Windows e não substitui Linux.
- Após a segunda extração de manutenção: 300 testes aprovados no ambiente
  Windows existente; roteiro Qt/HTTP aprovado nas dez abas. A instalação limpa
  anterior permanece registrada com 296 testes e o snapshot daquela rodada.
- Primeiro ciclo de manutenção concluído: separação adicional de Android/USB
  e SSH/diagnósticos aprovada nos 300 testes e no roteiro Qt/HTTP das dez abas;
  caminhos públicos antigos de importação preservados.
- Clone publicado `6a2fac3` validado em venv novo: 300 testes, launcher,
  Qt/HTTP e Chrome aprovados, com arquivos rastreados inalterados. A API do
  GitHub confirmou `skavazza/serverpy_manager` privado; revisão limitada da
  árvore atual sem ocorrências dos padrões de credenciais/dados locais verificados.
- Barra de ações: 301 testes aprovados no ambiente Windows existente e
  roteiro Qt/HTTP nas dez abas aprovado. O teste da barra confere ações
  compartilhadas com menus, estados de início/parada, abertura de Sobre e
  nomes acessíveis traduzidos; a linha redundante de idioma/Sobre foi removida.
- Uso interativo no Windows, hardware físico de câmera/scanner/impressora e vários caminhos de
  rede precisam de validações específicas; testes simulados não substituem
  essas verificações.

## Melhorias priorizadas

O [roadmap](../ROADMAP.md) concentra tarefas, dependências e critérios de aceite.
A sequência atual é:

1. **Segurança de comandos — implementada:** autenticação administrativa para
   intents, timeout de 15 s, saída de até 1 MiB e uma execução por servidor
   (`SEC-001` e `SEC-002`). Veja a [política e limitações](system-intents.md).
2. **Recursos HTTP — implementados:** limites de corpos/uploads e conexões,
   expiração/capacidade do estado por IP e ZIP temporário em disco com limites
   (`HTTP-001` a `HTTP-003`). Veja os [valores e limitações](http-limits.md).
3. **Instalação e compatibilidade — parcialmente validada:** launchers alinhados,
   dependências fixadas, testes entre plataformas corrigidos e logs Unicode
   protegidos; instalação em venv novo e 296 testes passaram em Windows.
   Linux nativo continua pendente (`REL-001`, `QA-001` e `QA-002`). Veja o [guia](installation.md).
4. **Validação e entrega — em andamento:** fluxos automatizados Qt/HTTP/browser
   aprovados no Windows. `origin/main` foi clonado na revisão `6a2fac3`, FindPort
   incluído e privacidade do repositório confirmada. Faltam aceite de hardware,
   controle Android e Linux nativo (`QA-003`, `ANDR-007` e `REL-002`).
5. **Manutenção — primeiro ciclo concluído:** rotas POST de arquivos/recuperação separadas do
   handler principal em `src/core/file_http.py`, mantendo autenticação e
   permissões no fluxo. Montagem da configuração separada do controller em
   `src/gui/server_config.py`, com cópia das opções mutáveis para isolar a
   sessão. Android separado de unidades USB e SSH/SFTP separado de QR Code e
   diagnóstico, preservando os caminhos públicos de importação (`MAINT-001`).
6. **VPN e túneis — base técnica em desenvolvimento:** conectar duas
   instâncias como rede privada, servidor gerando convites individuais e
   acesso aos serviços do app pelo IP virtual. WireGuard é a base proposta;
   primeiro validar integração Windows, depois cadastro seguro, interface e
   duas máquinas reais. CGNAT/intermediário, LAN remota e saída de internet
   têm etapas próprias (`VPN-001` a `VPN-007`). Veja a [especificação](vpn.md).
   Geração de identidades em memória, planejamento de peers e diagnóstico
   inicial implementados; oito testes direcionados passaram. WireGuard não
   encontrado localmente; serviço e túnel real ainda não implementados.
   A segunda etapa acrescenta persistência DPAPI por usuário com criação
   atômica e planos de configuração/serviço sem execução. Vinte testes
   direcionados passaram, incluindo DPAPI real e falhas de persistência.
   A suíte completa terminou com `OK`, 321 testes; o wrapper PowerShell de
   redirecionamento marcou stderr como `NativeCommandError`, registrado no guia.
   Cadastro local SQLite acrescentado: convites com validade e uso único,
   pedidos pendentes, aprovação e revogação persistentes; 30 testes de VPN
   aprovados nesta etapa. Transporte autenticado, prova de posse da chave,
   interface e aplicação em túnel ativo permanecem pendentes.
   A aba VPN e túneis já oferece diagnóstico, preparação persistente, tokens
   locais e tabela de autorizações em português/inglês. Os 56 testes
   direcionados passaram e o roteiro Qt/HTTP aprovou as 11 abas; conexão,
   cadastro remoto e aplicação em túnel ativo continuam pendentes.
   A regressão completa após integrar a aba passou: 335 testes em Windows,
   código de saída zero (`artifacts/vpn-ui-regression.log`).
   Cliente HTTPS e formato portátil de convites acrescentados, com validação
   de certificado/nome/pin antes do envio do token. Seis testes do transporte
   passaram, incluindo HTTPS real em loopback; a aba confere convites sem
   conexão automática. Servidor de cadastro e prova da chave WireGuard pendentes.
   O servidor HTTPS de cadastro foi integrado à aba: iniciar/parar, selecionar
   certificado/chave existentes, gerar convites completos e enviar pedidos para
   aprovação local. Oito testes do listener e um fluxo com dois painéis passaram
   usando TLS real em loopback; túnel, prova da chave WireGuard e homologação
   entre máquinas reais permanecem pendentes.
   Regressão completa aprovada: 351 testes em Windows, código de saída zero;
   roteiro Qt/HTTP nas 11 abas aprovado nas duas dimensões de desktop.
   Integração WireGuard Windows acrescentada: servidor/cliente, perfil público,
   encerramento, assinatura dos executáveis, importador DPAPI SYSTEM oficial,
   rotas conflitantes e consulta de handshake. Vinte testes runtime/painel
   passaram com serviço simulado; o instalador oficial 1.1.1 foi baixado e teve
   assinatura verificada, sem execução. A máquina segue sem instalação/elevação
   e nenhum túnel real foi ativado. Veja o [guia Windows](wireguard-windows.md).
   A regressão completa passou com 365 testes e código de saída zero, além do
   roteiro Qt/HTTP nas 11 abas. Validação do serviço/driver reais continua pendente.
   Arquitetura unificada implementada: fábricas de identidade/túnel selecionam
   Windows ou Linux sem alterar convites, interface ou regras compartilhadas.
   Backend Ubuntu usa systemd-creds, wg/ip e configuração em memfd; testes Linux
   são simulados em Windows. Credenciais/kernel reais, helper administrativo e
   distribuição .deb permanecem pendentes. Veja o [guia](vpn-platforms.md).
   Regressão final desta etapa: 382 testes aprovados em Windows, código de saída
   zero, após repetição de uma conexão HTTP abortada na rodada inicial. Os 17
   testes novos cobrem seleção e simulação Linux; o roteiro Qt/HTTP passou.
   A validação final do executável com VPN passa a incluir esse novo escopo.
7. **Android por Wi-Fi:** permanece no backlog após estabilização (`ANDR-008`).

O roadmap também preserva o histórico de controle por USB, scrcpy e pareamento.
A análise técnica detalhada e as decisões ainda abertas
estão nos documentos `.planning/` locais; esses documentos são ignorados pelo
Git nesta configuração multi-repositório.
