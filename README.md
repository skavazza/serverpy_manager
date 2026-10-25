# ServerPy HTTP Manager

Aplicativo desktop Python/PySide6 para iniciar um servidor HTTP e gerenciar
arquivos, dispositivos e serviços locais pela interface gráfica.

## Funcionalidades

- **Servidor HTTP e arquivos:** navegação, compartilhamento de pastas
  adicionais, permissões, operações de arquivo, links temporários, autenticação,
  restrições de IP e TLS.
- **Rede:** diagnóstico de DNS/TCP/HTTP(S), QR Code para acesso pelo celular,
  atividade HTTP e suporte a Cloudflare Tunnel.
- **Transferências:** uploads e downloads com progresso, cancelamento e
  proteção de arquivos existentes durante operações incompletas.
- **Android:** ADB por USB para navegar e transferir arquivos; scrcpy para
  espelhamento e controle, com opções de vídeo/áudio, gravação e captura.
- **SSH/SFTP:** conexão por chave ou senha, terminal remoto, comandos e
  transferência de arquivos.
- **Dispositivos locais:** câmeras, scanners, impressoras, unidades USB e
  consulta de portas com FindPort.
- **Interface:** português e inglês, menus e barra superior com ícones de
  ações rápidas, dicas traduzidas e atalhos de teclado.

Documentação por recurso:
[Android](docs/android.md) · [SSH/SFTP](docs/ssh.md) ·
[transferências](docs/transfers.md) · [FindPort](docs/findport.md) ·
[câmera](docs/camera.md) · [digitalização](docs/scanning.md) ·
[impressão](docs/printing.md) · [Cloudflare Tunnel](docs/cloudflare-tunnel.md) ·
[comandos remotos](docs/system-intents.md) ·
[limites HTTP](docs/http-limits.md) ·
[validação Windows](docs/windows-validation.md) ·
[estado do projeto e melhorias](docs/project-status.md).

## Clone privado para colaboradores autorizados

O repositório `skavazza/serverpy_manager` é privado. O acesso é limitado a
colaboradores autorizados; estas instruções não anunciam uma publicação pública
nem alteram os termos de [`LICENSE`](LICENSE).

```bash
git clone https://github.com/skavazza/serverpy_manager.git
cd serverpy_manager
```

No Linux, crie o ambiente e inicie o aplicativo:

```bash
python3 -m venv venv
./venv/bin/python -m pip install -r requirements.txt
./start.sh
```

No Windows, use:

```powershell
py -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
.\start.bat
```

O FindPort incluído para clones limpos fica em `vendor/findport/`; o checkout
aninhado `findport/` é apenas uma alternativa para desenvolvimento no workspace.
O scrcpy é obtido como executável externo oficial ou binário do sistema.
Consulte [Third-Party Notices](THIRD_PARTY_NOTICES.md) para detalhes de
proveniência e limites da cópia privada.

## Requisitos

- Python 3.10 ou superior.
- Dependências listadas em [requirements.txt](requirements.txt).

## Instalação e execução

No Linux:

```bash
./start.sh
```

No Windows, execute `start.bat`. Os scripts criam o ambiente virtual quando
necessário, verificam as dependências fixadas e interrompem a abertura se a
instalação falhar. Ambientes existentes incompatíveis são preservados.
Use `start.bat --check` ou `./start.sh --check` para conferir um ambiente já
criado sem instalar nem abrir a interface. Veja [instalação e limites de
validação](docs/installation.md). Também é possível
instalar manualmente:

```bash
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
./venv/bin/python src/main.py
```

## Testes

Execute a suíte completa com:

```bash
QT_QPA_PLATFORM=offscreen ./venv/bin/python -m unittest discover -s tests -v
```

No Windows, execute `.\venv\Scripts\python.exe -m unittest discover -s tests -v`.
Os testes e verificações de integração variam conforme a plataforma e os
recursos disponíveis.

## Planejamento e próximos passos

O [roadmap](ROADMAP.md) registra as melhorias de segurança, HTTP, instalação e
Android. A validação com dispositivos reais no Windows e a regressão nativa
Linux das mudanças atuais continuam pendentes; Android por Wi-Fi fica no backlog.

O novo escopo de [VPN integrada e túneis](docs/vpn.md) está documentado, com
base técnica em desenvolvimento: rede entre instâncias, convites individuais gerados pelo
servidor e acesso aos serviços do ServerPy pelo IP virtual. O roadmap detalha
as etapas `VPN-001` a `VPN-007`, incluindo homologação antes do executável com VPN.
O diagnóstico inicial pode ser executado com `python -m src.core.vpn` no
ambiente virtual; esse diagnóstico não instala componentes nem altera a rede.
Na aba **VPN e túneis**, já é possível preparar a rede local, gerar tokens de
cadastro local e gerenciar autorizações. Esses tokens ainda não conectam outro
computador; o cadastro remoto usa o convite HTTPS completo descrito abaixo.
**Conferir convite remoto** valida o formato portátil sem enviar solicitações.
O cadastro HTTPS já permite iniciar/parar o listener com certificado/chave
existentes, gerar convites completos e enviar pedidos entre instâncias para
aprovação local. Foi testado em loopback com dois painéis.
Os controles de túnel WireGuard Windows já foram integrados e exigem instalação
oficial e app como administrador. A ativação real ainda não foi homologada;
veja [pré-requisitos, fluxo e limitações](docs/wireguard-windows.md).

A [arquitetura por plataforma](docs/vpn-platforms.md) mantém um único app que
seleciona automaticamente Windows ou Linux. O backend Linux foi implementado
com testes simulados; Ubuntu 24.04+, credenciais systemd, privilégios e túneis
reais ainda precisam de homologação. Instalador Windows e pacote .deb serão
distribuições separadas da mesma base de código.
