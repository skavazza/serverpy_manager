# Conectar celulares Android

O app oferece dois caminhos para usar o celular:

- **Aba Android:** conecta um aparelho autorizado por USB, transfere arquivos
  acessíveis ao usuário do Android e inicia o espelhamento/controlador scrcpy
  em uma janela própria.
- **Rede local:** o navegador do celular abre o servidor HTTP do computador
  usando o endereço e o QR Code disponíveis em Rede → Diagnóstico.

## Preparar scrcpy para controle visual

Na aba **Android**, use **Instalar controle de tela scrcpy** para baixar a
versão oficial da Genymobile compatível com o sistema. O pacote é validado por
SHA-256 e instalado na pasta de dados do usuário, sem privilégios de
administrador ou alteração do `PATH`. Se scrcpy já estiver disponível no
`PATH`, o app o reutiliza. O download integrado está disponível para Windows
x86_64/ARM64 e Linux x86_64.

O pacote de scrcpy também contém um ADB próprio. Se uma instalação anterior no
Linux mostrar `Permission denied` ao executar `adb start-server`, reinicie o
ServerPy atualizado; ele restaura as permissões de execução do scrcpy e do ADB
contidos na instalação gerenciada pelo app.

Selecione um dispositivo autorizado e clique em **Iniciar controle de tela**
para abrir a janela nativa do scrcpy. A janela aceita mouse e teclado e pode
ser encerrada pelo botão **Parar controle de tela** ou pela própria janela. A
sessão também é encerrada ao sair do app. Os botões Android predefinidos e os
controles incluem Voltar, Início, Apps recentes, energia, tela, volume,
rotação manual, notificações, configurações rápidas e recolher painéis.
Rotacionar manualmente desativa a rotação automática; use **Restaurar rotação
automática** para reativá-la.

As opções ficam agrupadas em **Configurações de vídeo**, **Configurações de
áudio** e **Comportamento da sessão**. É possível limitar resolução e FPS,
escolher codecs e taxas de bits, selecionar fonte de áudio, orientar a imagem
na janela e ajustar tela/estado da sessão. Os padrões mantêm resolução
original, H.264, 8 Mbps, saída de áudio do aparelho em Opus/128 Kbps e
orientação padrão. H.265, AV1, fontes de áudio e orientações específicas
dependem do suporte do aparelho; se uma opção não for compatível, o scrcpy
mostra o erro no status. As opções de codec e fonte de áudio ficam desativadas
quando o encaminhamento de áudio está desligado.

A sincronização da área de transferência é opcional e vem desativada. Ao
ativá-la, o scrcpy sincroniza o clipboard com o computador; texto colado no
Android fica acessível aos aplicativos Android que puderem ler esse clipboard.
Ative-a somente quando necessário e evite colar senhas ou outros dados
sensíveis.

Marque **Gravar esta sessão do scrcpy** antes de iniciar para salvar a sessão
em MP4; a gravação é finalizada ao fechar a janela ou parar a sessão. A captura
de tela salva uma imagem PNG local. **Instalar APK** pede confirmação antes
de enviar o pacote ao dispositivo; instale somente APKs de fontes confiáveis.
O navegador de arquivos da aba Android também pode enviar arquivos à pasta
aberta no telefone.

## Preparar USB/ADB

1. Em **Dispositivos USB → Celular Android (ADB)**, clique em **Instalar
   ferramentas Android (ADB)** caso o ADB não esteja instalado. O app baixa
   Android SDK Platform-Tools diretamente de `dl.google.com`, verifica o
   SHA-256 do pacote e o instala na pasta de dados do usuário, sem privilégios
   de administrador nem alteração do `PATH`. Um ADB já disponível no `PATH`
   continua sendo usado primeiro.
2. No Android, habilite as Opções do desenvolvedor e a Depuração USB.
3. Conecte o cabo de dados, desbloqueie o aparelho e aceite o diálogo para
   autorizar este computador.
4. Abra a aba **Android** e clique em **Atualizar
   dispositivos Android**. Estados `unauthorized` ou `offline` não podem ser
   usados; confirme a autorização no celular ou reconecte o cabo.
5. Navegue a partir de `/sdcard/Download`. Selecione um arquivo para baixar ou
   envie um arquivo do computador para a pasta aberta. O envio pede confirmação
   porque pode substituir um arquivo com o mesmo nome.

As operações usam o usuário ADB normal do aparelho; não fazem root nem acessam
dados privados de outros aplicativos. O Android pode negar arquivos fora das
pastas acessíveis ao usuário. USB debugging deve permanecer desativado quando
não estiver em uso, e só autorize computadores confiáveis.

O download integrado está disponível para Windows e Linux x86_64. O pacote
oficial Linux disponibilizado pelo Google é x86_64; outras arquiteturas Linux
precisam instalar um ADB compatível por conta própria e deixá-lo no `PATH`.
No Windows, são instalados `adb.exe` e as DLLs oficiais necessárias ao lado do
executável. Os arquivos permanecem na pasta de dados do usuário do ServerPy.
As URLs e os hashes fixados seguem os pacotes oficiais usados pelos scripts de
dependência do [scrcpy](https://github.com/Genymobile/scrcpy/tree/master/app/deps).

## Abrir o servidor pelo cabo USB

1. Inicie o servidor HTTP no app.
2. Selecione o Android autorizado e clique em **Ativar acesso USB ao servidor
   HTTP**.
3. No navegador do celular, abra a URL local mostrada pelo app, por exemplo
   `http://127.0.0.1:8080`. Se TLS estiver ativado no app, a URL usa `https`.
4. Use **Remover acesso USB** para apagar o encaminhamento quando terminar.

O encaminhamento usa `adb reverse` e exige que o servidor escute no localhost ou
em todas as interfaces. O túnel fica associado à sessão ADB e pode persistir
até removê-lo, desconectar o aparelho ou reiniciar o serviço ADB. O app não
altera opções de desenvolvedor, não aceita automaticamente a chave RSA do
computador e não instala apps no telefone.

O servidor registra o tráfego USB reverso como loopback (`127.0.0.1`), não com
o endereço Wi-Fi do celular. Por isso, uma lista de IPs permitidos não
distingue esse acesso USB de outro acesso local.

## Controlar o celular pela rede (Depuração sem fio)

Requer Android 11 ou superior, com o celular e o computador na mesma rede.

1. No celular: Opções do desenvolvedor → **Depuração sem fio** → ativar.
2. Na aba **Android**, em **Conexão Wi-Fi**, clique em **Buscar celulares na
   rede**. Os aparelhos anunciados aparecem na lista (`pairing` ou `connect`).
3. Primeiro pareamento: no celular, toque em **Parear dispositivo com código**,
   selecione a entrada `pairing` (ou digite o IP:porta mostrado), informe o
   código de seis dígitos e clique em **Parear**.
4. Selecione a entrada `connect` (ou digite o IP:porta da tela principal da
   Depuração sem fio) e clique em **Conectar**. O aparelho passa a aparecer na
   lista de dispositivos e aceita scrcpy, controles e transferências.
5. **Desconectar** encerra a conexão de rede do aparelho selecionado.

Se a busca não achar nada (a descoberta mDNS pode ser bloqueada pela rede),
digite o endereço manualmente.

## Acesso pelo Wi-Fi

Conecte o computador e o celular à mesma rede local, inicie o servidor HTTP e
abra **Rede → Diagnóstico → Mostrar QR Code para o celular**. Selecione um
endereço de rede local em **Servidor** antes de mostrar o código. O celular
abre a URL no navegador; a autenticação e as demais restrições configuradas no
servidor continuam valendo.
