# Operação pública compartilhada sem login

`APP_AMBIENTE=publico_compartilhado` usa um único conjunto persistente de
`alunos`, `provas`, `gabaritos`, `correcoes`, `operacoes` e `nomes_alunos` no
Firestore **dedicado a este site**. Dois computadores veem os mesmos registros.
Não há Firebase Authentication, sessão de visitante ou prazo de exclusão
automática de 30/37 dias. Os registros só devem ser removidos por procedimento
administrativo deliberado, após conferência e backup. Não aplique políticas TTL
às coleções desse modo.
Dados eventualmente criados no antigo `publico_sessoes` permanecem em suas
subcoleções e **não são migrados nem exibidos automaticamente**; qualquer
migração requer inventário e autorização separados. Nenhum banco real foi
consultado durante esta implementação.

## Consequência do acesso aberto

**Qualquer pessoa que alcance a API pode consultar, cadastrar e alterar dados**
pelas operações disponíveis. Não há identidade de usuário, privacidade,
responsabilização individual ou proteção contra vandalismo. Não use dados
pessoais, sigilosos ou alunos reais sem aceitar e resolver esse risco por um
controle de acesso externo ou autenticação. CORS, Host, a URL da API e nomes
imprevisíveis de documentos não autenticam ninguém. Regras do Firestore que
negam acesso direto ao navegador também não restringem o Admin SDK no backend;
a conta de serviço precisa de IAM mínimo e ficar apenas na Render.

As operações de correção mantêm recálculo da nota no servidor, comprovante de
integridade e transações/idempotência por `operacao_id`. Reenviar a mesma
operação não cria outra correção. Quando a resposta é inconclusiva, o navegador
guarda o identificador da operação e deve consultar seu estado antes de reenviar.
Essa pendência local pode se perder ao limpar o navegador; a correção confirmada
continua consultável no histórico e na exportação compartilhados.

ZIPs e imagens enviados são temporários e **não** ficam no Firestore. A API
devolve uma credencial aleatória exclusiva do lote; manifesto, páginas e
cancelamento exigem `X-Lote-Token`. O navegador a preserva apenas para recuperar
o lote temporário após atualizar a página. Quem obtiver essa credencial pode
acessar as imagens do lote até ele expirar ou ser cancelado; não a registre em
logs/URLs. Reiniciar a Render apaga os ZIPs, mas não as correções confirmadas.
`/docs`, `/redoc`, `/openapi.json` e `/interface` ficam indisponíveis no serviço
Render. Nenhuma rota serve arquivos de credenciais ou documentos do repositório.

## Configuração manual

O `render.yaml` usa `main`, `APP_AMBIENTE=publico_compartilhado`, plano `1c-2g`,
um worker, `--no-proxy-headers`, `/api/health` e deploy automático desligado.
Antes de importar/sincronizar o Blueprint ou implantar, configure no serviço:

| Variável | Valor exigido |
| --- | --- |
| `APP_AMBIENTE` | `publico_compartilhado` |
| `FIRESTORE_MODO` | `real` |
| `SERVIR_FRONTEND` | `false` |
| `FIREBASE_PROJECT_ID` | ID do projeto Firestore exclusivo do site público |
| `FIREBASE_PRODUCTION_PROJECT_ID` | ID do projeto operacional anterior, diferente |
| `GOOGLE_APPLICATION_CREDENTIALS` | `/etc/secrets/firestore-publico.json` |
| `INTEGRIDADE_CHAVE` | chave aleatória estável de 32 bytes, 64 hexadecimais |
| `ALLOWED_HOSTS` | host exato da API Render, sem esquema nem porta |
| `CORS_ORIGINS` | origem HTTPS exata da Vercel, sem barra final |

Envie o JSON da conta de serviço **somente** como Secret File da Render com
nome `firestore-publico.json`. O backend compara o `project_id` desse arquivo
com `FIREBASE_PROJECT_ID` antes de iniciar. Não configure `ADMIN_UIDS`,
`PUBLIC_SESSION_KEY`, emuladores nem `FORWARDED_ALLOW_IPS=*`. Mantenha as chaves
privadas fora do Git e do frontend. O health check não testa IAM ou Firestore.

No projeto Firestore dedicado, configure regras Web/Mobile para negar leitura e
escrita direta. Conceda à conta de serviço somente o papel de leitura/escrita
de dados necessário, nunca Owner/Editor. Confirme os índices automáticos para
`alunos.nome_normalizado`, `correcoes.aluno_id`, `correcoes.aluno` e
`correcoes.prova_id`. O histórico paginado requer índice composto com escopo
**Collection** em `correcoes`: `aluno_id ASC`, `processada_em DESC`,
`__name__ ASC`. A necessidade exata de índices adicionais deve ser validada
com dados fictícios no projeto novo, antes de aceitar dados de operação.

Na Vercel, Root Directory `Frontend`, sem framework, instalação ou build. O
frontend usa a origem HTTPS configurada em `Frontend/js/config.mjs`; o domínio
final deve constar em `CORS_ORIGINS`. A câmera exige contexto seguro HTTPS.

## Limites e validação antes da abertura

Uploads individuais: 10 MiB, 12 milhões de pixels. ZIP público: 8 MiB
compactados, 20 imagens/páginas, 50 MiB descompactados, 10 páginas por PDF,
dois lotes temporários por processo. Há uma operação pesada simultânea,
18 processamentos, 6 gravações e 2 exportações por minuto no processo, além de
120 requisições por minuto para o modo compartilhado. São limites locais ao
processo, não defesa contra abuso distribuído. Monitore CPU, RAM, tráfego e
cobrança; o plano Free de 0,1 CPU/512 MiB não foi validado para OCR/ZIP.

Antes de abrir o site, faça piloto autorizado **somente com dados fictícios**:
cadastre uma avaliação com 50 respostas e um aluno no navegador A; confirme
que B consulta os mesmos dados; processe JPG/PNG/PDF, fotografe, importe ZIP
com PDF multipágina, revise antes de salvar, confira histórico, reenvio
idempotente, recuperação e CSV em ambos. Verifique que baixar imagem de ZIP
sem `X-Lote-Token` retorna 404. Reinicie o backend e confira que os registros
persistem e o ZIP temporário desaparece. Confirme os índices e a política de
backup/exportação antes de usar dados reais. Não há conexão real durante os
testes automatizados do repositório.
