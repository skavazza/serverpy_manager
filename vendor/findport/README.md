# 🛡️ FindPort - Gerenciador Interativo de Portas e Firewall (Windows)

Uma ferramenta completa de auditoria, segurança e controle de portas de rede para **Windows**. Lista portas abertas (**TCP e UDP**), analisa o nível de exposição na rede, reconhece serviços conhecidos e permite decidir entre **finalizar o processo** ou **bloquear a porta no Firewall sem fechar o aplicativo**, mantendo histórico reversível para desbloqueio a qualquer momento.

---

## ⚡ Como Executar em 1 Clique

No ServerPy HTTP Manager, o FindPort também está disponível em **Rede →
FindPort**, com consulta e ações integradas à GUI. Consulte o
[guia da integração](../docs/findport.md).

Basta dar **duplo clique** no arquivo:
```cmd
run.bat
```
> O arquivo solicita automaticamente permissão de **Administrador (UAC)** do Windows e abre o terminal pronto para uso com acesso total ao Firewall e processos.

---

## 🚀 Como Executar pelo Terminal

Se preferir rodar manualmente no **PowerShell**:

```powershell
.\find_ports.ps1
```

Opções via linha de comando:
```powershell
.\find_ports.ps1 -ApenasSeguras    # Inicia filtrando apenas portas que podem ser fechadas
```

---

## 🌟 Principais Recursos

1. **⚡ Executável em 1 clique (`run.bat`)**: Não precisa abrir o PowerShell e digitar comandos como administrador manualmente.
2. **🌐 Detecção de Exposição de Rede**:
   - 🏠 **Local (PC)** (`127.0.0.1` / `::1`): Baixo risco, acessível apenas localmente.
   - ⚠️ **Rede / Aberta** (`0.0.0.0` / `*`): Exposta para outros aparelhos na sua rede local/Wi-Fi.
3. **📡 Suporte Completo a TCP e UDP**: Audita tanto servidores TCP (`Listen`) quanto endpoints UDP (jogos, streaming, DNS, VoIP).
4. **🏷️ Dicionário Inteligente de Portas**:
   - Identifica automaticamente portas famosas: `3306` (MySQL), `5432` (PostgreSQL), `6379` (Redis), `3000`/`5173`/`8080` (Web Dev), `5037` (Android ADB), `7070` (AnyDesk), `3389` (RDP), etc.
5. **🔍 Busca e Filtro em Tempo Real**:
   - Digite **`[B]`** para pesquisar por termo (ex: filtrar por `node`, `mysql`, `8080` ou `anydesk`).
   - Digite **`[C]`** para limpar a busca.
6. **🔒 Bloquear no Firewall vs Encerrar Processo**:
   - **`[1]` Encerrar Processo**: Libera a porta matando o aplicativo (com trava de segurança em processos vitais do Windows como `System`, `svchost`, `lsass`).
   - **`[2]` Bloquear no Firewall**: Mantém o aplicativo aberto e funcionando, mas impede qualquer conexão externa na porta.
7. **🔄 Desbloqueio e Memória de Regras**:
   - Ao abrir o FindPort, ele verifica se existem portas bloqueadas anteriormente por você e permite restaurá-las a qualquer momento teclando **`[D]`**.
8. **📝 Histórico de Auditoria (`findport_audit.log`)**:
   - Todas as ações de encerramento de processos, bloqueios e desbloqueios são registradas com data, hora, porta, protocolo e processo.

---

## 📖 Arquitetura e Especificação para IAs

Para especificações detalhadas, regras de negócio e convenções técnicas para Inteligências Artificiais ou novos desenvolvedores, consulte o arquivo [REQUIREMENTS.md](REQUIREMENTS.md).
