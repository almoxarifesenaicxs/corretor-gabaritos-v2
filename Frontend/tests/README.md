# Testes do frontend

Requer Node.js >= 20. Playwright está fixado como dependência **de desenvolvimento**
neste diretório, com lockfile; não altera o ambiente Python nem o build Vercel.
`Frontend/.vercelignore` já exclui `tests/` da publicação.

Na raiz do repositório:

```powershell
npm ci --prefix Frontend/tests --ignore-scripts --no-audit --no-fund
node --test Frontend/tests/*.test.mjs
node --test Frontend/tests/browser.test.cjs
```

A suíte procura Chrome/Edge nos caminhos Windows conhecidos. Para outro caminho,
definir `QA_CHROME_PATH` apontando para o executável instalado. Sem um executável
local, Playwright usa seu Chromium, que precisa estar previamente instalado
(`npx playwright install chromium` neste diretório, caso necessário). Nesta etapa
foi usado o Chrome existente, sem baixar navegador.

## Isolamento

- Não iniciar FastAPI. Um servidor estático temporário escuta apenas em
  `127.0.0.1`, em porta livre, e serve os arquivos públicos do frontend.
- `QA_BASE_URL` e `QA_ARTIFACT_DIR` externos são recusados para não usar servidores
  ou imagens privadas inadvertidamente.
- A configuração pública é substituída somente pela interceptação no navegador;
  `js/config.mjs` e o código da aplicação permanecem intactos.
- O login usa o formulário real e uma resposta simulada do Identity Toolkit.
  A conta `admin@example.test`, a senha e o token são fictícios. Nenhuma chamada
  é enviada ao Firebase. Demais destinos externos são bloqueados e fazem a suíte
  falhar. Service Workers são bloqueados para preservar a interceptação.
- APIs usam respostas em memória. O mock padrão exige o Bearer sintético;
  cenários específicos interceptam persistência e erros. Isso verifica o cliente,
  não substitui os testes de autorização do backend.
- Imagens de entrada são geradas por canvas. Capturas e imagens ficam em um
  diretório exclusivo criado com `mkdtemp`, removido ao encerrar a suíte.
  Os arquivos temporários preexistentes do projeto não são acessados.

## Cobertura e limites

Os cenários antigos passam pelo login antes de usar as telas. Mantêm verificações
de revisão visual, homônimos, confirmação, OCR simulado, webcam simulada, navegação,
carregamento dos fragmentos e reenvio idempotente após perda da resposta.
Os novos cenários verificam bloqueio sem sessão, Bearer, logout, ausência de tokens
no armazenamento e respostas 401/403 no login e durante a sessão.

Os resultados, posições de marcação, nomes OCR e comprovantes são contratos
sintéticos. Não comprovam precisão de OCR, assinatura criptográfica, integração
real com Firebase ou correção do motor Python. Essas responsabilidades continuam
na suíte Python e na futura homologação autorizada. Não usar credenciais reais
para executar estes testes.

Referência: [interceptação de rede no Playwright](https://playwright.dev/docs/network).
