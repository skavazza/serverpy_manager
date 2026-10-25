# Túneis WireGuard no Windows

## Estado da entrega

A integração de servidor/cliente, importação protegida de configurações,
início/remoção de serviço e consulta de handshake está implementada em
`src/core/wireguard_windows.py`. A ativação com driver real e a conexão entre
duas máquinas **ainda não foram homologadas**. Nesta máquina, o WireGuard não
está instalado e o processo não é administrador; nenhum adaptador ou rota foi
criado durante o desenvolvimento.

Os testes do ciclo do serviço usam uma simulação. Testes de HTTPS entre painéis
e proteção DPAPI do usuário são reais, mas não equivalem a um túnel WireGuard.

## Pré-requisitos

- Instalar o [WireGuard oficial para Windows](https://www.wireguard.com/install/)
  nas duas máquinas. Ao detectar que ele falta, a tela VPN oferece baixar o MSI
  oficial fixado e verificado por SHA-256 e Authenticode; após confirmação, o
  instalador é iniciado com a aprovação UAC do Windows. Conclua a instalação e
  atualize o status. A integração usa a instalação padrão em Program Files;
  não executa cópias encontradas no PATH. No Linux, instale os pré-requisitos
  pelos pacotes da distribuição.
- Abrir o ServerPy como administrador para criar/encerrar serviços e adaptar
  a rede. A aprovação UAC do instalador WireGuard não eleva o ServerPy; não há
  elevação automática do próprio app.
- Para internet, o endpoint UDP anunciado precisa alcançar o servidor. CGNAT
  pode exigir o intermediário ainda previsto no roadmap.

Foi preparado localmente o instalador `artifacts/wireguard/wireguard-amd64-1.1.1.msi`,
baixado do domínio oficial. Authenticode retornou assinatura válida e publicador
`WireGuard LLC`. SHA-256:
`7bfed60ad61b785c914b38b61555a975488e1d3ec472dbfb2fcdf498fca75242`.
O instalador não foi executado e é um artefato local ignorado pelo Git.

## Fluxo na interface

O painel separa os dois objetivos em abas: **Criar uma rede**, para quem
administra o servidor e aprova participantes, e **Conectar a uma rede**, para
quem solicita acesso e inicia o cliente. A instalação/status do WireGuard e a
orientação do próximo passo ficam visíveis nos dois modos.

1. Na aba **Criar uma rede**, prepare a rede VPN e inicie o **cadastro HTTPS**.
   Selecione o certificado TLS e a chave privada correspondentes.
2. Gere um **convite remoto** e envie-o ao outro computador por um canal
   confiável.
3. No outro computador, abra **Conectar a uma rede**, use
   **Enviar pedido de cadastro** e cole o convite. Volte à aba de criação,
   atualize o status e aprove o dispositivo na tabela.
4. Inicie o **servidor WireGuard** (porta UDP padrão 51820). Se ele já estava
   ativo antes da aprovação, aproveitar a mudança encerra o túnel; inicie-o
   novamente para aplicar a lista autorizada.
5. Selecione o dispositivo aprovado no servidor e **Exporte conexão do cliente**.
   Informar o nome/IP alcançável do servidor e a mesma porta UDP.
6. Envie esse JSON público pelo mesmo canal confiável do convite. Ele contém
   faixa, IP atribuído e chaves públicas, sem chave privada. O cadastro HTTPS
   e o WireGuard usam portas e protocolos separados.
7. No participante já cadastrado, na aba **Conectar a uma rede**, escolha
   **Conectar cliente WireGuard** e
   colar o perfil. O app exige que a chave pública de cliente do perfil
   corresponda à identidade `client` DPAPI criada no cadastro local.
8. Use **Atualizar status da VPN**. Serviço ativo não significa conexão:
   o app só indica handshake confirmado se o WireGuard reportar um handshake
   com timestamp de até 180 segundos. No servidor, isso confirma pelo menos
   um peer, não necessariamente todos. O cliente usa keepalive de 25 segundos.
8. Usar **Desconectar WireGuard** para remover o serviço gerenciado. O
   encerramento normal do app também tenta parar o túnel desta sessão.

O servidor usa o primeiro host da faixa; os clientes recebem IPs exclusivos.
O cliente publica seu endereço como `/32` e encaminha somente o IP virtual do
servidor. O servidor mantém `/32` por participante. Não configura DNS, saída de
internet, acesso à LAN remota, encaminhamento entre clientes ou hooks de shell.
Antes de iniciar, consulta as rotas Windows e rejeita sobreposição da faixa,
excluindo o próprio adaptador gerenciado ao reiniciar.

Para acessar o HTTP do ServerPy pelo IP virtual, seu bind e as regras locais
de firewall precisam permitir essa interface/porta. A autenticação e as
permissões de arquivos continuam obrigatórias conforme configuradas no app.

## Proteção da configuração e ciclo de vida

O app confere Authenticode dos dois executáveis, exige publicador `WireGuard LLC`
e verifica seu hash novamente antes de cada execução. Não passa chaves privadas
em argumentos, logs ou saídas de diagnóstico. A consulta de handshake usa apenas
`wg show <nome> latest-handshakes`; não usa `dump` ou `showconf`.

O gerenciador oficial recebe um `.conf` transitório na pasta
`Program Files/WireGuard/Data/Configurations`. O arquivo já nasce com ACL
restrita a SYSTEM e Administradores, é publicado por rename após a escrita
completa e o WireGuard o converte em `.conf.dpapi` no contexto SYSTEM, removendo
o original. Isso resolve a diferença entre DPAPI do usuário e DPAPI do serviço.
O app só instala o túnel após observar o arquivo protegido e a remoção do
plaintext. Falha/timeout remove o staging/plaintext na finalização normal.
Esse fluxo usa texto puro **temporário sob ACL**, diferente do armazenamento
da identidade do usuário, que grava apenas conteúdo cifrado.

O app inicia o gerenciador oficial se necessário; ele pode exibir o ícone/UI
do WireGuard. Não encerra esse gerenciador compartilhado. Os túneis usam nomes
`serverpy-<hash>` e o app exige o caminho exato do executável e da configuração
antes de parar um serviço existente. Não aceita configurações arbitrárias de
terceiros, hooks ou nomes de serviços fora desse namespace.

Após instalar, o túnel é configurado para início manual. Em falha de ativação,
o app tenta remover o serviço parcial. Aprovar, rejeitar ou revogar um dispositivo
com túnel servidor ativo primeiro para o túnel inteiro; só depois altera a
autorização. O administrador precisa reiniciar o servidor para aplicar a lista
atualizada. Se a parada falhar, a autorização não é alterada.

O perfil de conexão do cliente é importado manualmente e não é persistido;
reconexão automática e retomada após reinício ainda estão pendentes. O arquivo
protegido do gerenciador pode permanecer após desconectar. Interrupção forçada
ou falha de limpeza pode deixar serviço/importação pendente, inclusive antes
de o início manual ser aplicado: conferir no WireGuard oficial e encerrar o
túnel `serverpy-...` antes de repetir. O app recusa importação com plaintext
pendente, sem sobrescrevê-lo. Este ciclo de recuperação exige homologação real.

## Evidências e pendências

- Vinte testes direcionados de runtime/painel aprovados, incluindo rollback,
  assinatura/publicador inválidos, binário alterado, recusa de serviço alheio,
  limpeza de importação, rotas conflitantes e revogação que encerra o túnel.
- Regressão completa: **365 testes aprovados**, código de saída zero, em
  84,8 s (`artifacts/wireguard-regression.log`). Isso não comprova driver ou
  serviço reais: os testes de ciclo de serviço continuam simulados.
- Consulta real das rotas locais e API de criação de arquivo com ACL conferidas
  em Windows. Não foi criado arquivo de configuração de serviço real.
- As 11 abas renderizadas em 980×760 e 1440×900; roteiro HTTP de arquivos passou.
- Pendentes: instalação em ambiente elevado, migração DPAPI SYSTEM pelo
  WireGuard real, criação/remoção de adaptadores, handshake, tráfego HTTP na
  VPN, firewall, suspensão, mudança de rede, reinício e recuperação em duas
  máquinas Windows. Suporte equivalente Linux e pacote executável não validados.

Referências: [serviços e importação oficial](https://git.zx2c4.com/wireguard-windows/about/docs/enterprise.md),
[armazenamento DPAPI oficial](https://git.zx2c4.com/wireguard-windows/tree/conf/dpapi/dpapi_windows.go).
