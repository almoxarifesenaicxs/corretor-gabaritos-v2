# Login administrativo para Vercel e Render

O dashboard hospedado permanece oculto até o Firebase Authentication restaurar ou
criar uma sessão e `GET /api/auth/me` confirmar o UID autorizado. Cada chamada à
API, incluindo upload ZIP, páginas do lote, exportação, histórico, recuperação e
salvamento, envia o ID Token em `Authorization: Bearer`. O backend verifica assinatura,
projeto, expiração, revogação e `ADMIN_UIDS`. A presença do token sozinha não autoriza.

## Cadastro manual da única administradora

1. No Firebase Console do projeto correto, habilitar **Authentication > Sign-in method > Email/Password**.
2. Em **Authentication > Users**, adicionar manualmente a conta com e-mail e senha forte. Não criar usuários pelo aplicativo.
3. Copiar o **UID** exibido na lista de usuários para `ADMIN_UIDS` na Render. Não usar o e-mail como permissão.
4. Em **Authentication > Settings > Authorized domains**, incluir o domínio exato da Vercel.

Não colocar senha, chave de conta de serviço ou token no Git, frontend ou variáveis
públicas da Vercel. Em computador compartilhado, usar **Sair** ao terminar e evitar
salvar a senha no navegador. A persistência LOCAL do SDK mantém a sessão até logout
ou invalidação, mas não substitui a autorização do backend.

## Configuração pública do frontend

Em `Frontend/js/config.mjs`, preencher somente `FIREBASE_API_KEY`,
`FIREBASE_AUTH_DOMAIN`, `FIREBASE_PROJECT_ID` e `FIREBASE_APP_ID` com os valores
do **aplicativo Web** do mesmo projeto Firebase. Esses identificadores são públicos.
`API_BASE_URL` deve ser a origem HTTPS da Render, sem `/api`. Como o site é estático,
essa configuração exige nova publicação do frontend; variáveis da Vercel não são
lidas em tempo de execução pelo navegador.

## Configuração privada da Render

Manter `APP_AMBIENTE=homologacao` enquanto a configuração real não estiver pronta:
nesse modo, somente `GET /api/health` está remoto. Antes de mudar manualmente para
`producao`, configurar e validar `FIRESTORE_MODO=real`, `FIREBASE_PROJECT_ID`,
`ADMIN_UIDS`, `GOOGLE_APPLICATION_CREDENTIALS` apontando para arquivo secreto
montado na Render, `INTEGRIDADE_CHAVE` (32 bytes aleatórios em hexadecimal),
`ALLOWED_HOSTS` com o host exato da Render, `CORS_ORIGINS` com a origem HTTPS exata
da Vercel e `SERVIR_FRONTEND=false`. Não usar `FORWARDED_ALLOW_IPS=*` e manter
`--no-proxy-headers`, um worker e limite de upload do ZIP em 32 MiB úteis.

O modo `local_operacional` continua sem login e restrito ao loopback; nunca deve ser
usado na Render. O modo `publico` continua sendo anônimo e **não deve ser ativado**
com dados reais. CORS e Host complementam a proteção, mas não são autenticação.

## Validação antes do deploy funcional

Testar em ambiente isolado: 401 sem token e com token inválido/revogado; 403 para
UID não listado; 200 para UID autorizado; logout e restauração; ZIP, exportação e
recuperação com Bearer; CORS da origem exata; upload ZIP acima do limite; e falhas
de conexão sem confirmação falsa de salvamento. Os testes automatizados usam mocks,
não um projeto Firebase real. Confirmar manualmente o funcionamento com conta de
teste e dados fictícios antes de usar dados de alunos.
