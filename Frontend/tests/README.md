# Testes do frontend

Requer Node.js >= 20. Playwright está fixado como dependência de desenvolvimento
neste diretório, sem afetar o backend ou o build da Vercel.

```powershell
node --test Frontend/tests/*.test.mjs
node --test Frontend/tests/browser.test.cjs
```

Os testes de navegador servem `Frontend` em um servidor temporário limitado a
`127.0.0.1`. A configuração da API é substituída apenas na interceptação do
navegador; todas as respostas administrativas são sintéticas. Destinos externos
são bloqueados. Nenhum Firebase real, Firestore real ou backend hospedado é
acessado. Imagens de teste ficam em diretório temporário exclusivo, removido ao
encerrar a suíte.

O navegador abre o dashboard sem login e testa navegação, avaliações, alunos,
uploads, câmera, OCR, revisão visual, respostas 403/503 e reenvio idempotente.
Chrome ou Edge local são usados quando disponíveis; `QA_CHROME_PATH` permite
indicar outro executável.
