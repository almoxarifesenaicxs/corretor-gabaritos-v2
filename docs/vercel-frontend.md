# Frontend estático na Vercel

O frontend é HTML, CSS e JavaScript sem build. Na configuração pública atual,
o dashboard abre sem login e usa os registros compartilhados do modo
[`publico_compartilhado`](publico-compartilhado.md) na Render.
As abas Avaliações, Correção e Alunos usam hashes (`/#avaliacoes`, `/#correcao`,
`/#alunos`), inclusive após atualizar a página.

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
Render, sem `/api`, caminho, query ou credenciais. Os campos públicos Firebase
estão vazios no modo atual; senhas e contas de serviço nunca entram nesse
arquivo. `api.mjs` acrescenta os caminhos
`/api/...`. Como o frontend é estático, alterar essa origem exige publicar nova
versão. Em `localhost` ou `127.0.0.1`, a configuração usa a API da mesma origem;
o backend `local_operacional` entrega uma configuração local sem Firebase Auth.
O navegador não injeta variáveis da Vercel em tempo de execução.

PDF/JPG/PNG continuam usando `FormData`; o navegador define o boundary. ZIPs
usam uma credencial temporária de lote no cabeçalho `X-Lote-Token` para baixar
imagens, sem autenticar o acesso aos registros compartilhados. A webcam exige
HTTPS ou localhost e permissão do usuário. Falhas de rede e 503 mostram
mensagem sem repetir gravações automaticamente.

O `render.yaml` está preparado para `publico_compartilhado`, com deploy
automático desligado. A configuração manual e o piloto com dados fictícios
estão descritos em [operação pública compartilhada](publico-compartilhado.md).
Nenhum deploy ou mudança externa é realizado por este código.
