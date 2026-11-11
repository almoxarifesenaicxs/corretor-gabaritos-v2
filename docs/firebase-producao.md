# Firebase para produção — preparação

Esta etapa não configura serviços reais nem ativa produção. O padrão continua
`APP_AMBIENTE=local` e `FIRESTORE_MODO=emulador`. As configurações abaixo são para
uma implantação futura autorizada. Console, permissões IAM, regras e dados reais
não foram consultados ou validados.

## Authentication

No projeto Firebase escolhido, habilitar o provedor e-mail/senha e criar as contas
administrativas. Registrar seus UIDs na variável privada de servidor `ADMIN_UIDS`,
separados por vírgulas, sem curingas. E-mail, domínio e claims enviados pelo
cliente não concedem autorização. Todos os administradores permitidos têm acesso
aos dados da aplicação; não existe isolamento por escola ou usuário.

O frontend usa a API REST `signInWithPassword` e a renovação de tokens. Para esse
fluxo, a única configuração Firebase necessária no navegador é `FIREBASE_API_KEY`,
a chave Web pública do mesmo projeto. Não são necessários `authDomain`, `appId`
ou credenciais Admin. Não há cadastro na interface; isso não significa que a
criação de contas esteja desabilitada no serviço. Contas fora de `ADMIN_UIDS`
continuam sem acesso ao backend.

O ID Token segue em `Authorization: Bearer`. O Admin SDK verifica assinatura,
projeto destinatário, emissor e validade, com `check_revoked=True` para verificar
revogação e usuário desativado. A instância reutilizada deve pertencer ao projeto
configurado. Token ausente/inválido retorna 401; UID não autorizado, 403; falha
de configuração ou indisponibilidade do serviço, 503, sem detalhes privados.
A verificação de revogação requer acesso de rede e permissões de consulta de
usuários no Authentication. Reiniciar o serviço após mudar projeto ou credenciais.

## Firestore e credenciais na Render

Provisionar futuramente o Cloud Firestore em modo Native, banco `(default)` do
mesmo projeto. Escolher região e política de backup/retensão antes de inserir
dados. A aplicação não seleciona outro ID de banco. Validar índices necessários
com dados sintéticos antes do uso real.

Usar uma conta de serviço com privilégios mínimos para as operações necessárias
no Firestore e para a verificação de usuários no Authentication. Não conceder
Owner/Editor por conveniência. O Admin SDK usa IAM e **ignora as regras de
segurança do Firestore**; revisar IAM é indispensável. Como o navegador não acessa
Firestore diretamente, suas regras devem negar acesso de clientes Web/mobile.
Não publicar regras permissivas de teste. Nenhuma regra foi aplicada nesta etapa.

Na Render, disponibilizar o JSON privado como Secret File e definir
`GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/<nome-do-arquivo>` conforme o caminho
efetivamente montado. O SDK utiliza Application Default Credentials. A variável
contém o **caminho**, não o JSON: o projeto não interpreta JSON inline em variável
de ambiente. A inicialização de produção exige arquivo existente e credencial
carregável. Isso não comprova permissões IAM ou disponibilidade do serviço.
Nunca colocar esse arquivo no Git, na imagem pública ou na Vercel.

| Variável do backend | Configuração futura |
| --- | --- |
| `APP_AMBIENTE` | `producao`, somente na ativação autorizada |
| `FIRESTORE_MODO` | `real`, escolha explícita; não existe fallback automático |
| `FIREBASE_PROJECT_ID` | ID exato do projeto, sem espaços e sem prefixo `demo-` |
| `GOOGLE_APPLICATION_CREDENTIALS` | Caminho do Secret File privado |
| `ADMIN_UIDS` | Lista explícita de administradores |
| `CORS_ORIGINS` | Origens HTTPS exatas do frontend, separadas por vírgulas |
| `ALLOWED_HOSTS` | Hosts exatos da API, sem esquema, porta ou curinga |
| `INTEGRIDADE_CHAVE` | Segredo aleatório persistente de 32 bytes em hexadecimal |
| `SERVIR_FRONTEND` | `false` |

Não definir `FIRESTORE_EMULATOR_HOST` nem `FIREBASE_AUTH_EMULATOR_HOST` em produção.
Manter o comando Render com `--no-proxy-headers` e um worker; não configurar
`FORWARDED_ALLOW_IPS=*`. Preservar a chave de integridade entre reinícios; mudanças
podem invalidar revisões pendentes. Ver também [backend Render](render-backend.md).
Falhas de Firestore são convertidas em erros seguros pelas rotas, sem migrar
silenciosamente para outro banco. O contexto fecha cliente e aplicação Firebase.
`/api/health` não consulta Firebase e não comprova prontidão de IAM ou banco.

## Frontend na Vercel

Usar `Frontend` como Root Directory. Em `Frontend/js/config.mjs`, configurar
`API_BASE_URL` com a origem HTTPS da API Render e `FIREBASE_API_KEY` com a chave
Web pública. São valores entregues ao navegador; variáveis da Vercel não são
injetadas automaticamente nesses arquivos estáticos. Não inserir conta de
serviço, chave privada, tokens ou `INTEGRIDADE_CHAVE` no frontend.

A chave Web identifica o projeto e não substitui autenticação/autorização.
Revisar suas restrições de APIs e de origem conforme o suporte dos endpoints
Identity Toolkit e Secure Token; validar login e renovação antes de restringir.
Tokens ficam em memória, sem armazenamento persistente. Atualizar a página exige
novo login. Falhas de conexão são tratadas, 401/403 encerram a sessão e respostas
503 não apagam automaticamente uma sessão válida. Ver [Vercel](vercel-frontend.md).

## Testes seguros

Os testes unitários substituem a verificação de identidade e a persistência por
mocks. A suíte bloqueia ADC e validação real de tokens por padrão e protege os
clientes Firestore síncronos e assíncronos. `conectar_firestore(emulador=False)`
é bloqueado em processos Pytest, antes de carregar credenciais.

Para testes de integração opcionais, iniciar apenas o emulador Firestore local
com projeto `demo-corretor-local` e definir no processo de testes:

```text
APP_AMBIENTE=local
FIRESTORE_MODO=emulador
FIREBASE_PROJECT_ID=demo-corretor-local
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080
```

Remover `GOOGLE_APPLICATION_CREDENTIALS` desse processo. O host deve ser loopback,
com porta e sem esquema; o projeto deve começar com `demo-`. Executar no diretório
Backend `python -B -m pytest -q -p no:cacheprovider`; na raiz,
`node --test Frontend/tests/*.test.mjs`. Sem emulador configurado, a integração é
ignorada. Os testes usam dados sintéticos e limpam seus próprios registros.

O emulador Authentication **não é aceito** pela aplicação: tokens sem assinatura
continuam bloqueados. Os testes de autorização usam mocks explícitos; não apontar
o login do navegador para um projeto real para testar o emulador Firestore.
Não executar scripts privados de ambiente real durante os testes.

## Dados de alunos e pendências

Limitar acesso a nomes, notas e avaliações; evitar dados pessoais em logs,
capturas, fixtures e relatórios públicos. Definir responsáveis, retenção, exclusão,
backups e procedimento de restauração antes de usar dados reais. Rotacionar
credenciais expostas e revogar sessões quando necessário. Remover um UID da lista
e reiniciar o backend retira sua autorização independentemente do login.

Permanecem pendentes a validação autorizada de IAM, regras, índices, cotas,
restrições da chave Web, conectividade e recuperação de backups. Testes com mocks
não comprovam essas propriedades em produção. Nenhuma credencial foi gerada e
nenhuma conexão com Firebase real é necessária para esta etapa.

Referências: [Admin SDK](https://firebase.google.com/docs/admin/setup),
[validação de tokens](https://firebase.google.com/docs/reference/admin/python/firebase_admin.auth),
[API REST de autenticação](https://firebase.google.com/docs/reference/rest/auth),
[regras e acesso de servidor](https://firebase.google.com/docs/firestore/security/rules-conditions),
[emulador Firestore](https://firebase.google.com/docs/emulator-suite/connect_firestore),
[Secret Files Render](https://render.com/docs/configure-environment-variables).
