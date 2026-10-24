# Regras por domínio

Leia a seção do produto solicitado. As propostas dos READMEs são o ponto de partida; escolhas explícitas do usuário têm precedência.

## Delivery

Evolua a implementação em `apps/delivery/` em vez de começar um segundo cardápio. Separe categorias, itens, adicionais, horários, entrega/retirada, pedido e pagamento. O resumo deve guardar os preços e opções contratados: editar o cardápio depois não altera pedidos antigos.

Valide itens disponíveis, quantidades, adicionais e total no servidor para pedidos persistidos. Defina a progressão operacional com o cliente; pagamento aprovado e pedido entregue são eventos diferentes. Confirme taxa de entrega, área atendida e fechamento do estabelecimento quando isso afetar a tarefa. Integração oficial de WhatsApp, estoque e impressão de cozinha não são requisitos automáticos.

Verifique carrinho, pedido com adicionais, indisponibilidade de item e acesso administrativo. Ao mexer em pagamentos, verifique repetição da tentativa e coerência entre pedido e cobrança. Mantenha dados de demonstração identificados.

## Agendamentos

Modele duração do serviço, profissional, horário de atendimento e bloqueios. Use início inclusivo e fim exclusivo: um atendimento pode começar quando o anterior termina, respeitando o intervalo adicional configurado. Disponibilidade deve considerar a duração inteira, o fuso do estabelecimento e os estados que ocupam a agenda.

Impeça dois agendamentos concorrentes para o mesmo profissional no banco. A consulta pública expõe horários livres ou ocupados sem dados do cliente. Separe solicitação, confirmação e cancelamento conforme o fluxo acordado; não presuma aprovação automática.

Para decisões pendentes, consulte quantidade de profissionais, intervalos e política de confirmação/cancelamento quando necessário. Pagamentos, lembretes e WhatsApp são extensões do escopo. Verifique concorrência, fronteiras de horário, bloqueios e permissões.

## Gestão financeira

Trate valores com precisão decimal no banco ou unidades monetárias inteiras. Defina se o relatório usa data do movimento, vencimento ou baixa; rótulos e totais devem refletir essa escolha. Diferencie previsto, realizado e cancelado. Uma conta baixada não pode gerar uma segunda entrada de caixa ao repetir a ação.

Preserve histórico e rastreabilidade de correções. Defina quais perfis podem lançar, corrigir e exportar; isole dados entre instalações. Listas, filtros, exportação e totais devem usar a mesma regra e o mesmo período.

O MVP proposto é controle operacional. Emissão fiscal, contabilidade oficial, conciliação bancária, estoque e conexão a bancos precisam de escopo próprio. Verifique centavos, baixa repetida, correções e isolamento de dados.

## Outros MVPs

Identifique a entidade principal, seus estados, quem pode alterá-la e quais invariantes precisam ser garantidas no banco. Escolha um fluxo completo de primeira entrega antes de adicionar módulos. Não transplante estados de pedido, agenda ou reserva para um domínio sem avaliar seu significado.
