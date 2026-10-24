# Fila de impressão

Na aba **Impressoras**, clique em **Atualizar impressoras** e escolha uma
impressora instalada. A tabela mostra ID, documento, proprietário, estado,
páginas e horário de envio. As consultas são executadas em segundo plano;
clique em atualizar para acompanhar alterações feitas por outros aplicativos.

Selecione um trabalho e clique em **Cancelar trabalho selecionado**. A confirmação
tem **Não** como opção padrão. Antes de pedir a remoção, o aplicativo consulta
novamente o trabalho e compara impressora, ID, documento, proprietário e horário.
Se houver mudança ou desaparecimento, a operação falha e deve ser atualizada.
Essa verificação reduz o risco de agir sobre um ID reutilizado; a fila do Windows
pode continuar mudando entre a consulta e a remoção.

O recurso requer Windows 10 ou 11 e o serviço de impressão disponível. Usa as
permissões do usuário atual, sem elevação automática. Falhas e tempos esgotados
são exibidos na tela; após falha de cancelamento, a seleção antiga é descartada.
Um tempo esgotado não prova que o Windows deixou de executar a operação: atualize
antes de tentar novamente. Páginas já impressas não podem ser recuperadas.

O painel não envia documentos para impressão nem altera drivers, compartilhamento,
serviço Spooler ou configurações de impressoras térmicas.

Implementação baseada em [Get-PrintJob](https://learn.microsoft.com/en-us/powershell/module/printmanagement/get-printjob)
e [Remove-PrintJob](https://learn.microsoft.com/en-us/powershell/module/printmanagement/remove-printjob).
Os botões usam os ícones nativos do Qt, com texto visível e navegação por teclado.

Validação automatizada: consulta vazia e Unicode, erros, timeout, identificação
incompleta, confirmação, tradução e interface assíncrona. O script de cancelamento
é executado em PowerShell com funções simuladas para verificar cada campo de
identidade, sem remover trabalhos reais. Testes com impressora física e cancelamento
real continuam sendo validação manual.
