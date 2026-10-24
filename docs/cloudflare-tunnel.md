# Cloudflare Tunnel

O aplicativo aceita tráfego encaminhado por um `cloudflared` executado na
mesma máquina. A configuração de DNS e do túnel é feita no Cloudflare; o app
não cria nem administra o túnel.

## Configuração

1. Configure o hostname público no seu Cloudflare Tunnel e aponte o serviço
   para o servidor local, por exemplo `http://127.0.0.1:8080`.
2. No app, abra a aba **Servidor**, marque **Cloudflare Tunnel (local
   cloudflared)** e informe o hostname público, como `files.example.com`.
3. Se **Verificar cabeçalho HTTP Host** estiver ativado, o hostname informado
   será aceito junto aos endereços locais do servidor.
4. Inicie o servidor. Use autenticação e, se necessário, a lista de IPs
   permitidos para restringir o acesso.

O app só considera `CF-Connecting-IP` quando a conexão TCP de origem é loopback
(`127.0.0.1` ou `::1`). O cabeçalho não é aceito de conexões remotas; se o
`cloudflared` encaminhar ao IP da rede local em vez de loopback, a origem será
tratada como o próprio proxy. Configure a origem do túnel com `localhost` ou
`127.0.0.1` para preservar o endereço do visitante.

Quando reconhecido, o IP do visitante é usado na lista de IPs permitidos, no
limite de requisições, na atividade HTTP e nos registros de transferências e
links temporários. Endereços IPv4 e IPv6 podem ser usados na lista de IPs.
Para requisições sem um `CF-Connecting-IP` válido, o app usa o IP da conexão.

O Cloudflare Tunnel não substitui a autenticação do app. Considere também
proteger o hostname com Cloudflare Access e usar senhas fortes. Cabeçalhos de
proxy enviados por uma conexão que não seja local não são usados para conceder
acesso nem para atribuir o IP do cliente.

## Diagnóstico

Na aba **Rede → Diagnóstico**, teste a origem local usando o host e a porta que
o servidor mostra na aba **Servidor**. Se o app não tiver TLS ativado, deixe
**Use HTTPS** desmarcado. Ao detectar que HTTPS falhou, mas HTTP respondeu, o
diagnóstico informa que essa origem usa HTTP e recomenda desmarcar a opção.

Em seguida, teste o hostname público na porta `443` com **Use HTTPS** marcado.
Uma resposta HTTP, inclusive `401`, confirma que o serviço respondeu; `401`
indica que a autenticação do app está ativa. O diagnóstico é executado a partir
do computador onde o app roda e não substitui a confirmação da requisição na
aba **Rede → Atividade**.
