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
- Windows, hardware físico de câmera/scanner/impressora e vários caminhos de
  rede precisam de validações específicas; testes simulados não substituem
  essas verificações.

## Melhorias priorizadas

1. **Publicação privada no GitHub — pending:** preparar `skavazza/serverpy-http`
   para colaboradores autorizados e validar o clone limpo antes de marcar como
   concluído. O código do FindPort necessário fica em `vendor/findport/`;
   `scrcpy/` e `scrcpy-gui/` são checkouts de referência excluídos do repositório
   principal. Esta publicação não autoriza distribuição pública.
2. **Validação no Windows:** testar instalação de ADB/scrcpy, conexão USB,
   controles e launcher em ambiente Windows real.
3. **Instalação e release reproduzíveis:** alinhar verificações de dependências
   nos launchers, fixar versões testadas e decidir se haverá bundles por SO.
   Distribuir publicamente o software ou binários requer autorização conforme
   [`LICENSE`](../LICENSE).
4. **Android por Wi-Fi:** considerar somente o pareamento moderno iniciado pelo
   usuário (Wireless debugging, `adb pair` e endpoint TLS anunciado); não ativar
   debugging nem usar `adb tcpip 5555` silenciosamente.
5. **Limites de recursos HTTP:** avaliar limites explícitos para corpos de
   requisição/uploads, concorrência de handlers e estado de rate limit por IP.
6. **Manutenibilidade:** decompor gradualmente os módulos grandes, mantendo
   testes focados nas rotas HTTP, autorização e operações de arquivos.

O [roadmap Android](../ROADMAP.md) registra as tarefas de controle por USB,
scrcpy e pareamento. A análise técnica detalhada e as decisões ainda abertas
estão nos documentos `.planning/` locais; esses documentos são ignorados pelo
Git nesta configuração multi-repositório.
