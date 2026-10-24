# Câmera ao vivo

Na aba **Câmeras**, clique em **Atualizar câmeras** e selecione uma webcam
reconhecida pelo Qt Multimedia. A descoberta não inicia a captura.

1. Inicie o servidor na aba **Servidor** e escolha seu endereço de acesso.
2. Abra **Câmeras**, selecione o dispositivo e clique em **Iniciar transmissão**.
3. Confira a imagem no painel. Use **Copiar URL da câmera**, **Abrir câmera no
   navegador** ou **QR Code da câmera** para acessar o visualizador.
4. Para outro dispositivo, selecione um endereço da rede local e conecte-o à
   mesma rede. Endereços `localhost` e `127.0.0.1` só funcionam neste computador.
5. Clique em **Parar transmissão** para liberar a câmera. Parar o servidor ou
   fechar a janela principal também encerra a captura. Ela não reinicia sozinha.

Use **Taxa de quadros da transmissão** para escolher de **1 a 30 FPS**.
O padrão inicial é **5 FPS** e sua preferência fica salva para a próxima abertura.
É possível alterar o valor enquanto transmite, sem reiniciar o servidor.
O navegador acompanha a mudança na próxima consulta de imagem,
sem precisar recarregar a página. A taxa escolhida é um limite: câmera,
processamento, rede e limites de requisições podem reduzir a taxa efetiva.

O visualizador fica em `http://IP:PORTA/_camera/` (ou HTTPS conforme configurado).
Ele atualiza a imagem até a taxa escolhida, por requisições JPEG
sequenciais, com resolução máxima selecionável e proporção preservada.
Não inclui gravação, WebRTC, RTSP ou acesso a câmeras IP por URL.
O aplicativo conserva somente a imagem mais recente em memória.

## Áudio do microfone (opcional)

Marque **Incluir áudio do microfone** antes de **Iniciar transmissão**. A opção
vem desmarcada e não é salva entre aberturas. O app captura o microfone escolhido
na lista ao lado (por padrão, o microfone padrão do Windows) em PCM de 16 bits e guarda só os últimos 5 segundos em memória. No
visualizador, clique em **Ativar áudio** (o navegador exige esse clique para
tocar som). O áudio passa pelas mesmas regras de autenticação, IPs e limite de
requisições da câmera; quem puder abrir a página poderá ouvir o ambiente.

O áudio é entregue por consultas HTTP (`/_camera/audio.pcm`) e tem atraso típico
de 0,3 a 1 segundo; não é sincronizado quadro a quadro com a imagem. Se o
microfone faltar ou o formato não for suportado, a transmissão segue só com
vídeo e o painel avisa. Parar a transmissão ou o servidor encerra o áudio.

## Resolução, qualidade e FPS efetivo

- **Resolução máxima da transmissão:** 320 × 240, 640 × 480, 960 × 540
  (padrão), 1280 × 720 e 1920 × 1080. São limites de saída: a proporção é
  mantida e imagens menores nunca são ampliadas. Por exemplo, uma câmera 16:9
  com limite de 640 × 480 produz uma imagem de 640 × 360.
- **Qualidade JPEG:** de 10% a 95%, com padrão de 75%. Valores maiores tendem
  a preservar mais detalhes e aumentar o tamanho dos quadros e o tráfego de rede.
  A porcentagem é o parâmetro de compressão do JPEG, sem medir fidelidade exata.
- Resolução, qualidade e FPS ficam salvos entre aberturas. Os controles podem
  ser ajustados durante a transmissão. O aplicativo escolhe um formato anunciado
  pelo dispositivo que atenda ao tamanho solicitado, preferindo taxas suficientes.
  Sem um formato adequado, usa a melhor alternativa anunciada; sem lista de
  formatos, mantém o padrão do driver e reduz a imagem na saída.
- A troca de formato nativo pode causar uma pausa ou ser recusada pelo driver.
  Erros aparecem no painel. A imagem efetivamente recebida determina o tamanho
  publicado; selecionar Full HD não cria detalhes que a câmera não entrega.
- **Publicados:** média dos novos JPEGs disponibilizados pelo desktop em uma
  janela de até 5 segundos. Não conta consultas HTTP e não confirma recebimento
  por todos os clientes. O painel mostra também FPS solicitados e tamanho real.
- **Recebidos:** no navegador, conta quadros distintos recebidos nessa janela,
  sem contar consultas repetidas à mesma imagem. Pode ficar abaixo dos FPS
  publicados por causa da rede, do processamento ou da frequência de consulta.
  Não representa uma medição do monitor nem do tempo de renderização.
- As métricas começam em zero, precisam de pelo menos meio segundo para formar
  a média e são reiniciadas com a sessão. Pausar/ocultar o visualizador zera
  seus contadores locais; imagens indisponíveis não mantêm FPS recebidos antigos.
- O limite de cada JPEG é 8 MiB. Somente o quadro mais recente é retido pelo
  aplicativo; quadros que excederem esse limite interrompem a transmissão com
  orientação para reduzir a resolução ou a qualidade.

## Acesso e comportamento

- Os clientes usam autenticação, IPs permitidos, verificação de Host, TLS e
  limite de requisições já configurados no servidor. Se a autenticação estiver
  desativada, quem puder acessar o servidor poderá ver a câmera enquanto ativa.
- O botão de iniciar existe apenas no desktop; abrir a página não ativa hardware.
- As respostas da câmera solicitam `no-store`. Cabeçalhos de cache personalizados
  não substituem essa política, e CORS não é habilitado para os recursos da câmera.
- A página tem seleção PT/EN, layout móvel e um botão de pausar/retomar a
  visualização naquele navegador. Pausar ou ocultar a aba suspende suas consultas
  e oculta a imagem; outros clientes continuam recebendo imagens.
- O visualizador oculta a imagem quando a transmissão fica indisponível. Uma
  imagem sem atualização por mais de 3 segundos deixa de ser entregue pelo servidor.
- O desktop para a captura se não receber o primeiro quadro em 10 segundos ou
  se ficar mais de 5 segundos sem novos quadros após iniciar. Erros e desconexões
  são informados no painel.
- O limite de requisições é compartilhado com o restante do servidor. Um limite
  baixo pode interromper a visualização; cada cliente ativo consulta até a taxa
  escolhida por segundo, além da abertura da página e de seus recursos.
- Imagens já entregues a um cliente não podem ser revogadas. O aplicativo não
  grava vídeo, mas clientes podem salvar o conteúdo que recebem.
- O prefixo `/_camera/` é reservado na raiz HTTP. Não existe um alias de câmera
  dentro das pastas adicionais `/_shares/`.

No Windows, permita o acesso de aplicativos desktop à câmera nas configurações
de privacidade. Se o dispositivo estiver ocupado, libere-o no outro aplicativo
e inicie a transmissão novamente. A disponibilidade depende do driver e do
backend Qt Multimedia instalado.

## Validação

A suíte automatizada cobre geração de JPEG, redução de resolução, limite de
quadros, expiração, troca de sessão, descarte de quadros atrasados, desligamento,
erros, desconexões, timeout e traduções. Os testes HTTP verificam autenticação,
IPs, rate limit, HEAD, cache, CORS e parada do servidor.

O teste `venv\Scripts\python.exe tests/run_camera_smoke.py` usa imagens geradas
localmente, sem acionar webcam. O Chrome verifica acesso autenticado, pausa e
retomada, transmissão interrompida e reiniciada, PT/EN, layout móvel e mudança
de frequência de atualização durante a transmissão (20 FPS e 2 FPS).

Controle de FPS: suíte completa com 169 testes, 168 aprovados e 1 ignorado;
observação histórica local. O teste Chrome mediu 18 consultas em 1 segundo com 20 FPS selecionados, e
2 consultas em 1,2 segundo com 2 FPS. Essas medições usam imagens sintéticas
e verificam a frequência de consulta, sem comprovar desempenho de uma webcam.

Resolução, qualidade e métricas: suíte completa com 173 testes, 172 aprovados e
1 ignorado em uma execução histórica local. Os testes verificam JPEGs codificados,
proporção, ausência de ampliação, formatos anunciados, persistência e contagem
de quadros distintos. O Chrome verifica mudança de tamanho sem recarregar a
página e distingue FPS recebidos de frequência de consultas, com câmera sintética.

Nenhuma câmera foi encontrada pela descoberta real neste ambiente; captura
física, permissões do dispositivo e acesso por outro aparelho dependem de
validação manual. Os resultados, logs e prévias dessas execuções eram locais
e não fazem parte do clone do código; as prévias usaram uma câmera simulada.
Para reproduzir a suíte automatizada atual, execute
`QT_QPA_PLATFORM=offscreen venv/bin/python -m unittest discover -s tests -v`.

Referências: [QVideoSink](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QVideoSink.html)
e [QMediaCaptureSession](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QMediaCaptureSession.html).
Seleção de formato: [QCameraFormat](https://doc.qt.io/qtforpython-6/PySide6/QtMultimedia/QCameraFormat.html)
e [QCamera.setCameraFormat](https://doc.qt.io/qtforpython-6.8/PySide6/QtMultimedia/QCamera.html).
