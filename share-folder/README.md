# share-folder.ps1

Script PowerShell que compartilha uma pasta na rede no **Windows 11**, preparando tudo o que o Windows costuma bloquear (serviços, SMB, firewall, perfil de rede) e criando o compartilhamento com permissão de **leitura** ou **leitura e escrita**.

## Requisitos

- Windows 10 ou 11 (testado no desenho para Windows 11)
- PowerShell 5.1 (já vem no Windows)
- Conta com privilégios de administrador (o script pede elevação sozinho)

## Como usar

### Modo interativo (mais fácil)

1. Salve o arquivo `share-folder.ps1` (por exemplo em `D:\`).
2. Abra o PowerShell na pasta do arquivo e rode:

   ```powershell
   powershell -ExecutionPolicy Bypass -File .\share-folder.ps1
   ```

   Ou clique com o botão direito no arquivo e escolha **Executar com o PowerShell**.
3. Aceite o pedido de administrador (UAC).
4. Siga as perguntas:
   - **Escolha a pasta** na janela que abrir.
   - **Nome do compartilhamento** (Enter usa o nome da pasta).
   - **Usuário/grupo com acesso** (Enter libera para todos).
   - **Tipo de permissão**: `1` leitura e escrita, `2` somente leitura.
5. No final, o script mostra o caminho de acesso, por exemplo `\\MEU-PC\Projetos` e `\\192.168.0.10\Projetos`.

### Modo direto (sem perguntas)

```powershell
.\share-folder.ps1 -Pasta "D:\Projetos" -Nome "Projetos" -Usuario "Todos" -Acesso Escrita
```

### Parâmetros

| Parâmetro | Descrição | Exemplo |
|-----------|-----------|---------|
| `-Pasta` | Caminho da pasta a compartilhar | `"D:\Projetos"` |
| `-Nome` | Nome do compartilhamento na rede | `"Projetos"` |
| `-Usuario` | Usuário ou grupo que terá acesso (`Todos` = qualquer um) | `"Todos"`, `"MEU-PC\maria"` |
| `-Acesso` | `Leitura` ou `Escrita` (escrita inclui leitura) | `Escrita` |
| `-SemSenha` | Permite acesso sem senha (menos seguro) | `-SemSenha` |

Parâmetros não informados são perguntados durante a execução.

## O que o script faz

1. **Eleva para administrador** automaticamente, mantendo os parâmetros informados.
2. **Escolhe a pasta**, por janela gráfica ou pelo parâmetro `-Pasta`.
3. **Ativa os serviços de rede**: Servidor (`LanmanServer`), Estação de Trabalho (`LanmanWorkstation`), Publicação de Recursos de Descoberta (`FDResPub`), Host do Provedor de Descoberta (`fdPHost`), SSDP e UPnP, todos em inicialização automática.
4. **Habilita o SMB2/SMB3** no servidor.
5. **Muda redes "Públicas" para "Privadas"**, pois em rede pública o Windows bloqueia o compartilhamento.
6. **Libera o firewall** para os grupos "Compartilhamento de Arquivo e Impressora" e "Descoberta de Rede" nos perfis Privado e Domínio. A identificação é feita por recurso interno do Windows, então funciona em qualquer idioma.
7. **Cria o compartilhamento SMB** (recria se já existir um com o mesmo nome).
8. **Aplica a permissão NTFS** na pasta e subpastas (`Modificar` para escrita, `Leitura e execução` para leitura). A mais restritiva entre SMB e NTFS é a que vale.
9. **Mostra o resultado** com o caminho de rede e os IPs da máquina.

## Acessando de outro computador

- No Windows: pressione `Win + R`, digite `\\NOME-DO-PC\NomeDoCompartilhamento` (ou `\\IP\Nome`) e dê Enter.
- Informe usuário e senha de uma conta existente no PC que compartilha, a menos que tenha usado `-SemSenha`.
- Para uso contínuo, clique com o botão direito na pasta de rede e escolha **Mapear unidade de rede**.

## Acesso sem senha (`-SemSenha`)

Por padrão o Windows exige usuário e senha de uma conta do PC. Com `-SemSenha` o script altera estas configurações:

- `everyoneincludesanonymous = 1` (chave `Lsa`)
- `restrictnullsessaccess = 0` (chave `LanmanServer\Parameters`)
- `AllowInsecureGuestAuth = 1` (política do cliente `LanmanWorkstation`)
- `RejectUnencryptedAccess = False` no servidor SMB

Isso **reduz a segurança**. Use só em rede doméstica confiável. Nos outros computadores que forem acessar, também pode ser preciso habilitar o acesso de convidado inseguro.

## Remover o compartilhamento

```powershell
Remove-SmbShare -Name "NomeDoCompartilhamento" -Force
```

Para ver os compartilhamentos existentes:

```powershell
Get-SmbShare
```

As permissões NTFS adicionadas, o perfil de rede e as regras de firewall **não** são revertidos automaticamente.

## Solução de problemas

| Problema | O que verificar |
|----------|-----------------|
| "A execução de scripts foi desabilitada" | Rode com `powershell -ExecutionPolicy Bypass -File .\share-folder.ps1` |
| Outro PC não encontra `\\NOME-DO-PC` | Tente pelo IP (`\\192.168.x.x\Nome`) e confirme que os dois PCs estão na mesma rede |
| "Acesso negado" ao abrir | Confira usuário e senha, e se o usuário informado em `-Usuario` é o mesmo que está acessando |
| Consegue ler mas não gravar | Rode de novo com `-Acesso Escrita` |
| Antivírus ou firewall de terceiros | Podem bloquear as portas 445 (SMB) e 139; libere nas configurações deles |
| Erro em algum serviço (`!!` no log) | Alguns serviços podem estar bloqueados por política da empresa ou do sistema |

## Aviso

Compartilhar pastas expõe arquivos a outros dispositivos da rede. Compartilhe só o necessário, prefira usuários específicos em vez de "Todos" e evite `-SemSenha` em redes que você não controla.
