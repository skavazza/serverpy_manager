# Roadmap do ServerPy HTTP Manager

> Última atualização: 2026-10-24
> Status: Ativo

## Visão geral

O ServerPy HTTP Manager oferece compartilhamento e acesso a arquivos, rede e
periféricos em um aplicativo desktop Python/PySide6. A conectividade Android
usa ADB autorizado pelo usuário; a próxima melhoria adicionará controle visual
do aparelho via scrcpy.

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
  - **Validado:** testes automatizados e suíte completa (253 testes; 4 ignorados).
  - **Observação:** o teste com aparelho revelou que o ADB bundled no scrcpy
    foi extraído sem permissão de execução no Linux; o instalador agora preserva
    modos executáveis e repara instalações gerenciadas já existentes. A
    instalação existente foi reparada; scrcpy está em modo 0755 e o ADB
    bundled em 0775. `adb version` e `adb devices -l` passaram, com o Samsung
    SM_G990E detectado como autorizado. O usuário confirmou que a janela scrcpy
    abriu e permite controlar o aparelho.
  - **Pendente:** validar Windows em execução.
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
  - **Dependências:** `ANDR-007`

## Decisões e notas

| Data | Decisão | Justificativa |
|------|---------|---------------|
| 2026-10-24 | O controle Android terá uma aba própria; a primeira fase focará em USB e scrcpy. | Separar o fluxo Android das ferramentas genéricas de dispositivos e entregar primeiro uma conexão física simples de diagnosticar. |
| 2026-10-24 | Depuração USB e autorização do computador permanecem ações manuais; instalação de APK requer confirmação. | Preservar consentimento explícito e evitar alterações silenciosas no aparelho. |
| 2026-10-24 | Sincronização do clipboard vem desativada e rotação manual mostra como restaurar a rotação automática. | Evitar expor conteúdo copiado sem ação explícita e deixar claro que o controle de rotação altera a preferência do Android. |
| 2026-10-24 | Pareamento Wi-Fi fica para uma fase posterior. | Reduzir o escopo inicial e validar primeiro o ciclo USB e o controle visual. |
