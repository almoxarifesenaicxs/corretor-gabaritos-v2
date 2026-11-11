# Separação do frontend e backend — Etapa 07

A API pode iniciar sem a pasta `Frontend`. A interface continua disponível em
`/interface/` no uso local quando essa pasta existe. Não há mudança no Firestore,
no motor de correção, em `ProtecaoLocal` ou em `exigir_acesso_local()`.

## Backend

Variáveis lidas ao iniciar o processo (não há carregamento automático de `.env`):

| Variável | Valores e comportamento |
| --- | --- |
| `SERVIR_FRONTEND` | `auto` (padrão): monta a interface somente se a pasta existir; `false`: API isolada; `true`: exige a pasta e falha se ausente. |
| `CORS_ORIGINS` | Origens HTTP(S) separadas por vírgula; padrão vazio. Sem curingas, caminhos, credenciais, query ou fragmento. Exemplo local: `http://127.0.0.1:8000`. |

CORS permite apenas GET/POST e Content-Type, sem credenciais. A proteção local
executa antes do CORS, inclusive nos preflights OPTIONS. Uma origem externa
listada **continua recebendo 403**. IP remoto, Host externo e cabeçalhos de proxy
continuam bloqueados. CORS não autoriza operações administrativas.

Para continuar usando localmente, execute de `Backend`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --workers 1
```

Para iniciar somente a API local, defina `$env:SERVIR_FRONTEND = "false"` antes.
Remova essa variável ou use `auto` para voltar à interface integrada.

## Configuração pública no navegador

`Frontend/js/config.mjs` é um arquivo estático importado por `api.mjs`:

```javascript
export const API_BASE_URL = "";
```

Vazio mantém `/api/...` na mesma origem. Para preparar uma distribuição separada,
altere somente esse valor no artefato público para a origem do backend, por exemplo
`https://api.example`. Não inclua `/api`, credenciais, query ou fragmento. A barra
final é opcional. Todos os módulos continuam chamando caminhos `/api/...`; somente
`api.mjs` resolve o endereço final. Fragmentos HTML continuam vindo do frontend.

O arquivo deve ser entregue junto dos módulos, inclusive na hospedagem estática.
Variáveis cadastradas no painel da Vercel **não são lidas automaticamente pelo
navegador**. Nesta etapa a configuração é explícita no arquivo; não há geração
automática por build. Todo seu conteúdo é público: nunca coloque segredos nele.
Uma interface HTTPS deve apontar para uma API HTTPS.

Uploads continuam usando FormData: o navegador define Content-Type e boundary.
Campos, arquivos e AbortSignal permanecem inalterados.

## Limites e validação

O funcionamento entre origens diferentes, mesmo em duas portas locais, permanece
bloqueado pela proteção existente. A arquitetura está preparada, mas não habilita
Vercel → Render. A etapa futura de autenticação/autorização deverá tratar isso
explicitamente antes de qualquer exposição pública. Não publicar esta versão.

Os testes de separação cobrem pasta ausente, interface local, configuração pública,
CORS autorizado/negado, bloqueios remotos, JSON e multipart. As suítes existentes
continuam cobrindo avaliações, correção, alunos, câmera simulada, OCR e revisão.
Testes de navegador exigem Playwright e Chrome disponíveis; testes de Firestore
integrado exigem emulador local. Nenhum desses testes autoriza acesso à produção.

Referência: [CORS no FastAPI](https://fastapi.tiangolo.com/tutorial/cors/).
