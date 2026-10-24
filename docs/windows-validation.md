# Validação Windows — 2026-10-24

Esta rodada verifica o código de trabalho, incluindo mudanças ainda não
commitadas, em Windows 11 x64 com Python 3.14.3. O ambiente habitual foi
preservado; instalações e arquivos de teste ficaram em `artifacts/` e pastas
temporárias, com configurações Qt em um INI isolado.

## Instalação e abertura

Foi criada uma cópia selecionada dos fontes com manifesto SHA-256 e um `venv`
novo, sem acesso aos pacotes do ambiente habitual. O preparador instalou as
dependências fixadas pelo pip, reutilizando wheels do cache quando disponíveis.
Passaram imports, `pip check`, conferência de versões e `start.bat --check`.
A regressão nesse ambiente novo executou 296 testes, todos aprovados. O relatório
concluído desta rodada está em `artifacts/clean-install_ouvo0dfd/report.json`,
com manifesto, logs, capturas e retorno zero em todas as etapas. As capturas
Qt foram inspecionadas após carregar a fonte e o encerramento não registrou
erros de sinais Qt em trabalhadores de descoberta.

Isso valida uma instalação limpa das dependências sobre uma cópia dos fontes
atuais. Não equivale a clonar uma revisão publicada: o snapshot inclui mudanças
locais e não contém `.git`, configurações pessoais nem o ambiente habitual.

O roteiro Qt abre as dez abas em 980×760 e 1440×900, salva capturas e exercita
o controller contra um servidor HTTP real em loopback. Passaram:

- Início, parada e reinício do servidor pela configuração da interface.
- Rejeição sem login; download permitido ao leitor e escrita/comandos negados.
- Upload, download, exclusão e recuperação de arquivos temporários.
- Ausência de senhas de teste em texto puro no INI persistido.

A renderização usa o plugin Qt `offscreen`, com fonte Windows carregada
explicitamente. Os trabalhadores de descoberta de dispositivos terminam antes
do encerramento do roteiro. Isso é automação de interface, sem substituir uma
sessão de aceite manual com mouse, teclado e hardware real.

## Navegador

Chrome headless com perfil isolado passou nos fluxos de arquivos, busca,
recuperação, fila de transferências, cancelamento, repetição de upload, previews,
preferências, PWA, links temporários, download com senha e queda/retorno do servidor.
Os mesmos fluxos foram executados na raiz e em uma pasta adicional montada.

O desktop foi verificado em 1440×900; o mobile em 390×844 com emulação de toque
habilitada. Eventos de toque reais do navegador abriram/fecharam o painel de
pastas, e as verificações de largura não apontaram transbordamento horizontal.

O visualizador de câmera passou com JPEGs gerados: autenticação, redimensionamento,
alteração de FPS, PT/EN, pausa/retomada e parada/reinício. Foram usadas somente
imagens sintéticas; câmera e microfone físicos não foram abertos pelo roteiro.

## Android e pendências

No Windows, ADB respondeu com versão 1.0.41, scrcpy com versão 5.0.1 e o
Samsung SM-G990E foi detectado como autorizado pelo ADB. Isso confirma binários
executáveis e descoberta nesta máquina. Não conclui o aceite de espelhamento,
mouse/teclado, áudio, gravação ou instalação de APK.

Continuam pendentes:

- Controle visual Android no Windows com aceite manual.
- Câmera/microfone, scanner e impressora físicos.
- Instalação e regressão atuais em Linux nativo.
- Aceite final de hardware antes de concluir a entrega.

## Clone publicado e privacidade do repositório

Na rodada seguinte foi clonado diretamente `origin/main` de
`skavazza/serverpy_manager`, na revisão
`6a2fac32f12a4db2594a152b3b51e13ca82e6c80`, sem copiar os fontes do workspace.
A API do GitHub confirmou `private: true` e `visibility: private`.

O FindPort necessário está incluído em `vendor/findport/`. A revisão da árvore
rastreada não encontrou arquivos de banco, `.env`, certificados/chaves nem
pastas de dados locais; os padrões selecionados de chaves privadas e tokens
também não tiveram ocorrências. Essa verificação é da árvore atual e não
constitui auditoria completa do histórico ou de todos os formatos de segredo.

As evidências desta rodada ficam em `artifacts/clean-install__wh9np99/`, incluindo
manifesto, `source-review.json` e logs por etapa. Passaram a instalação em venv
novo, launcher, dez abas Qt/HTTP, Chrome na raiz e em pasta adicional e todos
os 300 testes da suíte. O relatório confirmou `tracked_worktree_clean: true`.
O aceite de dispositivos físicos
e a validação nativa Linux permanecem separados da publicação dos fontes.

## Reproduzir e localizar evidências

```powershell
.\venv\Scripts\python.exe tests/run_clean_install.py
```

Para baixar e validar a revisão publicada no remoto, use:

```powershell
.\venv\Scripts\python.exe tests/run_clean_install.py --clone
```

O modo `--clone` exige que a revisão da branch no remoto seja igual ao `HEAD`
local e verifica ao final que os arquivos rastreados do clone não foram alterados.

O roteiro cria `artifacts/clean-install_<id>/` com `source/`, `manifest.json`,
`report.json`, logs por etapa e capturas. Usa um ambiente novo e mantém seus
artefatos para revisão. Chrome e Node habilitam também os testes de navegador;
se não estiverem disponíveis, essa ausência fica registrada. A suíte de testes
roda com o Python recém-instalado.

Para repetir apenas a interface Qt:

```powershell
.\venv\Scripts\python.exe tests/run_desktop_smoke.py artifacts/desktop-smoke
```

As evidências são locais e ignoradas pelo Git. A revisão-base e os hashes do
snapshot ficam no relatório; qualquer mudança de fonte após a rodada exige
avaliar quais verificações precisam ser repetidas.
