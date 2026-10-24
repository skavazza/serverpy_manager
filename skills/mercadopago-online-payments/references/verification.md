# Referencia de verificacao

## Fontes oficiais (verificar novamente na execucao)

- Orders vs Payments: https://www.mercadopago.com.br/developers/pt/docs/checkout-api-orders/resources/migrate-payments-to-orders
- Credenciais: https://www.mercadopago.com.br/developers/pt/docs/checkout-api-orders/resources/credentials
- Teste Bricks: https://www.mercadopago.com.br/developers/pt/docs/checkout-bricks/integration-test/test-payment-flow
- Teste Orders/cartao: https://www.mercadopago.com.br/developers/pt/docs/checkout-api-orders/integration-test/cards
- Contrato do SDK e erros: https://github.com/mercadopago/sdk-js/blob/main/docs/bricks/payment-guest.md
- Campos seguros/Card Payment: https://github.com/mercadopago/sdk-js/blob/main/docs/bricks/card-payment.md

## Diagnostico por camada

| Evidencia | Verificacao seguinte |
|---|---|
| crypto.randomUUID indisponivel | Contexto seguro; alternativa getRandomValues testada em HTTP |
| Fetch falha sem corpo no celular | OPTIONS e CORS da origem exata; funcao publicada; conexao |
| Campo do iframe nao aceita digitar | Foco, inert, modal, eventos de toque e SDK real |
| Campo cortado | Largura util, padding do host e formPadding documentado; sem overflow |
| onError com formulario visivel | type/cause do SDK; validacao, BIN, parcelas, tokenizacao ou inicializacao |
| HTTP 401/codigo 7 | Confirmar resposta/endpoint e contrato da aplicacao; nao atribuir culpa ao CPF ou prefixo sem evidencia |
| Pending sem formulario | Tentativa anterior, paymentFound, referencia e reconciliacao; nao limpar storage para contornar bloqueio |
| Aprovacao direta no sandbox | Validar ainda o Brick real, toque/celular e notificacao assinada |

Preserve erros HTTP/codigos conhecidos com sanitizacao. Nao imprima corpo bruto de APIs administrativas ou do SDK. Usar /users/me com sucesso so confirma identidade/autorizacao daquele recurso.

## Diferencas que precisam migrar juntas

Orders: /v1/orders, valores decimais em strings, transactions.payments, ID alfanumerico ORD, consulta filtrada por referencia/datas, estado da order e da transacao, notificacao order. Payments: /v1/payments, transaction_amount, ID numerico, consulta /v1/payments/search, status do pagamento e notificacao payment. Consulte os contratos atuais antes de codificar.

No modo sandbox Orders deste repositorio, o e-mail enviado ao provedor e test@testuser.com. No fluxo legado Bricks, a documentacao orienta outro procedimento e alerta para nao usar e-mail de usuario de teste. Nao aplique uma regra de e-mail a todas as APIs.

## Exemplo local comprovado em 2026-10-10

O codigo de Reservas ja oferecia MP_API_MODE=orders; Delivery foi adaptado para a mesma API. As credenciais APP_USR mostradas pelo usuario na secao de testes acessaram Orders; um cartao ficticio foi aprovado pela API. Isso nao torna APP_USR sinonimo universal de sandbox nem comprova o Payment Brick real. A falha posterior em onError precisa de diagnostico do cliente.

Implementacoes para consultar, se presentes no projeto:
- apps/delivery/supabase/functions/_shared/server.mjs e mp-orders.mjs
- apps/delivery/public/assets/payments.js e uuid.js
- apps/reservas/supabase/functions/_shared/mp-orders.mjs
- apps/delivery/tests/server.test.mjs e payments-browser.py

O helper de Orders verifica vendedor, referencia, principal, valores pagos, metodo e status; nunca copie somente o construtor da requisicao. Um segredo/evento de webhook nao configurado permanece uma pendencia operacional mesmo com consulta manual funcional.
