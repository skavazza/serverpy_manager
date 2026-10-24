---
name: krakentech-mvps
description: Criar MVPs KrakenTech a partir de rascunhos e evoluir produtos em andamento, especialmente delivery, agendamentos e gestão financeira, respeitando o domínio e a organização de cada aplicação.
---

# Desenvolver MVPs KrakenTech

Transforme a proposta do produto solicitado em um fluxo utilizável e continue implementações existentes. Esta skill orienta desenvolvimento; não implica publicar catálogo, implantar servidores ou ativar cobranças reais.

## Identificar o produto e o estado real

Neste repositório, cada produto fica em `apps/<produto>/`. `apps/site/` é o catálogo comercial e não o backend dos produtos. Leia o README e inspecione código, testes e migrações do produto escolhido antes de planejar alterações. Não considere um rótulo do catálogo como prova de que o produto está implementado ou instalado em produção.

- Delivery: leia `apps/delivery/README.md`; evolua o cardápio, carrinho, pedidos, CMS e integrações existentes.
- Agendamentos: leia `apps/agendamentos/README.md`; a proposta inicial usa serviços, profissionais e disponibilidade por horário.
- Gestão financeira: leia `apps/gestao-financeira/README.md`; a proposta inicial trata de controle financeiro operacional.
- Reservas: use o guia específico `apps/reservas/SKILL.md` para regras de hospedagem.
- Produto novo: defina público, operação principal e resultado esperado; crie uma pasta própria sem alterar os demais produtos.

Os caminhos acima são relativos à raiz do repositório. Fora dele, adapte a estrutura ao projeto de destino. Para regras de negócio, leia apenas o domínio relevante em [references/domains.md](references/domains.md).

## Do rascunho ao fluxo completo

Antes de implementar um projeto novo, revisar os projetos KrakenTech existentes: ler READMEs e examinar painéis administrativos, permissões e fluxos relevantes. Buscar sugestões de funcionalidades aplicáveis ao novo domínio, distinguindo recursos implementados de propostas. Sempre perguntar ao usuário sobre público, objetivo, funcionalidades, exclusões, perfis de acesso e critérios de aceitação; aproveitar respostas explícitas já fornecidas e esclarecer lacunas. Apresentar sugestões para o painel administrativo, com finalidade, perfis autorizados e classificação como essencial, opcional ou não aplicável. Definir o escopo e resolver lacunas essenciais com o usuário antes de implementar. Não copiar funcionalidades de outro domínio nem ampliar o escopo automaticamente.

Para um rascunho, defina o primeiro fluxo de ponta a ponta e seus critérios de aceitação: o que o cliente faz, o que o administrador acompanha e qual estado fica persistido. Use a proposta existente como ponto de partida, preservando as decisões do usuário. Questione decisões que mudem o modelo de dados ou a operação; avance nas partes independentes enquanto elas são esclarecidas.

Para um produto em andamento, implemente a funcionalidade solicitada sobre a arquitetura atual. Diferencie o que já funciona, o que é demonstração e o que depende de instalação externa. Não reconstrua uma aplicação existente nem implemente os outros rascunhos só porque estão no mesmo repositório.

Frontend estático em HTML/CSS/JavaScript, Supabase e funções de servidor são a referência local, quando atendem ao escopo. Preserve outra stack escolhida pelo usuário. Crie `public/`, documentação e testes conforme a implementação exigir; migrações e funções pertencem ao produto que utiliza esses recursos.

## Reaproveitamento e isolamento

Reutilize padrões de autenticação, publicação de conteúdo, fotos, painel e componentes visuais. Adapte as regras de negócio; não copie tabelas de hóspedes, intervalos de noites ou estados de reserva para outros domínios.

Separe banco, configurações, sessões de autenticação e credenciais entre catálogo comercial, produtos e instalações de clientes. Reaproveitar código não autoriza reutilizar dados particulares nem tokens. Sirva somente a pasta pública. Proteja operações no banco e no servidor, inclusive contra chamadas diretas que ignoram a interface.

No painel, permita configurar os dados de negócio do escopo: identidade visual, conteúdo, itens, preços, horários e opções. Use edição por item, blocos claros, botões compactos e controles compatíveis com o tema existente. Separe salvar rascunho de publicar e indique quando uma alteração vale apenas neste navegador. Segredos ficam no servidor; a interface pode indicar presença, testar ou substituir credenciais sem revelá-las.

## Painel obrigatório e administrador principal

## Personalização obrigatória por cliente

Todos os projetos KrakenTech devem ser personalizáveis para entrega a clientes diferentes. Use uma base reutilizável do produto com configurações próprias por instalação; evite exigir alterações no código para a personalização rotineira de um cliente.

Disponibilize no painel a edição de nome comercial, logo, cores do tema, imagens, textos, contatos, endereço e dados de negócio aplicáveis ao domínio, como produtos, serviços, acomodações, preços e horários. Respeite a hierarquia de permissões: configurações críticas e módulos restritos continuam sob controle do administrador principal. Valide cores, imagens e conteúdo para preservar legibilidade e funcionamento em celular e desktop.

Centralize essas configurações e aplique a identidade do cliente de forma consistente ao site, painel, mensagens e documentos gerados que façam parte do escopo. Use dados de exemplo apenas na demonstração; não deixe marca, contatos ou credenciais de um cliente anterior embutidos na entrega.

Separe configurações, dados, arquivos e credenciais de cada cliente. Uma instalação independente pode usar seu próprio backend; se o produto adotar uma arquitetura compartilhada, garanta isolamento por cliente no servidor e no banco. Não introduza uma arquitetura compartilhada apenas para permitir personalização.

Documente a preparação de uma nova instalação, a configuração do administrador principal e a publicação das personalizações. Valide a mesma base com duas identidades distintas para conferir que a troca de cliente não exige modificar regras do produto nem expõe dados de outra instalação. Funcionalidades sob medida fora das opções configuráveis devem ser tratadas como desenvolvimento adicional.

## Painel obrigatório e administrador principal

Todos os projetos KrakenTech devem ter um painel administrativo com autenticação, inclusive os MVPs desenvolvidos a partir de rascunhos. O painel faz parte da entrega do produto e deve permitir administrar as operações e configurações previstas no escopo.

Distinga o administrador principal dos demais administradores e operadores. Defina e documente, por produto, quais funções somente o principal pode acessar, ativar ou desativar. Como referência, reserve ao principal a gestão de usuários e permissões, credenciais de integrações, configurações críticas e habilitação de módulos restritos; adapte a lista às decisões do usuário e às permissões já existentes.

Aplique essas restrições no servidor e no banco, além da interface. Outros perfis não podem acessar funções restritas nem alterar sua ativação por chamadas diretas. Não permita que um usuário conceda a si próprio o papel de principal. Crie o primeiro principal por um processo de instalação controlado, sem senha embutida ou cadastro público com privilégios.

Os controles de ativar e desativar devem persistir por instalação e valer também nas operações do backend. Diferencie função desativada de falta de permissão: ativar um módulo não concede acesso a todos os usuários. Documente o efeito da desativação e preserve registros existentes; desativar uma função não apaga dados nem cancela pagamentos automaticamente. Registre quem alterou as configurações restritas e quando.

Na validação, confira o acesso do principal e a recusa para administradores comuns, operadores e visitantes, inclusive por chamadas diretas. Verifique também que uma função desativada não continua executável no servidor.

## Instalação como PWA obrigatória

Todos os projetos KrakenTech, incluindo delivery, devem oferecer instalação como Progressive Web App (PWA) nos navegadores e dispositivos compatíveis. Inclua um manifesto válido com nome, nome curto, ícones de 192 e 512 pixels, ícone adequado ao recorte (maskable), cores do tema, modo de exibição independente e caminhos de início e escopo coerentes com a instalação. Personalize esses dados com a identidade do cliente.

Use HTTPS na instalação publicada e registre o service worker no escopo correto. Considere também as demonstrações em subpastas: o service worker de um produto não pode controlar outro produto ou o site comercial. Disponibilize uma ação de instalar quando o navegador oferecer essa possibilidade e instruções adequadas aos dispositivos que exigem instalação pelo menu. Não prometa suporte idêntico em todos os navegadores.

Defina uma estratégia de cache e atualização para os arquivos públicos, com limpeza de versões antigas e indicação de atualização quando necessário. Não armazene respostas autenticadas, dados pessoais, credenciais, pagamentos nem operações administrativas em caches compartilhados. A instalação como PWA não autoriza copiar dados privados para uso offline.

Sem conexão, indique claramente a indisponibilidade de operações que dependem do servidor. Não apresente um pedido, agendamento ou pagamento como confirmado por ter sido salvo localmente. Operação offline com sincronização exige escopo específico, tratamento de conflitos e proteção contra duplicidade. Instalar o PWA não garante notificações com o aplicativo fechado; notificações push exigem implementação própria e seguem a autorização do desenvolvedor.

Valide manifesto, ícones, escopo, instalação, atualização e comportamento sem rede em dispositivos compatíveis. Confira que trocar a identidade do cliente também atualiza os recursos do PWA e que o cache não expõe dados de outra conta ou instalação. Documente os limites observados.

## Cadastro do cliente e preparação da entrega

Ao vender e preparar a entrega de um projeto, disponibilize um cadastro do cliente vinculado ao produto vendido e à instalação correspondente. Permita ao administrador principal cadastrar e atualizar:

- Nome do cliente ou responsável e, para empresas, razão social.
- E-mail e telefone com DDD e código do país.
- Endereço: logradouro, número, complemento opcional, bairro, cidade, estado e CEP.
- Tipo de cliente: pessoa física ou jurídica; CPF para pessoa física e CNPJ para pessoa jurídica. Se houver responsável por uma empresa, trate seu CPF como um campo separado quando necessário.
- Project URL do Supabase e publishable key da instalação do cliente.

Valide e normalize os dados no servidor, incluindo CPF/CNPJ conforme as regras vigentes e o formato do e-mail. A validação do documento não comprova identidade. Diferencie o endereço do Supabase do endereço público do produto, caso ambos sejam cadastrados.

Restrinja o cadastro de entrega ao administrador principal no painel, servidor e banco. Nome, documentos, endereço e contatos do cliente não podem aparecer no catálogo público nem nas demonstrações. Associe cada venda à instalação correta; um cliente pode adquirir mais de um produto ou ter mais de uma instalação.

A publishable key é uma chave pública de conexão, mas não concede acesso administrativo: mantenha autenticação e políticas de acesso no Supabase. Nunca aceite secret key ou service_role nesse campo nem as publique no frontend. O Project URL deve usar HTTPS, sem credenciais embutidas; teste a conexão com a chave pública sem alterar dados e apresente erros claros. Credenciais privadas de integrações ficam separadas, no servidor.

Salvar o cadastro não cria o projeto Supabase, aplica migrações nem configura todos os navegadores automaticamente. Use esses dados no procedimento de instalação, confira o projeto de destino e documente a configuração pública, autenticação, políticas e funções necessárias antes de concluir a entrega. Preserve o isolamento entre clientes ao trocar ou atualizar uma conexão.

## Notificações com autorização do desenvolvedor

Todos os projetos devem oferecer uma opção de envio de notificações adequada ao domínio. Separe a autorização do recurso, concedida exclusivamente pelo desenvolvedor, da ativação operacional, que pode ser feita pelo operador após essa autorização.

No painel do desenvolvedor, permita autorizar ou revogar o uso de notificações e definir os canais, eventos e limites disponíveis conforme o escopo. No painel do operador, permita ativar ou desativar os envios autorizados. O operador não pode conceder a própria autorização, modificar credenciais nem habilitar canais ou eventos que o desenvolvedor não liberou.

O envio só pode ocorrer quando a autorização do desenvolvedor e a ativação operacional estiverem vigentes e o canal estiver configurado. Guarde esses estados por instalação e confira-os no servidor em envios manuais, automáticos, agendados e novas tentativas. Revogar a autorização interrompe os próximos envios, inclusive os ainda na fila; uma nova autorização exige nova ativação do operador para evitar retomada inesperada.

Exiba estados claros: não autorizado, autorizado e desativado, ativo ou aguardando configuração do canal. Registre quem autorizou, ativou ou desativou o recurso e mantenha histórico dos envios e falhas sem expor credenciais ou conteúdo privado a perfis sem acesso.

Defina os eventos relevantes do produto, destinatários e canal de entrega conforme o escopo. A opção de notificações é obrigatória; integrações externas específicas, como WhatsApp oficial, SMS ou e-mail, dependem do canal escolhido e de sua configuração. Evite envios duplicados ao repetir eventos ou tentativas.

Valide que o operador consegue ativar notificações autorizadas, que não consegue contornar a falta de autorização e que a revogação pelo desenvolvedor bloqueia os envios no backend. Verifique também isolamento entre clientes, falhas do canal e retomadas sem duplicidade.

O administrador principal do cliente não pode conceder a autorização de notificações.

## Catálogo, demonstração e personalizações

O cadastro comercial é independente da configuração do produto. Preserve IDs, preços, links personalizados e repositórios privados existentes ao integrá-lo ao catálogo. Dados privados não entram no JSON público.

“Conhecer produto” abre informações e fotos. “Testar demo” precisa de um endereço válido e uma aplicação navegável. Uma demo local não prova instalação em produção. Neste repositório, confira as rotas `/demos/<produto>/` do servidor e os caminhos de assets; adicione uma rota de forma explícita se o novo produto precisar dela.

Descreva como proposta aquilo que ainda não existe. Atualize fase, capturas e funcionalidades conforme evidências da implementação. Não marque produção automaticamente ao terminar uma tarefa. Personalizações comerciais por MVP têm nome, valor adicional e prazo; são estimativas de orçamento e não alterações automáticas no checkout ou funcionalidades implementadas.

## Integrações e entrega

Pagamentos, mensagens automáticas, emissão fiscal e outras integrações entram quando fizerem parte do escopo. Confira documentação oficial vigente antes de integrar APIs. Para cobranças, calcule valores no servidor, use idempotência e valide notificações com dados do provedor; redirecionamento do navegador não confirma pagamento. Todo projeto que oferece pagamentos deve disponibilizar Pix direto com QR Code e cartão dentro da aplicação. Pix direto depende de conferência manual. Quando houver Mercado Pago, usar Checkout Transparente.

Valide o fluxo principal e seus riscos: autorização, consistência dos dados, concorrência quando aplicável e estados financeiros. Confira o painel e o site em celular e desktop. Para mudanças visuais, prefira verificação no navegador. Documente comandos reais de execução e testes, configuração necessária e limitações que ainda impedem operação.

Entregue o que foi pedido com evidências de validação. Distinga código concluído, demonstração disponível e serviço implantado. Migrações remotas, publicação de catálogo e implantação exigem o contexto e a autorização correspondentes; criar a skill não autoriza essas ações.
