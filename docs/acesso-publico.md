# Acesso sem login

O frontend abre diretamente em Avaliações, Correção e Alunos. Ele não carrega o
Firebase Authentication nem envia `Authorization`. `Frontend/js/config.mjs` contém
somente a origem HTTPS da API. A API continua em `homologacao` na configuração
preparada da Render: nesse modo, apenas `GET /api/health` funciona remotamente.

Para habilitar os fluxos de forma deliberada, o backend oferece
`APP_AMBIENTE=publico`. Esse modo exige `FIRESTORE_MODO=real`,
`FIREBASE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS` (caminho de Secret File),
`INTEGRIDADE_CHAVE`, `ALLOWED_HOSTS`, `CORS_ORIGINS` HTTPS e
`SERVIR_FRONTEND=false`. Valores ausentes ou malformados impedem a inicialização;
a validade e as permissões da credencial Firestore só são comprovadas ao consultar
o banco.
Manter o comando Uvicorn com `--no-proxy-headers` e sem
`FORWARDED_ALLOW_IPS=*`. O arquivo `render.yaml` não ativa esse modo.

**Consequência:** qualquer cliente capaz de alcançar a API pública poderá consultar
nomes e históricos de alunos, criar avaliações, processar cartões e salvar
correções sem identidade individual. `Host` e `Origin` limitam tráfego esperado,
mas não autenticam pessoas; clientes fora do navegador podem forjar esses
cabeçalhos. Os limites de tamanho, pixels, concorrência e integridade existentes
continuam ativos, mas não substituem controle de acesso nem limite de taxa por
usuário. Avaliar exposição de dados pessoais, retenção, abuso e custos antes de
ativar `publico` com dados reais.

Para desenvolvimento integrado sem login, usar `APP_AMBIENTE=local_publico`,
`FIRESTORE_MODO=emulador`, `FIRESTORE_EMULATOR_HOST` local e projeto `demo-*`.
Esse modo mantém a barreira de loopback, Host e Origin do modo local. Configurar
`API_BASE_URL = ""` no frontend local. O modo `local` anterior continua exigindo
autenticação; `homologacao` expõe apenas saúde; `producao` continua exigindo
Firebase Authentication e `ADMIN_UIDS`. A configuração de Firestore real não possui
fallback para emulador. Testes usam persistência simulada e nunca conectam ao
Firestore real.
