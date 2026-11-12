# Frontend estático na Vercel — Etapa 11

Preparação sem deploy, sem configuração de conta Firebase e sem alterações no
backend. O frontend continua HTML/CSS/JavaScript, sem framework ou instalação.

## Configuração futura do projeto

| Campo | Valor |
| --- | --- |
| Root Directory | `Frontend` (respeitar maiúscula) |
| Framework Preset | `Other` |
| Build Command | Override habilitado, vazio — sem build |
| Install Command | Vazio — nenhuma dependência a instalar |
| Output Directory | `.` — raiz do projeto Frontend |

`Frontend/vercel.json` fixa os comandos vazios, saída estática e cabeçalhos de
revalidação/cache e segurança. Não existe configuração Vercel na raiz do
repositório. O Root Directory é selecionado no painel, não por `vercel.json`.
Desativar inclusão de arquivos fora da raiz no build. Não selecionar a raiz
inteira do repositório: Backend, docs e arquivos locais não são conteúdo público.

`.vercelignore` exclui testes, código legado vazio, caches de QA, dependências e
nomes comuns de arquivos privados. Isso não substitui a regra de nunca colocar
credenciais em `Frontend`. Todo arquivo distribuído ao navegador é público.

## API e Firebase Authentication

`Frontend/js/config.mjs` define a origem pública da API Render:

```javascript
export const API_BASE_URL = "https://corretor-gabaritos-8yal.onrender.com";
export const FIREBASE_API_KEY = "";
```

O endereço da API é público; a chave Web Firebase permanece vazia nesta etapa.
A URL contém somente a origem HTTPS, sem `/api`,
query, fragmento ou credenciais. `api.mjs` é o único ponto de resolução das chamadas
da aplicação. Com a URL pública fixa, até a interface executada localmente envia
as chamadas da API para a Render. Para usar o modo local integrado, configurar
explicitamente `API_BASE_URL = ""` neste arquivo antes de iniciar a interface local
e restaurar a URL pública antes de publicar o frontend. Uma página hospedada com
base vazia apresenta erro de configuração; vazio continua permitido para o modo
integrado em localhost/127.0.0.1/IPv6 local.
HTTP não é aceito como API de uma interface HTTPS.

Não há substituição automática por variáveis do painel da Vercel: a configuração
é o arquivo estático explícito. Alterar valores exige publicar uma nova versão
futuramente. Nenhuma credencial administrativa, senha, conta de serviço, token ou
chave de integridade pode ser colocada nesse arquivo. A chave Web Firebase é
pública e não concede autorização administrativa.

O login continua via API REST Firebase por e-mail/senha. O ID Token é enviado no
Authorization: Bearer ao backend e fica somente em memória, assim como o refresh
token. A permissão administrativa continua sendo decisão do backend. Não houve
acesso real ao Firebase nesta etapa.

## Páginas, caminhos e atualização

As telas são abas de `index.html`, com fragmentos carregados por `paginas.mjs`.
URLs canônicas:

- `/#avaliacoes`
- `/#correcao`
- `/#alunos`

Também funcionam em `/index.html#...` e no modo local `/interface/#...`.
Após atualizar, é necessário entrar novamente porque a sessão é apenas em memória;
depois do login, a aba indicada no hash é restaurada. Arquivos, captura e revisão
ainda não salvos não são persistidos por refresh. A navegação não cria rotas de
servidor e não precisa de rewrite catch-all. Caminhos `/avaliacoes` ou `/correcao`
não são URLs da aplicação; arquivos `pages/*.html` são templates internos, não
documentos completos para abrir diretamente.

HTML/CSS/fontes usam caminhos relativos; fragmentos são resolvidos relativamente
ao módulo por `import.meta.url`. Os testes conferem existência e capitalização
dos arquivos para Linux, imports e correspondência dos slots das três telas.
Não redirecionar toda URL para index.html: isso esconderia erros de assets/API.

## Uploads, câmera e indisponibilidade

PDF/JPG/PNG continuam em FormData, com Content-Type/boundary gerados pelo navegador.
Authorization é preservado e uploads seguem direto para a API, sem função/proxy
Vercel. Cancelamentos continuam como AbortError; não provocam reenvio automático.

Webcam continua via getUserMedia em HTTPS ou localhost, mediante permissão do
usuário. `Permissions-Policy` permite câmera somente na própria origem e não
habilita microfone. Abrir diretamente a aplicação, não em iframe de outra origem.
Os cabeçalhos preparados ainda precisam de validação real na Vercel.

Falha de rede mostra orientação de conexão; respostas 429/5xx sem JSON mostram
indisponibilidade temporária. Não há repetição automática de gravações. Após
falha de salvamento, conferir histórico ou reenviar a mesma operação mantendo
a página aberta, para preservar seu identificador idempotente. Indisponibilidade
503 não encerra a sessão. Respostas 401/403 encerram a sessão e retornam ao login.
Sem autenticação, mensagens 401/403 são exibidas no formulário de entrada.

## Validação e limites

Testes Node usam arquivos reais e serviços simulados, sem Firebase externo:
assets/imports/fontes, fragmentos/slots, hashes, configuração HTTPS, falhas de rede,
indisponibilidade HTML, cancelamento e sessão. As suítes anteriores cobrem câmera
simulada, OCR, revisão, Bearer e FormData. Isso não é homologação visual em um
navegador nem em uma distribuição Vercel real. Playwright permanece indisponível.

Antes de implantação: validar login real autorizado, webcam física, headers/MIME
dos módulos, revalidação de cache e CORS entre os domínios reais. O backend continua
local por padrão; nenhuma mudança desta etapa o torna público. Domínios de preview
Vercel não serão autorizados automaticamente: CORS exige origens explícitas.

Referências: [configuração de build](https://vercel.com/docs/builds/configure-a-build)
e [vercel.json](https://vercel.com/docs/project-configuration/vercel-json).
