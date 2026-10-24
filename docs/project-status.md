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
- **Interface:** português e inglês.

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
   aprovados no Windows. Faltam aceite de hardware, controle Android, clone de
   revisão publicada e entrega privada (`QA-003`, `ANDR-007` e `REL-002`).
5. **Manutenção — iniciada:** rotas POST de arquivos/recuperação separadas do
   handler principal em `src/core/file_http.py`, mantendo autenticação e
   permissões no fluxo. Controller, armazenamento e rede continuam no plano
   de extrações graduais (`MAINT-001`).
6. **Novos recursos:** retomar Android por Wi-Fi após estabilização (`ANDR-008`).

O roadmap também preserva o histórico de controle por USB, scrcpy e pareamento.
A análise técnica detalhada e as decisões ainda abertas
estão nos documentos `.planning/` locais; esses documentos são ignorados pelo
Git nesta configuração multi-repositório.
