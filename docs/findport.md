# FindPort na interface desktop

No Windows 10 ou 11, e também no Linux com suporte a sockets e `psutil`, abra **Rede → FindPort**. A consulta começa ao abrir a subaba e roda em segundo plano. Use **Atualizar** depois de abrir ou fechar um programa. A lista inclui portas TCP em escuta e endpoints UDP locais, com endereço, PID, processo, exposição, categoria e serviço conhecido.

No Linux, a consulta usa a API nativa do sistema e `psutil` para listar conexões ativas; no Windows, a ação de firewall e o bloqueio usam os scripts do FindPort e a elevação UAC quando necessária.

- Digite no campo de busca para filtrar porta, processo, serviço ou endereço.
- Escolha TCP ou UDP e use **Ocultar processos protegidos** quando necessário.
- **Buscar porta do servidor** usa a porta real enquanto o servidor está
  iniciado, inclusive quando foi configurado com porta 0.
- Selecione uma porta e use **Bloquear porta** para criar uma regra de entrada
  no Firewall do Windows em todas as interfaces. No Linux, a ação fica disponível para o fluxo nativo de consulta e bloqueio do sistema, sem depender do PowerShell do Windows. O aplicativo continua aberto.
- Selecione uma regra na tabela inferior e use **Remover regra de bloqueio
  selecionada**. Somente a regra `FindPort_Block_TCP_PORTA` ou
  `FindPort_Block_UDP_PORTA` correspondente é removida. Essa tabela também
  permite remover regras de portas que já não estão em escuta.
- **Encerrar processo** fecha todo o aplicativo associado, incluindo outras
  portas usadas por ele, e pode perder alterações não salvas. A ação fica
  indisponível para processos críticos, o gerenciador e processos sem uma
  identificação completa. O adaptador confere novamente o horário de criação
  do processo e a associação à porta antes de encerrar.
- **Histórico de auditoria** abre as últimas entradas de
  `findport/findport_audit.log` em uma janela de consulta.

As alterações pedem confirmação na GUI e solicitam elevação UAC no Windows quando
necessário. No Linux, a ação de parar processo e bloquear porta usa o fluxo nativo do sistema e não exige elevação extra. A interface aguarda o resultado e atualiza a consulta após uma ação bem-sucedida. Cancelamentos e falhas aparecem no painel. Nenhuma dessas ações acontece apenas ao abrir a aba ou consultar portas.

Uma vinculação à rede indica o endereço de escuta, sem comprovar acesso pela
internet. A coluna **Regra FindPort** indica a existência/ativação de uma regra
gerenciada, sem resumir todo o firewall. Outras regras e o estado do Firewall
do Windows continuam influenciando o acesso. Falhas na consulta de regras são
exibidas como estado desconhecido.

## Implementação e validação

Em clones limpos, `vendor/findport/gui_bridge.ps1` reutiliza as funções de
coleta e classificação do arquivo irmão `find_ports.ps1` por meio de
`-LibraryOnly`, sem entrar no menu de console. No workspace de desenvolvimento,
o checkout aninhado `findport/` continua disponível como alternativa. O console
original e `run.bat` estão no snapshot vendorizado. O adaptador troca JSON com
`src/core/findport.py`; a GUI usa um trabalhador em segundo plano.
Os botões usam ícones nativos do Qt e textos visíveis em português/inglês.

Em 23/10/2026, a consulta real retornou endpoints TCP/UDP no Windows e no Linux. Os testes
de regressão cobrem filtros, seleção, tradução, cancelamento da confirmação,
falhas de consulta, argumentos estruturados, regras idempotentes, auditoria,
proteção de processos e cancelamento de UAC com comandos simulados. Não foram
alteradas regras reais nem encerrados aplicativos reais durante a validação.
O teste de consulta real abre endpoints temporários TCP e UDP em portas disponíveis,
confere sua detecção e verifica a proteção do próprio processo. A suíte
completa terminou com 130 testes aprovados e 1 ignorado pela limitação de
criação de links simbólicos do ambiente; esses resultados e capturas eram
observações locais, e os arquivos de evidência não são distribuídos com o
código. Reproduza os testes com
`QT_QPA_PLATFORM=offscreen venv/bin/python -m unittest tests.test_findport -v`.
