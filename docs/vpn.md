# VPN integrada e túneis entre instâncias

Atualizado em 2026-10-24. **Estado: base técnica em desenvolvimento.**
O cadastro HTTPS e a integração de túneis Windows estão implementados.
A ativação real do WireGuard e a conexão entre duas máquinas ainda precisam
de homologação. Veja o [fluxo e os pré-requisitos Windows](wireguard-windows.md).
O app agora seleciona automaticamente a integração Windows/Linux por contratos
comuns. A implementação Ubuntu e os limites da validação estão no
[guia por plataforma](vpn-platforms.md); nenhum túnel Linux real foi validado.

## Objetivo e escopo

Conectar computadores com ServerPy instalado por uma rede virtual privada.
O uso principal é VPN entre máquinas; o acesso aos arquivos e serviços do
ServerPy pela mesma conexão faz parte do escopo. Um computador cria a rede,
atua como servidor e gera convites individuais para os participantes.

A base técnica proposta é WireGuard, com gerenciamento pelo ServerPy.
A integração, instalação dos componentes, compatibilidade e licenças de
redistribuição precisam ser verificadas antes de fixar o pacote distribuído.
Não desenvolver criptografia ou protocolo VPN próprios.

## Implementação e evidências

`src/core/vpn.py` oferece geração X25519 em memória, validação de chaves e
endpoints, planejamento de endereços IPv4 privados e diagnóstico sem alterações
de rede. A alocação reserva o primeiro host ao servidor, atribui `/32` a cada
participante e rejeita duplicidade, esgotamento e sobreposição com as redes
fornecidas pelo chamador. A descoberta automática de rotas locais ainda não
está implementada; o planejador não garante ausência de conflitos sem essa entrada.

`src/core/vpn_identity.py` persiste identidades com DPAPI no escopo do usuário
Windows, em `%LOCALAPPDATA%/ServerPy/HTTPManager/vpn/identities`. Somente o
conteúdo cifrado chega ao disco. A publicação é atômica, sem substituição de
identidades existentes, inclusive em criação concorrente. Corrupção, troca de
nome e divergência entre chaves são rejeitadas, sem rotação silenciosa.
Esse armazenamento não é um arquivo de serviço `.conf.dpapi` do WireGuard.
Código rodando como o mesmo usuário e administradores permanecem no limite
de confiança. O Linux tem implementação própria de credenciais systemd,
descrita no [guia por plataforma](vpn-platforms.md), ainda sem homologação nativa.

`src/core/vpn_service.py` monta configurações do servidor somente em memória,
com rotas `/32` por participante e sem hooks, DNS ou rota de saída de internet.
Também prepara argumentos de instalação/remoção restritos a nomes
`serverpy-<identificador hexadecimal>` e caminhos `.conf.dpapi`.
`src/core/wireguard_windows.py` agora executa o ciclo do serviço com binários
oficiais verificados, importação transitória sob ACL e conversão DPAPI SYSTEM
pelo gerenciador oficial. O início requer Windows, instalação oficial e app
elevado; não há elevação automática. O ciclo foi testado com serviço simulado,
sem criar adaptadores nesta máquina. Veja o [guia Windows](wireguard-windows.md).

### Interface de preparação

A aba principal **VPN e túneis** e o menu Navegar agora oferecem acesso à
preparação local em português e inglês. É possível consultar os pré-requisitos,
preparar uma rede, gerar tokens locais de 15 minutos e aprovar, rejeitar ou
revogar dispositivos já cadastrados no banco local. Os estados são locais:
os botões de cadastro não instalam WireGuard nem alteram a rede.
A entrada de pedidos remotos está disponível por HTTPS; a conexão VPN entre
computadores está integrada aos controles WireGuard, mas ainda não homologada
com driver real. Servidor e cliente não encaminham internet ou LAN remota.

Os arquivos ficam na pasta VPN por usuário. `network.json` registra a faixa,
a identidade do servidor permanece cifrada por DPAPI e `registry.sqlite`
guarda dispositivos e verificadores de convites. A rede existente é reaberta,
sem substituir sua identidade; metadados são publicados atomicamente e falhas
não geram uma nova identidade automaticamente. A abertura da aba sem rede
configurada só consulta o diagnóstico. Operações de disco e diagnóstico são
executadas em segundo plano para preservar a resposta da interface.

Validação da interface: 56 testes direcionados (VPN, persistência, cadastro,
painel e idioma) aprovados; roteiro Qt/HTTP aprovado nas 11 abas em 980×760 e
1440×900. Prévia local em `artifacts/vpn-desktop/980-vpn-and-tunnels.png`.
A regressão completa posterior passou com 335 testes em 70,7 s e código de
saída zero; registro local em `artifacts/vpn-ui-regression.log`.

### Convite portátil e cliente HTTPS

`src/core/vpn_enrollment.py` define o JSON versionado `serverpy-vpn-invite`,
com host/porta do cadastro, chave pública WireGuard do servidor, certificado
TLS PEM, impressão digital SHA-256, token e validade. Não contém chave privada.
O convite deve ser recebido por canal confiável: substituir o convite inteiro
também substitui sua identidade de confiança. Campos extras/duplicados, versões
desconhecidas, validade inválida e mensagens acima de 16 KiB são rejeitados.
O formato inicial destina-se ao certificado autoassinado do próprio servidor,
com nome/IP compatível; a emissão e a proteção da chave TLS ainda não estão
integradas ao aplicativo. Host/porta correspondem ao cadastro HTTPS, não à
porta UDP do WireGuard.

O cliente `request_remote_admission` valida cadeia TLS e nome do servidor com
`CERT_REQUIRED`, TLS mínimo 1.2, e exige a impressão digital exata do certificado
antes de enviar o token. Não há fallback HTTP, proxies ou redirecionamentos.
Só aceita resposta JSON limitada a 4 KiB, estado `pending`, ID válido e a chave
pública do servidor indicada no convite. O timeout é de inatividade por operação,
com padrão de 5 s; não representa prazo total para a operação inteira.

A aba VPN oferece **Conferir convite remoto**, que apenas valida o JSON e mostra
destino e impressão digital. Não grava o token nem faz requisições. A ação
**Enviar pedido de cadastro** importa o convite e envia explicitamente um pedido
HTTPS com a identidade `client` protegida por DPAPI. O pedido fica pendente no
servidor; o administrador usa **Atualizar status da VPN** e aprova localmente.
A consulta automática do estado pelo cliente e a persistência do ID do pedido
ainda não estão implementadas. Se o servidor cadastrar o pedido e a resposta
se perder, o token permanece consumido: conferir a lista local antes de emitir
outro convite, sem repetir automaticamente o cadastro.

### Servidor HTTPS de cadastro

`src/core/vpn_admission_server.py` implementa um listener separado do servidor
HTTP de arquivos. A aba permite iniciar/parar, gerar o convite JSON completo e
encaminhar pedidos do cliente. Não há inicialização automática, instalação de
serviço, abertura automática de firewall ou alteração de roteador.

Para usar o cadastro entre máquinas:

1. Preparar a rede local no computador servidor.
2. Selecionar **Iniciar cadastro HTTPS**, informar o certificado público PEM e
   a chave privada TLS existente em arquivos separados, o IPv4 de escuta e a
   porta TCP (padrão 8444). O padrão de endereço é `127.0.0.1`, acessível somente
   na própria máquina; escolher um endereço de interface alcançável para LAN.
3. O certificado deve corresponder ao nome/IP que será anunciado e estar válido.
   Nesta etapa são importados arquivos existentes, sem emissão, renovação ou
   armazenamento DPAPI da chave TLS pelo app. A chave precisa estar protegida
   pelas permissões do sistema; arquivos de chave cifrados com senha ainda não
   têm entrada de senha na interface. Não compartilhar a chave privada.
4. Gerar o convite remoto com o nome/IP do servidor e enviar o JSON por um canal
   confiável. Porta e certificado correspondem ao listener HTTPS, não ao WireGuard.
5. Na outra instância, escolher **Enviar pedido de cadastro**, colar o JSON e
   informar o nome do dispositivo. A identidade de cliente é criada/reutilizada
   localmente com DPAPI, sem salvar o token.
6. Atualizar a lista do servidor e aprovar ou rejeitar o pedido. **Isso registra
   a autorização, mas ainda não estabelece uma VPN.** Encerrar o cadastro fecha
   o listener; os convites existentes deixam de funcionar enquanto estiver parado.

Limites do listener: quatro conexões simultâneas; handshake dentro do worker
limitado; inatividade de socket de 3 s e prazo de conexão de 5 s; cabeçalhos de
até 8 KiB e corpo JSON de até 2 KiB. Rejeita framing ambíguo, transfer encoding,
campos extras e JSON duplicado. A resposta nunca inclui o token, detalhes de
exceção ou comandos; logs de requisição ficam desativados. Apenas
`POST /vpn/v1/requests` cadastra pedidos; não há aprovação remota.

Há limite de dez requisições HTTP por IP/minuto e sessenta globais/minuto,
com histórico limitado a 256 IPs e janela monotônica. Os contadores são locais,
voláteis, reiniciam ao encerrar o listener e não constituem bloqueio persistente
de força bruta. Conexões em excesso são fechadas; rate limit retorna 429.
Rotinas SQLite podem terminar depois do prazo do socket; o prazo limita a rede,
não cancela uma transação já iniciada. Homologação em redes independentes e
endurecimento antes da exposição pública ainda estão pendentes.

O teste de interface usa dois painéis com identidades/pastas separadas: inicia
o listener real em loopback, gera/importa convite, envia pedido por TLS, aprova
localmente e encerra a porta. Oito testes do listener cobrem replay, limites,
erros genéricos, framing inválido, rate limit e handshake ocioso sem bloquear
o accept. Nenhum adaptador ou túnel foi criado.
Regressão desta entrega: **351 testes aprovados em Windows**, em 86,5 s,
com código de saída zero (`artifacts/vpn-admission-regression.log`). O roteiro
Qt/HTTP também passou nas 11 abas em 980×760 e 1440×900; imagens em
`artifacts/vpn-admission-desktop/`. Esses resultados são locais, sem comprovar
cadastro pela internet ou conectividade WireGuard entre máquinas físicas.

O cadastro declara a chave pública WireGuard; TLS autentica o servidor, mas
não comprova que o solicitante possui a chave privada WireGuard. Essa prova
permanece pendente para integração com o handshake do túnel. Cadastro pendente,
aprovação e conectividade são estados distintos.

Seis testes do transporte cobrem HTTPS real, replay, certificado/nome inválidos,
pin divergente antes do POST, formato estrito e resposta com identidade divergente.
Um teste adicional da interface verifica rejeição de convite sem rede ou escrita.
Nesta rodada, os 63 testes direcionados de VPN/interface/idioma passaram,
assim como o roteiro Qt/HTTP nas 11 abas em 980×760 e 1440×900.
A suíte completa de 335 casos citada acima é o resultado da etapa anterior.

### Persistência do cadastro local

`src/core/vpn_registry.py` implementa o cadastro local em SQLite, associado à
faixa e à chave pública do servidor. Convites usam tokens aleatórios de 256 bits;
somente o SHA-256 é persistido. A validade permitida é de 60 segundos a 24 horas,
com padrão de 15 minutos e limite de 100 convites ativos. O token é retornado
uma vez, fica omitido do `repr` e não é enviado automaticamente.

O consumo do convite cria um pedido pendente. Transações SQLite `BEGIN IMMEDIATE`
impedem consumo concorrente e duplicidade na alocação de IPs. Aprovar, rejeitar
e revogar são operações administrativas locais; chaves rejeitadas/revogadas
não podem se recadastrar. IPs revogados permanecem reservados para evitar
reutilização enquanto a remoção de peers ainda não está integrada. Há limite
de 4096 registros de dispositivos, incluindo histórico; limpeza e desbloqueio
administrativo ainda não estão disponíveis. Expiração é verificada com o relógio
do sistema, que precisa estar correto.

Nesta fase, o cadastro recebe somente a chave pública declarada: ainda não
verifica posse da chave privada. O formato portátil e o cliente TLS estão
implementados acima, incluindo listener e limites de tentativas. Métodos de
aprovação/rejeição/revogação devem ser chamados apenas por administração local
confiável e não são expostos no listener. Revogar remove a autorização no cadastro, mas ainda não remove
um peer individualmente. Na interface, alterações de autorização encerram antes
o túnel servidor gerenciado inteiro; a lista atualizada vale no próximo início.
Não há chaves privadas no banco; os metadados e verificadores
dependem das permissões de acesso à pasta escolhida pelo futuro controlador.

Validação desta etapa: 30 testes direcionados de VPN aprovados no Windows,
incluindo dez novos testes de expiração, replay, concorrência, rejeição,
revogação após reinício e rollback quando a rede está cheia. O teste anterior
de 321 casos é histórico; a suíte completa não foi repetida nesta etapa isolada.

Diagnóstico disponível a partir da raiz do repositório:

```powershell
.\venv\Scripts\python.exe -m src.core.vpn
```

Resultado local em 2026-10-24: Windows sem `wireguard.exe`/`wg.exe` encontrados
e processo sem elevação administrativa. Nenhuma instalação, serviço, rota ou
regra de firewall foi alterada. Encontrar um executável não atesta assinatura,
versão ou conexão funcional. Oito testes direcionados passaram, incluindo
acordo de chaves, rejeição de entradas inválidas e alocação de peers.
A regressão completa executada após essa implementação passou: 309 testes
em Windows, em 72 s. Isso valida o código atual, não um túnel WireGuard real.

A integração Windows usará o serviço por túnel documentado pelo fabricante,
separado do serviço de gerenciamento da interface oficial. Configurações
protegidas `.conf.dpapi` são suportadas pelo WireGuard; ainda precisamos
implementar e validar proteção, ACLs, contexto de usuário/serviço e recuperação
antes de gravar configurações do serviço. Não gerar configurações permanentes em texto puro.
O helper privilegiado deverá aceitar somente operações e túneis gerenciados,
sem comandos arbitrários ou hooks `PreUp`/`PostUp` fornecidos por convites.
Instalação dos binários exige assinatura e versão verificadas; descoberta no
PATH serve apenas ao diagnóstico, não autoriza execução privilegiada.

## Fluxo de uso

1. O administrador abre a aba **VPN e túneis** e escolhe **Criar rede**.
2. Define nome, endpoint público e faixa virtual sem conflito com redes locais.
3. O app gera a identidade local e configura a interface VPN mediante as
   permissões do sistema, apresentando erros e instruções de recuperação.
4. O administrador gera um convite individual, temporário e de uso único,
   para enviar por um canal de sua escolha. O app não envia mensagens sozinho.
5. O participante importa o convite em **Entrar em uma rede**. Seu computador
   gera as próprias chaves e solicita autorização ao servidor.
6. O administrador confere a identidade da solicitação e aprova o dispositivo.
   O participante recebe um IP virtual exclusivo e as rotas autorizadas.
7. As duas interfaces mostram conexão, IP, último contato e diagnóstico.
   Desconectar, reconectar e revogar são ações explícitas.

O convite não contém a chave privada do servidor. Cada dispositivo possui
identidade própria; remover um participante não deve exigir trocar as chaves
dos demais. O mecanismo de registro por convite é uma camada do ServerPy,
pois WireGuard não oferece esse fluxo de cadastro por si só.

## Arquitetura e segurança

- Separar o plano de registro/autorização do transporte WireGuard.
- Proteger o registro com TLS e autenticação do servidor vinculada ao convite;
  definir a distribuição da confiança sem desativar validações de certificado.
- Gerar tokens com fonte criptográfica, armazenar somente seu verificador,
  aplicar expiração, consumo atômico, limites de tentativas e revogação.
  Rejeitar reutilização e pedidos concorrentes com o mesmo convite.
- Nunca colocar chaves privadas ou tokens em logs, URLs de diagnóstico,
  arquivos versionados ou relatórios. Proteger o armazenamento local usando
  os mecanismos do sistema; definir e testar esse mecanismo na primeira fase.
- Reservar IPs sem duplicidade e associar cada chave somente aos endereços e
  rotas autorizados. Autorização da VPN não concede administração HTTP.
- Manter autenticação e permissões atuais do ServerPy, mesmo dentro da VPN.
- Isolar operações privilegiadas de interface, serviço, rotas e firewall;
  reverter alterações incompletas e remover apenas recursos gerenciados pelo app.
- Revogação remove o peer ativo e impede novas conexões com sua credencial.
  Reconexão e reinício não podem reativar um dispositivo revogado.

## Conectividade e modos

| Modo | Escopo e padrão |
|------|-----------------|
| Entre participantes | Primeira entrega: comunicação com o servidor e, quando explicitamente autorizada, entre peers. |
| Serviços do ServerPy | HTTP/arquivos acessíveis pelo IP virtual, respeitando bind, firewall e permissões existentes. |
| Rede local remota | Etapa posterior: rotas de sub-rede, encaminhamento e regras explícitas; desativada por padrão. |
| Toda a internet pelo servidor | Etapa posterior e opcional: exige configuração de saída, DNS e testes de vazamento; desativada por padrão. |
| Túneis de portas | Etapa posterior: publicar portas TCP selecionadas com autorização individual e vínculo local por padrão. |

Uma VPN roteada não garante descoberta automática por broadcast, presença na
mesma rede Ethernet ou redirecionamento de USB. A primeira entrega usa IPs e
serviços explicitamente acessíveis.

Para conexão direta pela internet, o servidor precisa de endpoint alcançável:
IP público ou DNS/DDNS, porta UDP e regras adequadas no roteador/firewall.
Dois apps abertos e um convite não eliminam CGNAT. Sem caminho direto, será
necessário um nó público intermediário. A topologia desse nó e o limite de
confiança são decisões pendentes: um hub WireGuard comum termina os túneis;
não descrevê-lo como retransmissor sem acesso ao conteúdo. Definir se haverá
túnel interno entre os participantes para preservar criptografia ponta a ponta.
Não presumir VPS contratada, configurar produção ou publicar serviços nesta etapa.

## Entregas e critérios de aceite

1. **VPN-001 — Prova técnica Windows:** conectar duas máquinas usando WireGuard,
   confirmar instalação/serviço/permissões, armazenamento de chaves, rotas,
   firewall e limpeza. Registrar versões, dependências, licenças e arquitetura.
2. **VPN-002 — Cadastro e convites:** implementar registro autenticado,
   aprovação, expiração, uso único, persistência e revogação. Testar fraude de
   identidade, replay, concorrência, força bruta e ausência de segredos nos logs.
3. **VPN-003 — Interface e ciclo de conexão:** criar/entrar, gerar/importar convite,
   aprovar/remover dispositivos, mostrar IP/estado e configurar reconexão.
   Interface em português/inglês, acessível e sem bloquear durante operações.
4. **VPN-004 — Integração e homologação:** testar em dois Windows reais, LAN e
   internet com endpoint alcançável; acesso HTTP/arquivos pela VPN, peer
   revogado, reinício, suspensão, mudança de rede, conflito de faixa e falhas
   de elevação. Confirmar preservação de rotas, DNS e firewall anteriores.
5. **VPN-005 — Redes restritivas:** definir e validar intermediário para CGNAT,
   autenticação, modelo de confiança, disponibilidade e tráfego; testar em
   redes independentes. Sem essa entrega, documentar o requisito de endpoint público.
6. **VPN-006 — Ampliações:** acesso autorizado à LAN remota, saída de internet
   opcional e túneis TCP selecionados; aceitar cada modo com testes próprios.
7. **VPN-007 — Distribuição:** empacotar componentes e instruções no executável,
   testar Windows sem Python, instalação/atualização/desinstalação e recuperação
   após falha, preservando identidades e configurações existentes. Validar
   Linux separadamente antes de anunciar suporte equivalente.

Ordem: VPN-001 → VPN-002 → VPN-003 → VPN-004 → VPN-005 → VPN-006.
VPN-007 acompanha a escolha das dependências desde VPN-001; a validação final
do executável com VPN depende dos modos que forem incluídos na distribuição.
As validações anteriores do aplicativo não comprovam o funcionamento desta VPN.

## Referências técnicas

Na segunda etapa, 20 testes direcionados passaram no Windows, incluindo
DPAPI real, corrupção, concorrência, publicação interrompida e configurações
de serviço sem comandos arbitrários. A suíte completa terminou com `OK`:
321 testes em 73,6 s. O redirecionamento de stderr no PowerShell retornou
`NativeCommandError` apesar do resultado aprovado do unittest; o registro
local está em `artifacts/vpn-regression.log`. Permanecem avisos de limpeza
de objetos HTTPError nos testes HTTP existentes. Nenhum túnel foi ativado.

- [WireGuard: interfaces, chaves e rotas](https://www.wireguard.com/)
- [WireGuard para Windows](https://git.zx2c4.com/wireguard-windows/about/)
- [Serviços Windows e configurações protegidas](https://git.zx2c4.com/wireguard-windows/about/docs/enterprise.md)
- [Microsoft: proteção DPAPI por usuário](https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata)
- [Conexão direta e retransmissão em redes restritivas](https://tailscale.com/docs/reference/connection-types)
- [OpenSSH: encaminhamento de portas](https://man.openbsd.org/ssh)
