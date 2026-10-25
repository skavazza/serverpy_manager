# Um aplicativo, integrações por sistema operacional

## Decisão

Manter um único projeto, com interface, convites, cadastro HTTPS, perfis públicos
e regras compartilhados. Selecionar automaticamente as integrações nativas ao
executar. Distribuir pacotes específicos para cada sistema; não há um binário
único capaz de executar nativamente em Windows e Ubuntu.

`src/core/vpn_backend.py` define os contratos `IdentityStore` e `TunnelBackend`,
o erro comum e as fábricas `identity_store()` / `tunnel_backend()`. A interface
usa somente essas fábricas. Falha em uma implementação não troca silenciosamente
o sistema de proteção de chaves nem tenta executar a implementação de outro OS.
Windows mantém os caminhos e identidades existentes, sem migração de dados.

| Responsabilidade | Windows | Linux / alvo inicial Ubuntu 24.04+ |
|------------------|---------|------------------------------------|
| Identidade persistente | DPAPI do usuário | systemd-creds, chave host e arquivos privados de root |
| Túnel | Serviço oficial WireGuard | Interface WireGuard do kernel, wg e ip |
| Configuração privada ativa | Importação temporária com ACL → DPAPI SYSTEM | memfd anônimo selado, sem arquivo de configuração no disco |
| Privilégios nesta fase | Sessão elevada | root |
| Nome gerenciado | serverpy- + 16 caracteres hexadecimais | spwg- + 10 caracteres hexadecimais (limite de 15 caracteres Linux) |
| Diagnóstico | Arquivos/privilégios; status do serviço e handshake | Ferramentas/privilégios; interface UP e handshake |
| Distribuição prevista | Executável/instalador Windows | Pacote .deb Ubuntu |

Os perfis de cliente são independentes dos nomes nativos de interfaces. Não
contêm chaves privadas; cada máquina gera sua própria identidade. Não copiar
arquivos DPAPI/credenciais cifradas entre sistemas ou participantes.

## Implementação Linux

`src/core/vpn_linux.py` implementa os mesmos contratos de servidor, cliente,
encerramento e status. O código pode ser importado no Windows sem executar
ferramentas Linux; imports e operações nativas são adiados até a seleção do OS.
Outros sistemas, incluindo macOS, retornam requisito não suportado.

O alvo inicial de homologação é Ubuntu 24.04 LTS ou posterior com:

- `wireguard-tools` (wg), `iproute2` (ip) e suporte WireGuard no kernel;
- `systemd-creds` com suporte a credenciais cifradas por chave host (systemd 250+);
- `memfd_create`, selagem de memfd e `/proc/self/fd`;
- privilégios root nas operações de identidade e túnel.

Ubuntu 22.04 não está coberto por esse requisito de credenciais; não há fallback
para armazenar chaves privadas em texto puro. Outras distribuições Linux podem
ter ferramentas equivalentes, mas não estão homologadas nesta etapa.

As identidades cifradas ficam em `/var/lib/serverpy/vpn/identities`. O mecanismo
usa `systemd-creds --with-key=host`, com plaintext somente em stdin/stdout dos
processos, sem chaves em argumentos ou logs. O segredo host é protegido por root;
essa opção não promete proteção TPM ou contra acesso root/disco completo.
Diretórios privados exigem 0700 e arquivos 0600, ou permissões mais restritas.
Recusa symlinks, arquivos de outro proprietário e caminhos graváveis por grupo/outros.
Publicação de identidades é atômica e não sobrescreve chaves existentes.

Os executáveis são escolhidos em caminhos do sistema, com proprietário root,
permissões protegidas e ancestrais protegidos. O backend do túnel também
confere o hash de wg/ip antes de cada execução.
Confia-se na instalação de pacotes do sistema; não foi implementada verificação
de assinatura do pacote apt pelo app. Não usa PATH do usuário, shell ou elevação
automática. O ambiente dos comandos é limitado a PATH do sistema e locale C.

O túnel recebe configuração em um memfd selado, transmitido ao wg por descritor
herdado. Endereços e rotas usam argumentos estruturados do ip. Não configura
DNS, rota de internet, LAN remota, hooks ou encaminhamento entre participantes.
Verifica conflitos de faixas antes de criar o adaptador.

Marcadores de propriedade em `/run/serverpy-wireguard` contêm apenas a chave
pública. Antes de apagar uma interface, confere marcador privado, alias, tipo
WireGuard e chave pública efetiva. Usa bloqueio entre processos, com prazo de
5 segundos, e tenta remover interfaces criadas em ativação incompleta. A consulta
de status não lê `dump`, `showconf` ou chaves privadas.

Nesta primeira implementação, a interface gráfica ainda não possui helper
privilegiado Linux separado ou política polkit. O processo normal pode mostrar
o diagnóstico, mas não executar operações que exigem root. O helper e o pacote
.deb precisam ser definidos antes da entrega para uso cotidiano; não se deve
apresentar essa etapa como instalador Ubuntu pronto.

## Validação e distribuição

Testes realizados nesta máquina Windows: seleção das fábricas, recusa de
plataforma desconhecida, ausência de fallback, simulação de comandos/interfaces
Linux, configuração em memória, rollback, propriedade, permissões e credenciais.
Esses testes não executam kernel Linux, selagem real ou systemd-creds real.
O WSL foi consultado e não está instalado; não há validação Ubuntu local.

Resultado desta etapa: **382 testes aprovados em Windows**, código de saída zero,
em 87,4 s (`artifacts/vpn-platform-regression-repeat.log`), incluindo 17 novos
testes de seleção/Linux. A primeira rodada registrou `WinError 10053` no teste
HTTP existente de corpo acima do limite; os 12 testes de intents passaram na
repetição direcionada e a regressão completa posterior passou. O roteiro
Qt/HTTP também aprovou as 11 abas em 980×760 e 1440×900.

Faltam testes nativos de credenciais, permissões, memfd, criação/remoção, rotas,
handshake e tráfego entre Ubuntu ↔ Ubuntu e Windows ↔ Ubuntu. A homologação
Windows ↔ Windows com WireGuard real também continua pendente.

O empacotamento continuará separado: instalador Windows e .deb, provenientes
da mesma revisão, com dependências e verificações específicas. Nenhum pacote
ServerPy novo foi gerado nesta etapa.

Referências: [wg no Ubuntu](https://manpages.ubuntu.com/manpages/noble/man8/wg.8.html),
[credenciais systemd](https://www.freedesktop.org/software/systemd/man/latest/systemd-creds.html),
[integração Windows](wireguard-windows.md).
