# Limites de recursos HTTP

O servidor aplica limites por instalação para evitar leitura ilimitada de
requisições, criação ilimitada de threads e montagem integral de ZIP em memória.
Os valores padrão são definidos em `src/core/http_limits.py`.

| Recurso | Padrão | Comportamento ao atingir o limite |
| --- | --- | --- |
| JSON de operações de arquivo | 1 MiB | HTTP 413, antes de alterar arquivos |
| JSON de comandos do sistema | 64 KiB | HTTP 413 |
| Leitura de JSON | 15 s no total | HTTP 408 |
| Upload por arquivo | 4 GiB | HTTP 413, antes de criar o upload temporário |
| Upload sem receber dados | 60 s | Interrompe sem substituir o arquivo existente |
| Duração total de upload | 1 hora | Interrompe sem publicar o arquivo incompleto |
| Conexões atendidas simultaneamente | 16 | HTTP 503 ou encerramento da conexão |
| Espera por dados da requisição | 30 s por leitura | Encerra conexão ociosa |
| IPs no controle de taxa, quando habilitado | 4096 | HTTP 429 para novos IPs enquanto estiver cheio |
| Retenção do histórico de IP | 60 s sem requisições | Remove entradas vencidas na próxima requisição |
| Geração e envio de ZIP | Um por vez | HTTP 503 para outro ZIP simultâneo |
| Dados de origem e arquivo ZIP resultante | 1 GiB cada | HTTP 413 |
| Entradas examinadas para ZIP | 10.000 arquivos/pastas | HTTP 413 |
| Geração de ZIP | 120 s | HTTP 503 |

Corpos exigem um único `Content-Length` válido. Transferência HTTP chunked
de corpos não é suportada. Dados incompletos, framing ambíguo e JSON inválido
são rejeitados; a conexão é fechada após erro de leitura. Uploads continuam
usando publicação somente após conclusão e leitura em blocos de até 64 KiB.

A verificação de taxa mantém a janela de um segundo por IP e aceita de 1 a
10.000 requisições por segundo quando configurada. A limpeza de históricos
usa relógio monotônico e não exige um serviço adicional em segundo plano.

O handshake TLS acontece dentro da vaga de conexão, com timeout, para que
um cliente que não conclua a negociação não impeça o servidor de aceitar os
demais. Ao saturar a capacidade, conexões TLS são fechadas antes do handshake;
em HTTP simples, o servidor tenta responder 503 com `Retry-After: 1`.

ZIPs são criados no diretório temporário do sistema e fechados ao terminar,
falhar ou interromper o envio. O download usa o monitor de transferências e
permite cancelamento. A geração verifica o prazo entre entradas e blocos;
uma chamada de disco bloqueada pelo sistema operacional pode ultrapassar o
prazo. Desconexões durante a geração são percebidas no envio; a geração
permanece sujeita aos limites acima. `.serverpy`, links simbólicos e junções
de diretório não são incluídos.

## Ajuste por integração

Os limites entram automaticamente em qualquer inicialização, incluindo a
interface desktop. Integrações Python podem sobrescrever os parâmetros via
`ServerManager.start_server(..., max_post_bytes=..., max_upload_bytes=...,
max_connections=..., body_timeout=..., zip_max_bytes=...)`. Não há novos campos
na interface nesta etapa. Valores inválidos são rejeitados antes de abrir a
porta. Aumentar os limites exige considerar memória, disco e capacidade da rede.

Testes de requisições reais, saturação, timeout e preservação de arquivos ficam
em `tests/test_http_limits.py`; os testes existentes de permissões, TLS e
transferências continuam compondo a regressão.
