---
name: mercadopago-online-payments
description: Configurar, diagnosticar e homologar pagamentos online Mercado Pago em projetos web, incluindo Checkout Transparente, Bricks, Orders ou Payments API e backend Supabase. Use quando houver integracao nova, credenciais, erro de pagamento, webhook ou homologacao mobile.
---

# Pagamentos online Mercado Pago

Produza uma integracao verificavel. Nao prometa ausencia de erros do provedor. Registre o que foi comprovado, o que foi simulado e o que ainda depende de teste ou configuracao externa.

## Identificar o contrato antes de alterar

Confirme produto da aplicacao, API usada pelo backend, componentes do SDK, pais, ambiente e projeto Supabase. Leia a implementacao existente. Checkout Transparente pode usar Orders ou Payments; o nome do produto sozinho nao identifica o endpoint. Um formulario que gera token de cartao nao comprova que o backend usa a API correta.

Nao classifique credenciais por prefixo APP_USR/TEST ou tag test_user isoladamente. Compare aplicacao e recebedor com o painel e consulte a documentacao oficial atual para o fluxo escolhido. Uma imagem da secao Credenciais de teste e evidencia que deve ser conciliada com os metadados da API; nao contradiga o usuario por suposicao. Alterar um seletor Teste nao converte credenciais. Nunca invente uma chave trocando seu prefixo.

Consulte [references/verification.md](references/verification.md) para diagnostico, diferencas entre APIs e criterios de homologacao. Consulte fontes oficiais atuais antes de reutilizar dados ou regras de testes.

## Configurar no escopo autorizado

Reutilize autorizacoes da sessao. A leitura desta skill nao autoriza alteracoes externas, pagamentos reais ou troca de conta recebedora. Com publicacao autorizada, conclua testes e publique no projeto confirmado; nao transfira ao usuario comandos que voce pode executar com a autenticacao disponivel.

Public Key e URL/chave publica do Supabase podem estar no cliente. Access Token, segredo de webhook e service role ficam no servidor/Vault. Nunca imprima, comite ou incorpore segredos a instrucoes ou artefatos. Para diagnosticos administrativos, capture respostas sensiveis em memoria e imprima apenas resultados sanitizados. Preserve segredos existentes quando campos privados estiverem vazios.

Teste /users/me para identidade e pais, mas nao trate isso como prova de capacidade para criar pagamento. Uma consulta Orders bem-sucedida tambem nao comprova criacao. Mantenha registro da API na tentativa e consulte pedidos antigos pela API original. Uma migracao requer criacao, consulta, normalizacao, webhook e validacao de valores; trocar somente o endpoint nao basta.

## Preservar as invariantes de pagamento

- Calcule total no servidor pelo catalogo publicado. Use centavos internamente e formato exigido pela API na requisicao.
- Valide recebedor, referencia, pais/moeda quando fornecida, ambiente quando fornecido, metodo, parcelas, principal e estado antes de aprovar. Nao compare cegamente total financiado com principal quando ha juros.
- Verifique conta/configuracao antes de bloquear a tentativa. Use idempotencia estavel; nunca crie nova chave ou reenvie automaticamente apos resposta incerta.
- Reconcile pelo ID/referencia no provedor. A ausencia de um pagamento em uma consulta nao autoriza automaticamente liberar uma tentativa recente. Encerramento de teste ou recuperacao exige evidencia suficiente e atualizacao condicional, preservando o registro.
- O sucesso da chamada HTTP nao equivale a pagamento aprovado. Orders pode criar a order e falhar a transacao (HTTP 402); consulte o resultado antes de concluir.
- Configure o evento correspondente: order para Orders, payment para Payments. Verifique HMAC e busque o estado atual; aceite o formato de ID correto e impe?a rebaixamento por eventos antigos. Relate se falta configurar eventos/segredo.

## Verificar a experiencia real

Teste digitar com foco/toque em campos seguros e confira largura, rolagem, parcelas e conclusao. Viewport de 390 px sem has_touch/is_mobile nao valida celular. Iframe simulado nao valida SDK real. Teste DevTools, celular fisico e HTTPS quando forem relevantes; distinga esses resultados.

HTTP na rede local pode nao oferecer crypto.randomUUID ou recursos exclusivos de contexto seguro. Quando aplicavel, gere UUID v4 com crypto.getRandomValues; nunca use Math.random para segredos. Confirme CORS/OPTIONS para a origem exata. No delivery, HTTP em IPv4 privado e aceito somente no ambiente de teste. Isso nao torna HTTP equivalente a HTTPS para SDK, Auth ou PWA.

Evite modais nativos/travas de foco que tornem elementos auxiliares do SDK inert. Reserve largura adequada e use as customizacoes documentadas do SDK. Nao reduza o formulario com transform scale ou edite o conteudo de iframe do provedor.

Separe falhas do formulario de falhas do backend. Trate onError por type/cause, distinguindo validacao non_critical de inicializacao critical. Exiba somente causas conhecidas e mensagens locais; nao exponha error.message bruto ou formData. Um erro de campo incompleto nao significa que a opcao de pagamento falhou ao carregar.

## Concluir com evidencia

Execute testes de valores divergentes, idempotencia, falha de rede, consulta e assinatura do webhook. Homologue com cartao ficticio no sandbox somente dentro do escopo autorizado e com ambiente confirmado. Registre ID e estado sanitizados da homologacao. Uma aprovacao direta na API nao comprova o fluxo completo do navegador.

Informe separadamente: implementacao local, publicacao remota, pagamento sandbox, SDK em navegador real e webhook observado. Nao encerre como validacao completa se algum componente necessario permanece pendente. Para producao, confirme origem HTTPS, credenciais correspondentes, observabilidade e reconcilia??o; nao ative cobrancas reais por inferencia.
