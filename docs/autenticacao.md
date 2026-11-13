# Autenticação e autorização — Etapa 08

> O modo `APP_AMBIENTE=producao` exige Firebase Authentication e `ADMIN_UIDS`.
> A Vercel exibe login; o modo `local_operacional` mantém acesso local sem login.

O frontend usa o Firebase Authentication Web SDK por módulos CDN fixados.
O backend usa o Firebase Admin SDK já instalado. Nenhuma dependência nova
ou framework frontend é necessário. Não foi configurado nem acessado um projeto
Firebase real durante a implementação.

## Política de acesso

Todas as rotas dos routers de correções e interface exigem Firebase ID Token e
UID explicitamente autorizado: avaliações, gabaritos, alunos, histórico, captura,
OCR, reconhecimento, recálculo e salvamento. `GET /api/auth/me` valida a sessão
administrativa antes de inicializar a interface.

`/`, `/api/health`, a documentação OpenAPI e os arquivos estáticos não exigem
token, mas continuam sujeitos a `ProtecaoLocal`. Não há dados de alunos nesses
endpoints de infraestrutura. Requisições remotas, Host externo, outra origem e
cabeçalhos de proxy continuam bloqueados, inclusive com token válido.

- Token ausente, inválido, expirado, revogado ou usuário desativado: HTTP 401.
- Token válido cujo UID não consta em `ADMIN_UIDS`: HTTP 403.
- Configuração ausente ou serviço Firebase indisponível: HTTP 503, sem detalhes privados.
- Lista administrativa vazia: nenhum usuário autorizado. `*` não é curinga.

Não há bypass de desenvolvimento, cadastro aberto, autorização por e-mail ou
autorização baseada em campos enviados pelo navegador. A lista de UIDs é a única
política administrativa. Todos os administradores autorizados acessam o mesmo
conjunto de registros; não há isolamento por professor/escola nesta etapa.

O SDK verifica assinatura, emissor, destinatário e expiração e recebe
`check_revoked=True`, verificando também revogação e usuário desativado. O app
Firebase de autenticação é independente do cliente Firestore e inicializa sob
demanda. Não se usa o emulador de autenticação: `FIREBASE_AUTH_EMULATOR_HOST`
configurado causa rejeição, evitando aceitar tokens sem assinatura por engano.

## Configuração pelo responsável pelo projeto

1. No Firebase Console, habilitar Authentication → Sign-in method → Email/Password.
2. Criar previamente as contas autorizadas em Authentication → Users. Não há
   formulário de cadastro ou recuperação de senha nesta interface.
3. Copiar os UIDs dessas contas para `ADMIN_UIDS` no ambiente do backend.
4. Configurar `FIREBASE_PROJECT_ID` com o projeto real que emite os tokens.
5. Configurar Application Default Credentials no backend; quando necessário,
   `GOOGLE_APPLICATION_CREDENTIALS` deve apontar para arquivo privado fora do
   repositório. A identidade precisa poder consultar usuários Firebase Auth para
   verificar revogação/desativação. Conceder apenas as permissões necessárias.
6. Em `Frontend/js/config.mjs`, preencher os quatro valores públicos
   `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_PROJECT_ID` e
   `FIREBASE_APP_ID` do mesmo projeto. Eles não concedem acesso
   administrativo. Nunca inserir conta de serviço, senha, ID Token ou refresh
   token nesse arquivo. Configurar restrições da chave compatíveis com Firebase
   Auth e Secure Token API e validar o login no domínio local usado.

Exemplo de variáveis de backend, com valores fictícios:

```powershell
$env:FIREBASE_PROJECT_ID = "seu-projeto"
$env:ADMIN_UIDS = "uid-administrador-1,uid-administrador-2"
```

Reiniciar o backend após mudar a configuração. Manter execução em
`127.0.0.1`, `--no-proxy-headers` e um único worker. `API_BASE_URL = ""` mantém
a interface local integrada. Para desenvolvimento, usar projeto Firebase de
desenvolvimento e contas próprias de teste; o modo emulador do Firestore pode
continuar independente dos testes simulados de autenticação. O projeto demo
usado pelo emulador não serve como projeto emissor de tokens reais; não misturar
essas configurações em uma execução integrada.

## Sessão no navegador

A tela de login aparece antes de carregar os fluxos de negócio. Após entrar no
Firebase, o frontend consulta `/api/auth/me`; somente um administrador autorizado
acessa a interface. A senha é limpa do formulário ao terminar a tentativa.

O SDK gerencia a persistência LOCAL, inclusive o refresh token. O aplicativo não
armazena tokens manualmente nem os coloca em URLs ou logs. Recarregar a página
restaura a sessão, mas exige nova autorização em `/api/auth/me`. Tokens próximos
de expirar são renovados pelo SDK.
Requisições protegidas recebem `Authorization: Bearer ...`; multipart preserva
o Content-Type/boundary gerado pelo navegador. Redirecionamentos da API não são
seguidos. Respostas 401/403 encerram a sessão, sem repetir gravações automaticamente.

O botão Sair limpa a sessão local e recarrega a página, eliminando dados em memória
e encerrando a câmera. Ele não revoga todas as sessões da conta no Firebase.
Revogação global/desativação deve ser feita pelo administrador do projeto.

## Validação e limites

Os testes de autenticação usam instâncias de FastAPI sem bypass e simulam somente
o Firebase Admin, sem credenciais ou conexão real. Os testes antigos de negócio
usam um override de dependência restrito à aplicação compartilhada dos testes,
permitindo verificar os fluxos existentes sem depender de contas reais. Esse
override não existe na execução normal da API.

Testes JavaScript simulam login, renovação, falhas, logout e envio de Bearer com
multipart. Os cenários antigos de navegador exigem Playwright, Chrome e adaptação
do setup para login autorizado; ainda não validam a autenticação real. Webcam
física e login com Firebase real precisam de homologação local antes de publicação.

O próximo trabalho deverá avaliar autenticação real, limites de requisições e
política de sessão, além do isolamento de dados se houver múltiplas escolas.
A liberação remota/proxy/CORS é uma etapa separada: **não publicar esta versão**.
`ProtecaoLocal` e `exigir_acesso_local()` continuam sem alterações.

Referências oficiais:
- [Firebase Authentication REST](https://firebase.google.com/docs/reference/rest/auth)
- [Verificação de ID Tokens](https://firebase.google.com/docs/auth/admin/verify-id-tokens)
