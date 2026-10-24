# Estado das melhorias

Última verificação: 23/10/2026.

As contagens abaixo são resultados históricos de execuções específicas. Logs e
capturas locais não são incluídos no clone; para reproduzir a suíte automatizada
atual, execute `QT_QPA_PLATFORM=offscreen venv/bin/python -m unittest discover -s tests -v`.

## Conjunto atual validado

- Pastas HTTP adicionais com permissões por pasta e operações isoladas.
- QR Code dos endereços de acesso e dos links temporários.
- Diagnóstico de resolução de nomes, TCP e HTTP/HTTPS em segundo plano.
- Painel de atividade HTTP com clientes, requisições e tráfego em memória.
- Links temporários com expiração, revogação e senha opcional.
- Fluxos do explorador web na pasta principal e nas pastas adicionais.
- FindPort integrado em Rede, com consulta TCP/UDP, filtros, regras de firewall,
  encerramento de processos protegido e histórico de auditoria.
- Central de transferências no desktop e no navegador, com progresso,
  cancelamento, reenvio e publicação atômica dos uploads completos.

## Câmera ao vivo

Controles de imagem e desempenho: resolução máxima de 320 × 240 a
1920 × 1080, qualidade JPEG de 10% a 95% e preferências persistentes.
Seleção de formato compatível entre os anunciados pelo dispositivo, preservação
da proporção e ausência de ampliação artificial. O desktop mostra FPS publicados
e tamanho efetivo; o navegador mostra FPS de quadros distintos recebidos.
Suíte desta etapa: 173 testes, 172 aprovados e 1 ignorado. Chrome aprovado com
mudança de tamanho ao vivo, métricas, idiomas, pausa/retomada e tela móvel.
Os testes usam dispositivos simulados; negociação de formatos e captura com
webcam física permanecem como validação manual.

Disponível na aba **Câmeras**, com escolha de webcam, captura iniciada pelo
desktop, prévia, parada, URL e QR Code. O visualizador `/_camera/` atualiza
de 1 a 30 quadros por segundo, conforme o seletor do desktop, com padrão de
5 FPS e preferência persistente. A mudança é aplicada durante a transmissão
e o navegador acompanha automaticamente, sem áudio ou gravação, com PT/EN e pausa por cliente.
Os recursos usam as regras de acesso do servidor e respostas sem cache.
Veja [o guia da câmera](camera.md). Nenhuma câmera foi encontrada neste ambiente;
captura física e acesso por outro dispositivo continuam como validação manual.

Suíte completa: 165 testes executados, 164 aprovados e 1 ignorado por falta de
suporte a links simbólicos. O Chrome aprovou acesso autenticado, pausa/retomada,
parada/reinício, idiomas e layout móvel com imagens sintéticas. Evidências:
locais não distribuídas com o código. Os botões do desktop usam ícones nativos
do Qt com texto.
Validação do controle de FPS: 169 testes executados, 168 aprovados e 1 ignorado.
O Chrome verificou mudança de frequência em tempo real entre 20 FPS e 2 FPS
com imagens sintéticas.

## Digitalização WIA

Disponível na aba **Scanners**, com descoberta de dispositivos, digitalização
de uma página em PNG, seleção da pasta de saída e publicação sem sobrescrita.
O processamento roda em segundo plano, com ícones nativos do Qt e textos PT/EN.
Veja [o guia de digitalização](scanning.md). A descoberta real encontrou dois
scanners WIA; aquisição física ainda depende de validação manual. Os testes
usam COM simulado e verificam também o download HTTP autenticado do resultado.
Suíte completa: 158 testes executados, 157 aprovados e 1 ignorado pela
indisponibilidade de links simbólicos. Prévias PT/EN históricas usam um
dispositivo simulado e não são distribuídas com o código.

## Fila de impressão

Disponível na aba **Impressoras**, com consulta em segundo plano, seleção de
impressora, trabalhos, confirmação e revalidação antes de solicitar cancelamento.
Veja [o guia de uso e limites](printing.md). Consulta local de impressoras validada
no Windows; cancelamento validado apenas com cmdlets simulados, sem remover
trabalhos reais.
Nesta etapa, a suíte completa executou 150 testes: 149 aprovados e 1 ignorado
por indisponibilidade de links simbólicos. A descoberta real encontrou 10
impressoras instaladas no Windows. Os botões usam ícones nativos do Qt com texto.

## Central de transferências

Disponível em **Rede → Transferências** no desktop e no botão
**Transferências** do explorador web. Veja [o guia de uso](transfers.md).
Os testes reais cobrem interrupções, cancelamento com clientes parados,
conflitos simultâneos, HTTPS com certificado verificado e parada do servidor.
O Chrome validou a fila, cancelamento e reenvio na raiz, em pasta adicional
e em tela móvel. Reenviar começa novamente do início; retomada por partes
continua fora desta etapa.

## Integração FindPort

Consulte [o guia da subaba FindPort](findport.md). A consulta real de portas
foi validada no Windows; operações de firewall, encerramento e elevação UAC
foram testadas com comandos simulados, sem alterar regras ou processos reais.
Os botões usam ícones nativos do Qt, acompanhados de texto visível.

## Correção desta retomada

O script de compartilhamento SMB foi reorganizado para
`share-folder/share-folder.ps1`, mas a busca do aplicativo ainda esperava o
arquivo na raiz. A localização agora aceita a estrutura atual e a antiga,
inclusive nos diretórios de aplicativos empacotados. Um teste de regressão
cobre os dois formatos no projeto e em um diretório de recursos empacotados.

## Suporte SSH

Em **Rede → SSH**, o teste de conexão e a execução de comandos remotos agora
rodam em segundo plano, sem bloquear a interface. Os controles ficam
temporariamente desativados durante a operação e os textos da aba acompanham
o idioma da interface. É possível selecionar uma chave por host; o aplicativo
armazena somente o caminho, e o teste/comandos usam `IdentitiesOnly` e
autenticação não interativa. Testes de worker, seleção e restauração do caminho
de chave e navegação passaram; consulte o [guia de SSH](ssh.md).

A saída dos comandos remotos agora aparece em uma área de texto rolável que
preserva linhas e mensagens de erro, com ações para copiar ou limpar o
resultado. Os testes verificam texto multilinha, falhas, cópia e limpeza.

Transferências SFTP de arquivos individuais permitem envio e download em
segundo plano com indicador de atividade e cancelamento. O envio avisa que o
arquivo remoto pode ser substituído; downloads usam arquivo temporário local
para preservar o destino até a transferência concluir. O navegador SFTP
permite percorrer pastas remotas e selecionar arquivos para download sem
digitar o caminho completo.

Autenticação por usuário e senha foi adicionada além das chaves SSH. A senha
é mantida somente durante a sessão/ação e nunca salva nas preferências nem em
argumentos de processo. O caminho Paramiko usa `known_hosts` do sistema e
recusa chaves de host desconhecidas ou alteradas.

## Evidências

- `./venv/bin/python -m unittest discover -s tests -v`:
  186 testes executados, 182 aprovados e 4 ignorados (dependências de
  Windows/PowerShell e criação de links simbólicos).
- `./venv/bin/python -m unittest tests.test_findport tests.test_scanning tests.test_storage tests.test_windows_share -v`:
  44 testes executados, todos aprovados, com 3 ignorados por exigência de
  Windows/PowerShell.
- `git diff --check`: sem erros de whitespace.
Os logs dessas execuções históricas eram locais e não acompanham o clone.

A correção concluída cobre a localização do script SMB em layouts antigos,
atuais e empacotados, além da validação de mensagens de plataforma e da
integração da UI com os compartilhamentos de rede e impressoras. Não foi
criado nem removido um compartilhamento SMB real; a aplicação efetiva de
permissões e o acesso por outro dispositivo continuam dependendo de validação
manual no Windows.
