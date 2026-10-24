# Central de transferências

## No navegador

O botão **Transferências** abre os envios feitos pela página atual. Escolher
arquivos ou arrastá-los para uma pasta abre o painel automaticamente.
Os arquivos são enviados um por vez, com nome, progresso, bytes, velocidade
média e estimativa de tempo restante. **Finalizando** indica que o navegador
enviou o conteúdo e aguarda a confirmação do servidor.

Use **Cancelar transferência** para interromper um envio ou retirar um arquivo
da fila. **Reenviar arquivo** tenta novamente um envio cancelado ou com falha,
desde o início, mantendo a pasta de destino. Essa versão não retoma um arquivo
pelo ponto em que parou. Arquivos existentes não são substituídos pelo upload
da interface. O resultado de cada arquivo aparece separadamente, e o resumo
distingue cancelamentos de falhas.

O histórico mantém até 100 registros finalizados, além da fila ativa. **Limpar
finalizadas** remove esses registros da tela. Os dados ficam na memória desta
página; recarregá-la ou navegar para outra pasta encerra a fila. O navegador
pode pedir confirmação antes de sair durante um envio.

Se a conexão for interrompida depois que todo o conteúdo foi enviado, o servidor
pode já ter salvo o arquivo. Nesse caso, o painel orienta conferir o destino.
O reenvio preserva qualquer arquivo que já exista.

## Na interface desktop

Abra **Rede → Transferências** para acompanhar os uploads PUT e downloads de
arquivos servidos diretamente, incluindo pré-visualizações e links temporários.
A tabela mostra caminho público, IP, direção, estado, porcentagem, bytes,
velocidade, estimativa de tempo restante e duração.

Selecione uma transferência ativa e clique em **Cancelar transferência
selecionada** para interrompê-la. A atualização ocorre a cada meio segundo
enquanto a subaba está visível. O painel mantém todas as transferências ativas
e as últimas 100 encerradas na memória. Parar o servidor cancela as ativas;
iniciar uma nova sessão limpa o histórico. Códigos de links temporários e
parâmetros das URLs não aparecem na lista.

Os contadores consideram conteúdo dos arquivos, sem cabeçalhos HTTP ou tráfego
TLS/TCP. A velocidade usa uma janela aproximada de cinco segundos. Download
concluído significa que o servidor enviou os bytes, sem confirmar que o cliente
os salvou. ZIPs gerados em memória, APIs, edição de texto e sessões SMB seguem
fora desta tabela; a atividade HTTP geral continua disponível na subaba
**Atividade**. O cancelamento não desfaz um arquivo já concluído.

## Gravação e interrupções

Uploads são gravados em arquivos `.part` na área reservada
`.serverpy/uploads` da raiz correspondente. Eles ficam fora da navegação,
busca e acesso HTTP direto. O servidor só publica o destino após receber todos
os bytes declarados, usando uma operação atômica no mesmo sistema de arquivos.
Uma tentativa de sobrescrita interrompida preserva o arquivo anterior.
Conflitos entre envios simultâneos com `If-None-Match: *` também preservam
o primeiro arquivo publicado.

Cancelamentos, conexões interrompidas e falhas de gravação removem o temporário
da operação. A leitura e o envio mantêm prazo de 60 segundos sem progresso,
com verificações periódicas de cancelamento; arquivos grandes podem demorar
mais que isso enquanto continuam progredindo. Após encerramento forçado do
processo ou queda de energia, temporários podem permanecer ocultos; esta etapa
não implementa recuperação nem limpeza automática desses restos.

## Verificação

Os testes cobrem envios incompletos, preservação do original, conflitos
concorrentes, cancelamento de upload e download, parada do servidor, prazo de
inatividade, contagem de bytes, privacidade dos links, tradução e seleção na
GUI. Upload e download HTTPS são verificados com certificado temporário
quando OpenSSL está disponível. O Chrome verifica cancelamento de envio em
andamento e na fila, reenvio e operações existentes na raiz e em pasta adicional.

Verificação em 23/10/2026: suíte completa com 144 testes aprovados e 1 ignorado
por limitação de criação de links simbólicos. Chrome aprovado nas duas raízes.
Esses resultados e capturas são observações históricas locais e não acompanham
o clone do código. Reproduza a suíte automatizada com
`QT_QPA_PLATFORM=offscreen venv/bin/python -m unittest discover -s tests -v`.
