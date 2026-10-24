# Acesso SSH

Abra **Rede → SSH** para conectar a um host remoto usando o cliente OpenSSH
instalado no computador. Informe o host, a porta e, opcionalmente, o usuário.
Também é possível salvar hosts para reutilizá-los; esses dados ficam nas
preferências locais do aplicativo.

- **Autenticação:** escolha **Chave privada / agente SSH** ou **Usuário e
  senha**. A senha é solicitada na interface, fica apenas em memória enquanto
  você usa a sessão atual e é apagada após uma operação; nunca é salva nas
  preferências nem passada como argumento a um processo. O modo de senha usa
  Paramiko para testar a conexão, executar comandos e navegar/transferir via
  SFTP. **Abrir terminal** usa o OpenSSH do sistema e solicita a senha no
  próprio terminal.
- **Chave privada:** selecione o arquivo de identidade OpenSSH a usar para o
  host. O aplicativo salva somente o caminho do arquivo junto ao perfil; a
  chave privada não é copiada nem lida pelo aplicativo. Use **Limpar** para
  voltar às identidades padrão do OpenSSH.
- **Testar SSH** verifica se o host aceita uma conexão e executa um comando
  simples. A operação roda em segundo plano para manter a interface responsiva.
- **Abrir terminal** inicia o cliente OpenSSH interativo, que pode usar as
  chaves e o agente SSH configurados no sistema.
- **Executar comando** envia o texto do campo ao host remoto. Use apenas
  comandos que você entende e confia. A operação roda em segundo plano; a
  saída completa, inclusive várias linhas e mensagens de erro, aparece na área
  de resultados. Use **Copiar saída** ou **Limpar saída** conforme necessário.
- **SFTP:** use **Procurar...** para navegar pelas pastas remotas e selecionar
  um arquivo; o caminho escolhido preenche o campo de arquivo remoto. Também
  é possível digitar o caminho manualmente. Use **Enviar arquivo** ou
  **Baixar arquivo** para transferir arquivos individuais pelo `sftp` do
  OpenSSH, com indicador de atividade e cancelamento. O envio pede confirmação
  porque pode substituir o arquivo remoto. O download grava primeiro em um
  arquivo temporário local e só substitui o destino após concluir; ao cancelar,
  o arquivo temporário é removido. Um envio cancelado pode deixar um arquivo
  remoto incompleto, dependendo do servidor SFTP.

O aplicativo não salva senhas nem chaves privadas. Com chave, teste e comandos
usam autenticação não interativa; se a chave exigir frase secreta, carregue-a
no agente SSH do sistema. A autenticação por senha requer uma chave do host já
confiável no `known_hosts` do OpenSSH. Para verificar e registrar a identidade
na primeira conexão, use **Abrir terminal** e confira a impressão digital
apresentada pelo OpenSSH;
conexões desconhecidas ou com chave alterada são recusadas pelas operações
Paramiko até que a identidade seja verificada.

Ao conectar a um host novo, o OpenSSH pode aceitar e registrar a chave de host.
Se uma chave já conhecida mudar, confira a identidade do servidor antes de
alterar a entrada local `known_hosts`. O teste confirma somente a conexão SSH
a partir deste computador; não altera firewall nem prova acesso de outros
dispositivos.
