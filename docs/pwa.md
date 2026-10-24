# PWA do explorador

Reinicie o servidor para carregar a atualização. A interface pode ser instalada
como app e continua acessando os arquivos pelo mesmo servidor e endereço.

No Chrome ou Edge, abra o explorador e use **INSTALAR APP** quando o navegador
oferecer a instalação, ou o comando de instalação no menu do navegador.
No iPhone/iPad, use o Safari e **Compartilhar → Adicionar à Tela de Início**.
O botão depende do suporte e da oferta de instalação do navegador.
Se você alternar entre pastas compartilhadas usando o mesmo endereço e porta,
o app instalado abrirá a pasta que o servidor estiver compartilhando no momento.

O endereço precisa usar HTTPS com certificado confiável. Para teste no próprio
computador, `http://localhost:PORTA/` e `http://127.0.0.1:PORTA/` também funcionam.
Um endereço como `http://192.168.1.10:PORTA/` continua funcionando como site,
mas precisa de HTTPS para os recursos do PWA no celular ou em outro computador.
O servidor já oferece a opção TLS; o certificado deve ser confiável no dispositivo.

A instalação não mantém o servidor Python ligado: o computador e o servidor
precisam estar disponíveis para acessar os arquivos. O cache contém somente
uma tela genérica de servidor indisponível, com botão para tentar novamente.
Arquivos, senhas, listagens, APIs e operações de escrita não são guardados pelo
service worker. As permissões e a autenticação do servidor continuam aplicadas.
O editor Ace continua dependendo da CDN que a interface já utilizava.

Os recursos do app ficam em `/_serverpy/pwa/`, uma rota reservada ao PWA,
independente da pasta compartilhada. A interface também funciona normalmente
quando o navegador não suporta instalação ou o service worker falha.

Os testes de navegador desligam e religam somente o servidor temporário criado
pelo teste para verificar a tela de indisponibilidade e a reconexão reais.

## Backup e restauração

### Indicador de comunicação

O canto inferior esquerdo mostra o **Ping** da última requisição ao servidor
e a **Média** das últimas 10 medições bem-sucedidas. A medição usa o tempo
de ida e volta HTTP (inclui rede e processamento do servidor), em milissegundos.
Ela acontece a cada 5 segundos após a resposta anterior, somente com a página visível,
com limite de 3 segundos por requisição. Quando a comunicação falha, o indicador
mostra **Servidor indisponível** e zera as medições anteriores; elas recomeçam
quando o servidor responde novamente. A rota `/api/ping` respeita autenticação
e permissões e não usa cache. O indicador também funciona sem instalar o PWA.

Antes dessa alteração foi criado outro backup da versão PWA funcionando:
`backups/pre-latency-20261009-131439/project.zip` (51 arquivos com SHA-256 verificado).
Para voltar somente à versão anterior ao indicador, pare o servidor e execute:

```powershell
.\venv\Scripts\python.exe .\backups\pre-latency-20261009-131439\restore.py --apply
```

### Versão anterior ao PWA

Backup anterior à adaptação: `backups/pre-pwa-20261009-130519/project.zip`.
Inclui código, testes, documentação, scripts e artefatos existentes; exclui
Git, o ambiente virtual, caches Python e a própria pasta de backups.
O ambiente virtual existente não é alterado pela adaptação.
`sha256.json` registra os hashes verificados de todos os 39 arquivos do ZIP.

Para verificar o backup sem alterar arquivos, na raiz do projeto:

```powershell
.\venv\Scripts\python.exe .\backups\pre-pwa-20261009-130519\restore.py --check
```

Para voltar à versão anterior, pare o servidor e feche a interface desktop.
O comando seguinte salva uma cópia dos arquivos atuais, restaura o ZIP e
remove somente os novos arquivos introduzidos pelo PWA. Alterações posteriores
nos arquivos do backup serão substituídas pela versão do backup.

```powershell
.\venv\Scripts\python.exe .\backups\pre-pwa-20261009-130519\restore.py --apply
```

Depois, reinicie o servidor. No navegador, remova o service worker em
**Ferramentas do desenvolvedor → Application → Service Workers → Unregister**
e o cache `serverpy-pwa-v1` em **Cache Storage**, então recarregue a página.
Se instalou o app, também pode desinstalá-lo pelo navegador/sistema.
