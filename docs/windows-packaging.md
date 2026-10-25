# Executável Windows

## Gerar o pacote

No Windows x64, a partir da raiz do repositório:

```powershell
venv\Scripts\python.exe -m pip install -r requirements-build.txt
venv\Scripts\python.exe -m unittest discover -s tests
venv\Scripts\python.exe tests/run_desktop_smoke.py
venv\Scripts\python.exe -m PyInstaller --noconfirm packaging/windows.spec
```

O resultado é `dist/ServerPy/ServerPy.exe`. Distribua **toda a pasta
`dist/ServerPy`**, incluindo `_internal`; o executável sozinho não basta.
O destinatário não precisa instalar Python. Este é um pacote portátil em pasta,
sem instalador e sem assinatura digital.

A configuração inclui a interface Qt, metadados, templates HTTP/PWA, ícones,
licença, avisos de terceiros, scripts de compartilhamento e o FindPort vendorizado.
Os checkouts locais `.agents`, `scrcpy`, `scrcpy-gui` e `findport` não são incluídos.
ADB, scrcpy e WireGuard continuam sendo componentes externos, instalados pelos
fluxos próprios do aplicativo quando necessários.

## Limites de validação

Um build bem-sucedido e a abertura local do executável não substituem o teste
em uma máquina Windows limpa, sem Python e sem as ferramentas do desenvolvedor.
Antes de distribuir, validar nesse ambiente: abertura, HTTP/PWA, persistência,
reinício, inicialização automática e os recursos de dispositivos incluídos.
SMB e instalação/serviços WireGuard precisam de testes reais com os privilégios
apropriados. A VPN permanece em homologação; os testes simulados não comprovam
tráfego, rotas, firewall ou funcionamento de serviços reais.

## Verificação local em 25/10/2026

- Build Windows x64 gerado com PyInstaller 6.22.3 e ícone do aplicativo.
- Suíte completa existente: 392 testes aprovados. Depois da inclusão do teste
  de regressão da inicialização Windows, os 19 testes de privilégios e
  compartilhamento também passaram.
- Smoke test do código-fonte: 11 abas em 980×760 e 1440×900, autenticação,
  permissões, upload/download/exclusão/restauração e reinício HTTP aprovados.
- Executável iniciado em Qt offscreen a partir de um diretório temporário,
  sem `PYTHONPATH`/`PYTHONHOME`, permaneceu ativo durante a observação de 8 segundos.
  Recursos essenciais conferidos dentro de `_internal`.
- `pip check`: nenhuma dependência quebrada.

Os resultados locais ficam em `artifacts/windows-*.log`,
`artifacts/windows-executable-check.json` e `artifacts/windows-packaging-smoke/`.
Ainda não houve homologação do pacote em uma instalação Windows limpa nem
validação manual completa do executável.
