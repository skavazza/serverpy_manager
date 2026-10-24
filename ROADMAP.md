# Roadmap do ServerPy HTTP Manager

> Última atualização: 2026-10-24
> Status: Ativo

## Visão geral

O ServerPy HTTP Manager oferece compartilhamento e acesso a arquivos, rede e
periféricos em um aplicativo desktop Python/PySide6. A conectividade Android
usa ADB autorizado pelo usuário e já oferece controle visual via scrcpy,
com validação real no Windows ainda pendente.

## Fluxo de melhorias: segurança, estabilidade e entrega

Este fluxo organiza os achados da análise de 2026-10-24. As caixas e evidências
de cada tarefa distinguem implementação concluída de trabalho pendente.
Não há novas datas de entrega definidas.

**Ordem:** proteção de comandos → limites HTTP → instalação e compatibilidade
→ validação real e release → manutenção gradual → novos recursos Android.

### Etapa 1 — Proteger a execução de comandos

- [x] `SEC-001` — Exigir autenticação para habilitar intents
  - **Prioridade:** Crítica; primeira entrega.
  - **Problema:** `/api/intent` permite executar comandos com `shell=True`
    quando intents estão habilitados, inclusive sem login configurado.
  - **Critérios:** rejeitar essa configuração no núcleo do servidor e orientar
    o usuário na interface; exigir acesso de administrador na rota; testar
    ausência de credenciais, credenciais inválidas, usuário de pasta e
    administrador autorizado. Documentar o alcance da execução de comandos.
  - **Implementado em 2026-10-24:** validação antes de abrir a porta, orientação
    traduzida na interface e revalidação administrativa na rota.
  - **Referências:** [handlers](src/core/handlers.py),
    [servidor](src/core/server.py), [controller](src/gui/controller.py).
- [x] `SEC-002` — Limitar a execução de intents
  - **Prioridade:** Alta.
  - **Dependências:** `SEC-001`.
  - **Critérios:** definir timeout, limite de saída e concorrência; tratar
    encerramento e erros sem bloquear a interface; avaliar comandos permitidos
    e uso de argumentos sem shell, documentando a política escolhida e a
    compatibilidade com comandos existentes.
  - **Implementado em 2026-10-24:** uma execução por servidor, timeout de 15 s,
    saída combinada de 1 MiB, corpo de 64 KiB e entrada padrão fechada.
    Shell preservado por compatibilidade, restrito ao administrador geral.
    Encerramento de descendentes é uma tentativa, não isolamento de processos.
  - **Validação direcionada:** 12 testes de autorização/execução e 12 testes
    de permissões/perfis/interface aprovados em Windows, incluindo timeout e
    limite de saída com processos reais e orientação traduzida antes de iniciar.
  - **Referências:** [executor](src/core/intents.py),
    [testes](tests/test_intents.py), [política de uso](docs/system-intents.md).
  - **Regressão em Windows:** 277 testes, 273 aprovados; permanecem as 3 falhas
    de permissões Linux e 1 erro de autostart anteriores, registrados em `QA-001`.

### Etapa 2 — Controlar o consumo de recursos HTTP

- [x] `HTTP-001` — Limitar corpos POST e uploads
  - **Prioridade:** Alta.
  - **Dependências:** `SEC-001`.
  - **Critérios:** definir limites explícitos por tipo de operação; validar
    `Content-Length`, rejeitar excesso com 413 e aplicar timeout de leitura;
    cobrir corpos inválidos/incompletos e preservar arquivos existentes em
    uploads interrompidos. Evitar leitura integral de uploads em memória.
  - **Implementado em 2026-10-24:** JSON de até 1 MiB, comandos de até 64 KiB,
    uploads de até 4 GiB, validação compartilhada de framing e prazos de leitura.
    Uploads permanecem em blocos e só são publicados após conclusão.
- [x] `HTTP-002` — Limitar conexões e estado de rate limit
  - **Prioridade:** Alta.
  - **Dependências:** `HTTP-001`.
  - **Critérios:** limitar handlers simultâneos, encerrar conexões ociosas e
    expirar entradas antigas por IP; verificar que saturação tem resposta
    controlada e que o servidor volta a atender após liberar recursos.
  - **Implementado em 2026-10-24:** até 16 conexões, timeout de inatividade,
    handshake TLS na thread limitada e histórico com até 4096 IPs, expirando
    após 60 s. Saturação retorna 503/fecha conexão; o estado de taxa cheio
    retorna 429 para novos IPs.
- [x] `HTTP-003` — Reduzir memória usada na geração de ZIP
  - **Prioridade:** Alta.
  - **Dependências:** `HTTP-002`.
  - **Critérios:** substituir o ZIP integral em memória por arquivo temporário
    ou streaming; definir limites e limpeza após erro/cancelamento; validar
    arquivos grandes, autorização e preservação dos arquivos de origem.
  - **Implementado em 2026-10-24:** arquivo temporário em disco, uma operação
    por vez, até 1 GiB de origem/resultado, 10.000 entradas e 120 s de geração;
    envio pelo monitor de transferências com cancelamento e limpeza do temporário.
  - **Política da etapa:** [limites e configuração](docs/http-limits.md).
  - **Validação em Windows:** 9 testes novos de recursos HTTP aprovados;
    regressão completa com 286 testes, 282 aprovados e os mesmos 4 problemas
    anteriores de compatibilidade registrados em `QA-001`.
  - **Referências da etapa:** [handlers](src/core/handlers.py),
    [servidor](src/core/server.py), [transferências](src/core/transfers.py).

### Etapa 3 — Tornar instalação e testes consistentes

- [~] `REL-001` — Alinhar launchers e dependências
  - **Prioridade:** Alta.
  - **Dependências:** etapa 2 concluída para o marco de estabilização.
  - **Critérios:** conferir todas as dependências, incluindo qrcode e paramiko;
    interromper o launcher quando a instalação falhar; definir versões
    testadas/reproduzíveis e validar primeiro início e ambiente existente
    incompleto no Windows e Linux.
  - **Implementado em 2026-10-24:** preparador compartilhado com verificação de
    versões/imports, instalação pelo Python do venv, interrupção em erro e
    revalidação em processo novo. Versões diretas/indiretas fixadas; ambientes
    incompatíveis preservados e modo `--check` nos dois launchers.
  - **Validado:** Windows e Git Bash, falhas de instalação simuladas, caminhos
    com espaços, imports e `pip check`. Suíte completa: 296 testes aprovados em
    Windows, sem falhas ou erros. Sem bundles nesta etapa.
  - **Instalação limpa Windows:** dependências instaladas em venv novo sobre
    snapshot dos fontes locais, com manifesto SHA-256, imports, `pip check` e
    launcher verificados; 296 testes aprovados no ambiente novo. Veja a
    [validação Windows](docs/windows-validation.md).
  - **Pendente:** instalação e validação nativas Linux. WSL indisponível
    nesta máquina; Git Bash não substitui Linux.
  - **Guia:** [instalação e evidências](docs/installation.md).
  - **Referências:** [Windows](start.bat), [Linux](start.sh),
    [requisitos](requirements.txt).
- [~] `QA-001` — Corrigir os testes entre plataformas
  - **Prioridade:** Alta.
  - **Critérios:** corrigir isolamento/simulação do autostart Linux e as
    verificações de permissões executáveis em Windows; executar a suíte nos
    dois sistemas, registrando resultados e motivos de eventuais skips.
    Distinguir falha do teste de defeito funcional antes de alterar produção.
  - **Evidência em Windows, 2026-10-24:** 264 testes executados, 260 aprovados,
    3 falhas de permissões executáveis e 1 erro no teste de autostart Linux.
  - **Correção em 2026-10-24:** teste de autostart isolado no ramo Linux;
    testes de executáveis verificam o chmod solicitado em Windows e os bits
    reais quando executados em POSIX. Os quatro casos anteriores passaram no
    Windows após corrigir as simulações, sem alterar os instaladores de produção.
  - **Regressão atual em Windows:** 296 testes aprovados, sem falhas ou erros.
  - **Pendente:** executar a suíte atual em Linux nativo.
  - **Referências:** [Android](tests/test_android.py),
    [autostart](tests/test_startup.py).
- [x] `QA-002` — Tratar Unicode nos logs HTTP do Windows
  - **Prioridade:** Alta.
  - **Critérios:** reproduzir e corrigir o `UnicodeEncodeError` observado na
    saída cp1252 durante a suíte; garantir que caracteres não representáveis
    não interrompam o processamento da resposta HTTP e preservar a ocultação
    de tokens nos logs.
  - **Implementado em 2026-10-24:** fallback ASCII escapado após ocultar tokens;
    teste HTTP real com saída cp1252 confirma resposta 404 completa e mantém
    tokens de download ocultos em logs com Unicode.
  - **Referência:** [handlers](src/core/handlers.py).

### Etapa 4 — Validar uso real e preparar entrega privada

- [~] `QA-003` — Validar fluxos reais no Windows
  - **Prioridade:** Alta.
  - **Dependências:** `REL-001`, `QA-001`, `QA-002`.
  - **Critérios:** registrar instalação e abertura do app, autenticação,
    permissões por pasta, transferência/cancelamento e recuperação de arquivos;
    concluir o roteiro Android de `ANDR-007`. Registrar câmera, scanner e
    impressora por dispositivo disponível, mantendo indisponíveis como pendentes.
  - **Validado em 2026-10-24:** dez abas Qt em 980×760/1440×900, início/parada/
    reinício pelo controller, login, permissões e upload/download/recuperação
    em arquivos isolados. Interface Qt automatizada em modo offscreen.
  - **Navegador:** Chrome em 1440 px e 390 px com eventos de toque, na raiz e
    em pasta adicional; transferências, cancelamento, repetição, PWA, links e
    reconexão aprovados. Visualizador de câmera validado com imagens sintéticas.
  - **Android Windows:** ADB e scrcpy executáveis; Samsung SM-G990E autorizado
    detectado. Controle manual, câmera/microfone, scanner e impressora físicos
    continuam pendentes; `ANDR-007` permanece em andamento.
  - **Roteiros/evidências:** [validação Windows](docs/windows-validation.md),
    [instalação limpa](tests/run_clean_install.py),
    [interface Qt](tests/run_desktop_smoke.py).
- [ ] `REL-002` — Validar clone limpo e publicação privada
  - **Prioridade:** Alta após estabilização.
  - **Dependências:** etapas 1–3 e `QA-003`.
  - **Critérios:** validar clone limpo, dependências, FindPort incluído,
    documentação e ausência de credenciais/dados locais; registrar revisão e
    resultados antes de concluir a publicação privada em `skavazza/serverpy-http`.
    Distribuição pública e bundles continuam sujeitos aos termos de `LICENSE`.
  - **Preparação local:** snapshot selecionado com manifesto de arquivos e
    dependências instalado em venv novo. Clone de revisão publicada e publicação
    privada ainda pendentes; snapshot local não conclui esta tarefa.

### Etapa 5 — Reduzir o custo de manutenção

- [~] `MAINT-001` — Decompor módulos grandes gradualmente
  - **Prioridade:** Média.
  - **Dependências:** etapas 1–3.
  - **Critérios:** separar rotas HTTP, montagem de configuração, armazenamento
    e ferramentas de rede em mudanças pequenas; preservar contratos,
    preferências, permissões e traduções; executar testes de regressão de cada
    área alterada. Evitar uma reescrita geral.
  - **Primeiro incremento em 2026-10-24:** operações POST de arquivos e
    recuperação extraídas para `src/core/file_http.py`; o handler principal
    mantém seleção de raiz, autenticação e despacho antes da execução.
    Conflitos de publicação retornam uma única resposta 409, sem cair em
    uma segunda resposta 405. Teste de conflito confirma preservação da origem.
  - **Validação:** regressão de 296 testes aprovada, mais um teste novo de
    conflitos aprovado separadamente; smoke Chrome em pasta adicional aprovado
    em desktop/mobile com toque.
  - **Segundo incremento em 2026-10-24:** montagem de configuração e
    normalização de hostname extraídas para `src/gui/server_config.py`.
    O controller mantém validação de campos, mensagens traduzidas e ciclo do
    servidor. Opções mutáveis são copiadas para isolar a sessão em execução.
    Testes cobrem opções desativadas, exigência de administrador para intents
    e isolamento de permissões/CORS/redirecionamentos após mudanças na interface.
  - **Validação do segundo incremento:** 300 testes aprovados em Windows;
    roteiro Qt/HTTP aprovado nas dez abas, incluindo autenticação, permissões,
    transferências, recuperação e reinício do servidor.
  - **Pendente:** armazenamento e ferramentas de rede; seguir com extrações
    pequenas e regressão por área.
  - **Referências:** [handlers](src/core/handlers.py),
    [controller](src/gui/controller.py), [armazenamento](src/gui/storage.py),
    [rede](src/gui/network_tools.py).

Novas funcionalidades, incluindo `ANDR-008`, vêm após a estabilização e a
validação USB. O histórico Android abaixo permanece preservado.

## Marco atual: Controle visual Android por USB

> Data-alvo provisória: 2026-11-21
> Status: Ativo
> Objetivo: permitir selecionar um Android conectado por USB, espelhar sua tela
> e controlá-lo pelo computador através de uma aba Android dedicada.

### Critérios de aceitação do marco

- A aba Android é própria e reúne conexão, espelhamento e controles.
- scrcpy é obtido da fonte oficial, com verificação de integridade, para as
  plataformas suportadas; a instalação é por usuário e não exige alteração do
  `PATH` ou privilégios administrativos.
- A tela do telefone pode ser espelhada e controlada por mouse e teclado.
- Há botões para Voltar, Início, Apps recentes, energia/tela, volume, rotação,
  notificações e configurações rápidas.
- Área de transferência e envio de arquivos estão disponíveis; instalar APK
  exige confirmação explícita.
- Captura de imagem e gravação de tela podem ser iniciadas e encerradas pelo
  usuário.
- O app não ativa Depuração USB nem autoriza o computador no telefone; essas
  ações continuam sob controle explícito do usuário.
- Erros, desconexões e encerramento do espelhamento são apresentados sem
  bloquear a interface.
- Testes automatizados cobrem a integração e a documentação explica
  permissões, limitações e uso.

### Tarefas

- [x] `ANDR-003` — Baixar e validar scrcpy oficial para o sistema suportado <!-- completed: 2026-10-24 01:44 -->
  - **Prioridade:** Alta
  - **Critérios:** obter os artefatos oficiais adequados ao SO/arquitetura,
    verificar integridade antes de extrair, instalar na pasta de dados do
    usuário e reportar erros de download ou validação.
  - **Dependências:** `ANDR-002`
  - **Referência:** [src/core/scrcpy.py](src/core/scrcpy.py),
    [src/gui/storage.py](src/gui/storage.py), [tests/test_android.py](tests/test_android.py),
    [docs/android.md](docs/android.md)
- [x] `ANDR-004` — Criar aba Android e gerenciar sessões do dispositivo <!-- completed: 2026-10-24 01:53 -->
  - **Prioridade:** Alta
  - **Critérios:** listar dispositivos ADB autorizados, selecionar um aparelho,
    iniciar/parar scrcpy sem bloquear a interface e tratar desconexão e
    encerramento do app.
  - **Dependências:** `ANDR-003`
  - **Referência:** [src/gui/navigation.py](src/gui/navigation.py),
    [src/gui/storage.py](src/gui/storage.py), [tests/test_android.py](tests/test_android.py),
    [tests/test_language.py](tests/test_language.py)
- [x] `ANDR-005` — Implementar espelhamento e controles predefinidos <!-- completed: 2026-10-24 01:53 -->
  - **Prioridade:** Alta
  - **Critérios:** exibir a tela com entrada por mouse/teclado e disponibilizar
    Voltar, Início, Apps recentes, energia/tela, volume, rotação, notificações
    e configurações rápidas.
  - **Dependências:** `ANDR-004`
- [x] `ANDR-006` — Adicionar clipboard, arquivos, APK e captura/gravação <!-- completed: 2026-10-24 01:53 -->
  - **Prioridade:** Alta
  - **Critérios:** sincronizar clipboard com aviso sobre exposição do conteúdo,
    enviar arquivos, pedir confirmação antes de instalar APK e permitir
    capturar imagem/gravar tela.
  - **Dependências:** `ANDR-005`
- [~] `ANDR-007` — Validar e documentar controle Android
  - **Prioridade:** Alta
  - **Critérios:** testar integração nas plataformas suportadas, documentar
    instalação, autorização USB, limites e solução de problemas; rodar testes
    direcionados e a suíte de regressão aplicável.
  - **Dependências:** `ANDR-006`
  - **Validação anterior em Linux:** 257 testes executados, 253 aprovados e 4 ignorados.
  - **Observação:** o teste com aparelho revelou que o ADB bundled no scrcpy
    foi extraído sem permissão de execução no Linux; o instalador agora preserva
    modos executáveis e repara instalações gerenciadas já existentes. A
    instalação existente foi reparada; scrcpy está em modo 0755 e o ADB
    bundled em 0775. `adb version` e `adb devices -l` passaram, com o Samsung
    SM_G990E detectado como autorizado. O usuário confirmou que a janela scrcpy
    abriu e permite controlar o aparelho.
  - **Windows em 2026-10-24:** ADB 1.0.41 e scrcpy 5.0.1 responderam; Samsung
    SM-G990E detectado como autorizado. Ainda falta validar espelhamento e
    controles manualmente no Windows.
- [x] `ANDR-009` — Organizar e ampliar as configurações da sessão scrcpy <!-- completed: 2026-10-24 02:10 -->
  - **Prioridade:** Alta
  - **Critérios:** agrupar configurações em vídeo e comportamento da sessão;
    permitir escolha de resolução, codec, FPS e bitrate, além de áudio,
    tela ligada/desligada e opções da janela; preservar os padrões atuais.
  - **Validado:** suíte completa (255 testes; 4 ignorados), incluindo os
    argumentos de inicialização e as traduções da interface.
  - **Referência:** [src/gui/storage.py](src/gui/storage.py),
    [src/gui/i18n.py](src/gui/i18n.py), [tests/test_android.py](tests/test_android.py),
    [docs/android.md](docs/android.md).
- [x] `ANDR-010` — Adicionar configurações avançadas de áudio e orientação scrcpy <!-- completed: 2026-10-24 02:20 -->
  - **Prioridade:** Alta
  - **Critérios:** oferecer seletores para fonte, codec e bitrate de áudio e
    orientação da imagem na janela; passar somente opções válidas do scrcpy
    5.0.1, mantendo seus padrões quando nenhum ajuste for selecionado.
  - **Dependências:** `ANDR-009`
  - **Validado:** suíte completa (257 testes; 4 ignorados), incluindo os
    argumentos avançados e a tradução dos controles.
  - **Referência:** [src/gui/storage.py](src/gui/storage.py),
    [src/gui/i18n.py](src/gui/i18n.py), [tests/test_android.py](tests/test_android.py),
    [docs/android.md](docs/android.md).

## Concluído

- [x] `ANDR-001` — Conectar Android via ADB USB para transferência e acesso ao servidor <!-- completed: 2026-10-24 01:16 -->
  - **Referência:** [src/core/android.py](src/core/android.py),
    [src/gui/storage.py](src/gui/storage.py), [docs/android.md](docs/android.md)
- [x] `ANDR-002` — Instalar Platform-Tools oficial por usuário no Windows/Linux x86_64 <!-- completed: 2026-10-24 01:27 -->
  - **Referência:** [src/core/android.py](src/core/android.py),
    [tests/test_android.py](tests/test_android.py), [docs/android.md](docs/android.md)

## Backlog

- [ ] `ANDR-008` — Adicionar pareamento e controle Android por Wi-Fi
  - **Prioridade:** Backlog
  - **Critérios:** parear com autorização do usuário, conectar e reconectar
    dispositivos Android compatíveis sem remover o suporte USB.
  - **Dependências:** `ANDR-007` e etapas 1–4 do fluxo de melhorias.
  - **Limites:** usar pareamento moderno iniciado pelo usuário (`adb pair` e
    endpoint TLS anunciado); não ativar debugging ou `adb tcpip 5555`
    silenciosamente.

## Decisões e notas

| Data | Decisão | Justificativa |
|------|---------|---------------|
| 2026-10-24 | O controle Android terá uma aba própria; a primeira fase focará em USB e scrcpy. | Separar o fluxo Android das ferramentas genéricas de dispositivos e entregar primeiro uma conexão física simples de diagnosticar. |
| 2026-10-24 | Depuração USB e autorização do computador permanecem ações manuais; instalação de APK requer confirmação. | Preservar consentimento explícito e evitar alterações silenciosas no aparelho. |
| 2026-10-24 | Sincronização do clipboard vem desativada e rotação manual mostra como restaurar a rotação automática. | Evitar expor conteúdo copiado sem ação explícita e deixar claro que o controle de rotação altera a preferência do Android. |
| 2026-10-24 | Pareamento Wi-Fi fica para uma fase posterior. | Reduzir o escopo inicial e validar primeiro o ciclo USB e o controle visual. |
