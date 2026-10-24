# Comandos remotos do sistema

Intents são uma opção avançada: `POST /api/intent` executa comandos na máquina
do ServerPy com os privilégios da conta que iniciou o aplicativo. O recurso
continua desativado quando a opção correspondente não está selecionada.

## Acesso

- Habilitar intents exige login e senha do administrador geral. A interface
  explica essa exigência e o núcleo recusa iniciar o servidor sem credenciais.
- Cada requisição exige o login geral. Usuários de pasta não podem executar
  comandos, mesmo com todas as permissões de arquivos.
- A rota não é disponibilizada nas pastas adicionais.
- Use TLS ou um canal HTTPS protegido ao acessar remotamente: o login HTTP
  Basic sozinho não cifra credenciais nem comandos.

## Limites

- Uma execução por vez, compartilhada entre os clientes do servidor. Outra
  solicitação recebe HTTP 503 enquanto a execução estiver ocupada.
- Corpo JSON de até 64 KiB, com `Content-Length` único e válido. Corpos maiores
  recebem 413; payload inválido recebe 400 e timeout de leitura recebe 408.
- Timeout de leitura de 15 segundos e execução de até 15 segundos.
- Saída combinada de stdout e stderr de até 1 MiB. Excesso ou timeout de
  execução recebe 504 e libera a vaga para outro comando.
- A entrada padrão fica fechada: comandos interativos não são suportados.

## Compatibilidade e alcance

O campo `command` permanece uma string interpretada pelo shell do sistema,
preservando comandos existentes, pipes e redirecionamentos. Não há lista de
comandos permitidos: o acesso é reservado ao administrador geral e permite
executar operações arbitrárias na máquina. Isso não é um ambiente isolado.

Ao interromper uma execução, o app tenta encerrar os descendentes encontrados
e o processo principal. Processos que se desvinculam ou deixam de ser
identificáveis na árvore podem sobreviver; não use a API para iniciar serviços
ou tarefas em segundo plano. Os limites de saída cobrem stdout/stderr, sem
limitar gravações que o próprio comando faça em arquivos.

Os testes em `tests/test_intents.py` cobrem autorização, concorrência,
recuperação após falha e comandos reais com timeout e excesso de saída.
