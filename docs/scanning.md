# Digitalização de uma página

Na aba **Scanners**, clique em **Atualizar scanners**. São listados os scanners
que o Windows reconhece pelo WIA (Windows Image Acquisition). Instale o driver
WIA do fabricante caso um dispositivo conectado não apareça. Compartilhar uma
impressora multifuncional por SMB não compartilha seu scanner.

1. Selecione um scanner.
2. Clique em **Escolher pasta de saída** ou **Usar pasta do servidor**.
3. Coloque a página na origem padrão do dispositivo e clique em **Digitalizar uma página**.
4. Aguarde a conclusão. O caminho do arquivo aparece no painel; o botão
   **Abrir pasta da digitalização salva** abre a pasta no Windows.

O arquivo é salvo em PNG, com nome único `scan-DATA-HORA-IDENTIFICADOR.png`.
Arquivos anteriores não são substituídos. A imagem é adquirida em uma pasta
temporária local e publicada na saída somente após o comando WIA concluir.
Arquivos intermediários da publicação ficam na área reservada `.serverpy/uploads`,
seguindo o mecanismo de uploads existente. Falhas e tempos esgotados limpam os
intermediários; o painel informa o erro do Windows sem tratar falha como sucesso.

**Usar pasta do servidor** usa a raiz do servidor em execução; com o servidor
parado, usa a pasta configurada na aba Servidor. O botão só escolhe o destino,
sem iniciar o servidor nem alterar suas configurações. Se salvar em uma pasta
compartilhada, os clientes com acesso a ela poderão consultar o documento.
Atualize o explorador web após a digitalização. Autenticação, restrições de IP
e TLS seguem a configuração existente do servidor.

## Compatibilidade e limites

- Windows 10/11, serviço WIA disponível e dispositivo com driver WIA.
- Uma página por clique, usando o primeiro item de aquisição e as configurações
  padrão do driver. Não há seleção de origem, área, resolução ou modo de cor.
- Não inclui PDF, OCR, processamento em lote, duplex ou configuração de alimentador.
- O comando é iniciado no desktop; não existe endpoint de digitalização remota.
- Descoberta e aquisição rodam em segundo plano, com os controles bloqueados
  durante a operação para evitar disparos duplicados.
- Aquisição limitada a 2 minutos. Em timeout, verifique se o dispositivo terminou
  antes de tentar novamente. Encerrar o processo de aquisição não garante que o
  mecanismo físico do scanner pare imediatamente. Não há cancelamento pelo painel.
- A pasta temporária contém o documento durante a aquisição e é removida ao
  concluir ou falhar. Após encerramento abrupto do aplicativo ou do sistema,
  intermediários podem permanecer nas pastas temporárias.

## Validação

Os testes cobrem descoberta, erros, plataforma não suportada, timeout, validação
do destino, nomes únicos, descarte de intermediários, imagem PNG legível e
download HTTP com autenticação. O script de aquisição é executado em PowerShell
com objetos COM simulados, inclusive para dispositivo desconectado e nomes com
caracteres especiais. Nenhum desses testes aciona um scanner real.

A descoberta real em Windows encontrou dois scanners WIA. Digitalização física,
origem selecionada pelo driver e compatibilidade dos modelos dependem de teste
manual com uma página no dispositivo.
A conversão real de uma imagem BMP local para PNG também foi verificada por
`WIA.ImageProcess`, sem acionar scanner. As prévias PT/EN usam dispositivo simulado.
Esses resultados e prévias são observações históricas locais e não acompanham
o clone do código. Reproduza os testes automatizados com
`QT_QPA_PLATFORM=offscreen venv/bin/python -m unittest discover -s tests -v`.

Referências: [WIA Automation](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/wiaaut/-wiaaut-objects),
[formatos de imagem WIA](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/wiaaut/-wiaaut-consts-formatid)
e [conversão por filtros](https://learn.microsoft.com/en-us/previous-versions/windows/desktop/wiaaut/-wiaaut-howto-use-filters).
