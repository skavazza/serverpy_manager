# Instalação e verificação do ambiente

Os launchers usam o Python do `venv` e o mesmo preparador, `setup_env.py`.
O preparador verifica versões das quatro dependências diretas e importa os
módulos usados pelo app, incluindo qrcode, paramiko e módulos Qt da interface,
multimídia e carregamento de formulários.

Se houver uma dependência ausente ou incompatível, o início normal executa
`python -m pip install -r requirements.txt` com o Python desse ambiente. Depois
confere o ambiente em um processo novo. Falha de instalação ou de conferência
interrompe o launcher antes de abrir o app. Não há atualização automática do pip.

`requirements.txt` fixa as versões diretas observadas no ambiente Windows de
validação em 2026-10-24; `constraints.txt` fixa também a resolução das dependências
indiretas. Isso não é um lock de artefatos com hashes. Disponibilidade de wheels,
bibliotecas nativas do sistema ainda precisam de validação por combinação de
sistema e versão de Python. A instalação em venv novo passou no Windows 11
x64/Python 3.14.3; veja as [evidências e limites](windows-validation.md).

## Verificar sem instalar nem abrir o app

Com o ambiente virtual já criado:

```powershell
.\start.bat --check
```

```bash
./start.sh --check
```

Ou diretamente, com o Python do ambiente:

```powershell
.\venv\Scripts\python.exe setup_env.py --check
.\venv\Scripts\python.exe -m pip check
```

O primeiro comando verifica as dependências diretas e seus imports; `pip check`
confere os requisitos declarados pelos pacotes instalados. `--check` retorna
erro para ambiente incompleto, sem instalar dependências. Se o `venv` ainda
não existir, os launchers podem criá-lo antes de chegar a essa verificação.

## Ambiente incompatível ou danificado

Um ambiente existente não é removido automaticamente. Os launchers param e
orientam a preservar ou renomear a pasta quando não encontram o Python esperado.
Ambientes virtuais não devem ser copiados entre Windows e Linux. Para reconstruir,
preserve a pasta antiga, crie outro `venv` com Python 3.10 ou superior e execute
o launcher. As configurações e os arquivos compartilhados não são migrados.

Se os imports falharem mesmo após a instalação, revise a mensagem do preparador,
as bibliotecas nativas do sistema e a necessidade de recriar o ambiente. No
Windows, a abertura sem console exige `venv/Scripts/pythonw.exe`.

## Evidências e limites desta etapa

- Windows: verificação real pelos dois launchers (`start.bat` e `start.sh` via
  Git Bash), imports e `pip check`; testes de falha de instalação em diretórios
  temporários com espaços e preservação de ambiente incompatível.
- Testes Linux simulados: o autostart força o ramo Linux; os testes de ADB/scrcpy
  verificam o `chmod` solicitado e, quando executados em POSIX, também os bits
  de execução reais.
- Linux nativo: pendente. WSL não está instalado nesta máquina; executar Bash
  no Windows não valida dependências Qt, permissões reais ou dispositivos Linux.
- Instalação limpa das dependências no Windows: passou em venv novo sobre um
  snapshot dos fontes atuais, com wheels reutilizadas do cache do pip. Abertura
  Qt automatizada, fluxos HTTP e navegador também passaram. Isso não equivale
  a um clone limpo de revisão publicada nem ao aceite manual de hardware.
- Instalação Linux e validação física continuam pendentes. Esta etapa mantém
  a execução por código-fonte; bundles por SO ficam para uma entrega posterior,
  observando `LICENSE`.
