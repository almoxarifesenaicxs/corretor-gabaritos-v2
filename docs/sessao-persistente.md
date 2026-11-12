# Infraestrutura de sessão persistente

`Frontend/js/auth.mjs` usa módulos oficiais do Firebase Web SDK 13.2.0 por URL
versionada do CDN. A autenticação por e-mail/senha usa `browserLocalPersistence`;
o próprio SDK gerencia a sessão, o ID Token e sua renovação. O código do projeto
não grava refresh tokens diretamente em `localStorage`.

`Frontend/js/config.mjs` precisa receber os valores **públicos** do aplicativo Web
Firebase: `FIREBASE_API_KEY`, `FIREBASE_AUTH_DOMAIN`, `FIREBASE_PROJECT_ID` e
`FIREBASE_APP_ID`. Eles permanecem vazios nesta etapa. Nunca inserir chave de
conta de serviço, token, senha ou segredo administrativo nesse arquivo público.

Contrato de `authSession`:

- `login(email, password)` autentica e devolve um ID Token.
- `restore()` aguarda o estado inicial do SDK e tenta renovar o token. Devolve
  `null` sem sessão ou um ID Token; **não confirma autorização administrativa**.
- `getToken()` devolve um token atualizado para o cabeçalho Bearer, ou `null` sem sessão.
- `getUid()` informa somente o UID atual; `observeIdentity()` observa entradas,
  saídas e trocas de conta propagadas pelo SDK entre abas.
- `logout()` devolve uma Promise de `boolean`: `true` somente após o SDK limpar a
  sessão persistida; o callback registrado em `onLogout()` roda então. Em falha,
  devolve `false` e mantém o acesso local bloqueado, sem alegar que a persistência
  foi removida.
- Erros expõem `reason`: `configuration`, `credentials`, `invalid-session`,
  `network`, `unavailable` ou `cancelled`. Mensagens não expõem respostas internas.

Ao iniciar, `login.mjs` mostra "Verificando sessão" e aguarda `restore()` com o
dashboard oculto. Uma sessão restaurada só libera a interface após resposta
bem-sucedida de `/api/auth/me` com Bearer. Sem sessão, apresenta o formulário.
Respostas 401 e 403 encerram a sessão e voltam ao login; falhas temporárias
de rede ou 503 mantêm a interface bloqueada e oferecem nova tentativa sem
apagar a sessão. `logout()` é aguardado antes de recarregar a página. Se a
limpeza da persistência falhar, a interface permanece bloqueada e permite
tentar novamente.
O backend continua responsável por validar assinatura, revogação e `ADMIN_UIDS`.

Depois da autorização inicial, a interface observa mudanças de identidade pelo
Firebase SDK. Logout ou troca de conta em outra aba bloqueiam imediatamente a
interface, descartam dados de alunos, avaliações, captura e revisão carregados,
interrompem a câmera e recarregam a página. A nova identidade nunca herda a
autorização da conta anterior: o UID do SDK precisa coincidir com o UID retornado
por `/api/auth/me`. Uma barreira local impede novas chamadas administrativas e
descarta respostas antigas quando a autorização fica pendente ou é encerrada;
o backend continua sendo a barreira de segurança efetiva.

Ao voltar para uma aba oculta ou janela inativa, e a cada cinco minutos enquanto
a página permanece visível, o dashboard é ocultado e `/api/auth/me` é consultado
novamente com token atualizado. Revalidações concorrentes são agrupadas. Erros
401/403 encerram a sessão; indisponibilidade de rede ou 503 mantém a sessão
Firebase e oferece nova tentativa com o dashboard bloqueado. Uma operação já
recebida pelo servidor antes do bloqueio pode terminar lá; a interface descarta
o resultado tardio, mas não presume que uma gravação foi desfeita.
Uma revogação feita no servidor pode levar até a próxima revalidação periódica
para ocultar dados já exibidos em uma aba continuamente ativa. Novas requisições
continuam sujeitas à validação do backend em cada chamada.

Em computadores compartilhados, a persistência LOCAL mantém a sessão após fechar
o navegador. Usuários devem sair explicitamente; políticas de dispositivo e
proteção contra scripts injetados continuam relevantes. A autenticação persistida
fica restrita à origem do site e não é prova de permissão administrativa.

Os testes usam SDK e respostas de API sintéticos; os testes de navegador
interceptam os módulos do CDN e não fazem chamadas ao Firebase real. O modo
`homologacao` do backend continua aceitando remotamente apenas `GET /api/health`.
