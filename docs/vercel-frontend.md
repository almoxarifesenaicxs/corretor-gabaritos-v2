# Frontend estático na Vercel

O frontend é HTML, CSS e JavaScript sem build. Na Vercel, o dashboard só abre
após login Firebase e confirmação de `/api/auth/me` pelo backend.
As abas Avaliações, Correção e Alunos usam hashes (`/#avaliacoes`, `/#correcao`,
`/#alunos`), inclusive após atualizar a página. O SDK restaura a sessão LOCAL,
mas o backend precisa autorizar o UID em toda visita e requisição.

| Configuração Vercel | Valor |
| --- | --- |
| Root Directory | `Frontend` |
| Framework Preset | `Other` |
| Build Command / Install Command | Vazios |
| Output Directory | `.` |

`Frontend/vercel.json` contém a configuração estática e cabeçalhos da câmera.
`Frontend/.vercelignore` exclui testes e nomes comuns de arquivos privados.
Não adicionar segredos em `Frontend`: todos os arquivos publicados são públicos.

`Frontend/js/config.mjs` define `API_BASE_URL`, com a origem HTTPS da
Render, sem `/api`, caminho, query ou credenciais. Também contém apenas os valores
públicos do aplicativo Web Firebase: `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`,
`FIREBASE_PROJECT_ID` e `FIREBASE_APP_ID`. Senhas e contas de serviço nunca entram
nesse arquivo. `api.mjs` acrescenta os caminhos
`/api/...`. Como o frontend é estático, alterar essa origem exige publicar nova
versão. Em `localhost` ou `127.0.0.1`, a configuração usa a API da mesma origem;
o backend `local_operacional` entrega uma configuração local sem Firebase Auth.
O navegador não injeta variáveis da Vercel em tempo de execução.

PDF/JPG/PNG continuam usando `FormData`; o navegador define o boundary. A webcam
exige HTTPS ou localhost e permissão do usuário. Falhas de rede e 503 mostram
mensagem sem repetir gravações automaticamente. Respostas 401/403 encerram a
sessão e bloqueiam o dashboard. JSON e multipart enviam ID Token em Bearer.

O backend preparado na Render permanece em `homologacao`, que aceita apenas
`GET /api/health`. Para operar remotamente com dados reais, configurar e validar
`APP_AMBIENTE=producao` conforme [login administrativo](login-administrativo.md).
Nenhum deploy ou mudança de configuração da Render é realizado por este código.
