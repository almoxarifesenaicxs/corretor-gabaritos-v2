# Modos local e produção — Etapa 09

Esta etapa prepara o backend; não realiza implantação e não ativa produção por
padrão. As restrições remotas descritas nas etapas 07/08 continuam valendo no modo
local. `APP_AMBIENTE` ausente significa `local`; valores desconhecidos falham.

## Modo local

`APP_AMBIENTE=local` preserva IP de loopback, Host local, origem igual à API e
rejeição de cabeçalhos de proxy. Autenticação e autorização continuam obrigatórias
nas rotas administrativas. A função `exigir_acesso_local()` não foi alterada e
continua protegendo a abertura do Firestore real nesse modo.

## Modo produção

Somente `APP_AMBIENTE=producao` habilita a política remota. A aplicação valida as
configurações antes de iniciar; não há fallback para local nem para emuladores.

| Configuração | Exigência |
| --- | --- |
| `FIREBASE_PROJECT_ID` | Projeto explícito, não demo |
| `FIRESTORE_MODO` | `real` |
| `ADMIN_UIDS` | Lista não vazia de UIDs exatos; sem curingas |
| `CORS_ORIGINS` | Lista não vazia de origens HTTPS exatas, sem caminhos/curingas |
| `ALLOWED_HOSTS` | Hosts exatos do backend, separados por vírgula, sem protocolo ou porta |
| `GOOGLE_APPLICATION_CREDENTIALS` | Caminho de arquivo privado existente e carregável pelo SDK Admin |
| `INTEGRIDADE_CHAVE` | Segredo aleatório de 32 bytes, representado por 64 caracteres hexadecimais |
| `SERVIR_FRONTEND` | `false` (também padrão em produção) |

`FIRESTORE_EMULATOR_HOST` e `FIREBASE_AUTH_EMULATOR_HOST` não podem estar ativos.
`FORWARDED_ALLOW_IPS=*` é rejeitado. Credenciais e chave de integridade ficam
exclusivamente no ambiente privado do backend, nunca no frontend ou repositório.
Gerar a chave com um gerador criptográfico e mantê-la estável entre reinicializações
e instâncias. Não usar valores de exemplo dos testes. A checagem de formato não
comprova a aleatoriedade do segredo. Trocar a chave invalida comprovantes ainda
não salvos; operações já gravadas continuam idempotentes.

O carregamento das credenciais não confirma permissões IAM, habilitação de APIs,
existência da base ou conectividade. Essas condições ainda exigem homologação.
Configurações são de processo: reiniciar o serviço após mudanças; não hospedar
aplicações de ambientes/projetos diferentes no mesmo processo Python.

## Ordem das proteções

1. Rejeitar cabeçalhos ambíguos, Host não permitido e Origin não autorizado.
2. Ignorar/remover `Forwarded` e todos os `X-Forwarded-*` antes das rotas.
3. Validar ID Token e UID administrativo antes de receber o corpo dos uploads.
4. Aplicar os mesmos limites de corpo, tempo de recepção e concorrência.
5. Executar CORS e a rota; a dependência reaproveita a identidade já verificada.

Não se decide autorização por IP encaminhado, protocolo encaminhado ou alegações
do cliente. A marca de autorização é interna ao scope ASGI, não um cabeçalho.
A abertura do Firestore em produção exige essa marca e o modo real; a função de
persistência e o motor de correção permanecem inalterados.

Toda requisição em produção exige autorização, inclusive novas rotas, exceto:
- GET/HEAD de `/` e `/api/health`, sem dados administrativos;
- preflight OPTIONS com Origin autorizado, tratado pelo CORS sem executar operação.

Documentação Swagger/ReDoc/OpenAPI e interface estática não são servidas em
produção. Requisições sem Origin são aceitas apenas se o Host for permitido e a
autorização válida (salvo saúde). CORS não é autenticação. Erros 401/403 e limites
retornam cabeçalhos CORS somente à origem permitida. As respostas não revelam
credenciais nem detalhes internos.

## Proxy Render — contrato para a futura execução

A Render termina TLS no proxy e encaminha HTTP ao serviço; a porta interna não
é exposta diretamente à internet. Por isso o backend não exige que o scope tenha
`scheme=https` e não interpreta `X-Forwarded-Proto`. HTTPS externo é responsabilidade
da borda Render. Não usar esta política com porta HTTP diretamente exposta fora
desse ambiente.

O futuro comando deve manter **`--no-proxy-headers`**. Não configurar confiança
global em proxies nem usar `--forwarded-allow-ips '*'`. Exemplo para referência
somente, não executado nesta etapa:

```sh
uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --no-proxy-headers --workers 1
```

Usar o Host público real do serviço em `ALLOWED_HOSTS`; verificar o Host do health
check na homologação. Não adicionar curingas para contornar falhas. Nenhum header
encaminhado pode substituir um Host rejeitado. Clientes da biblioteca HTTP devem
usar diretamente URLs canônicas (sem depender de redirects gerados pelo backend).

Referência: [serviços web e TLS na Render](https://render.com/docs/web-services).

## Validação e riscos restantes

Testes simulam modo produção, autenticação, permissões, headers manipulados,
CORS, startup inválido, Firestore autorizado, limites e chave persistente, sem
credenciais reais. As suítes anteriores preservam regressões de integridade,
idempotência, leitura de imagens, notas e funcionamento local.

Ainda é necessário validar Firebase real, HTTPS/Host do proxy, health check,
login no navegador, consumo de CPU/memória e políticas operacionais. Não há rate
limit distribuído por usuário/IP; semáforos continuam por processo. A verificação
Firebase pode gerar consultas antes da recepção do corpo. Manter inicialmente um
worker e dimensionar/limitar tráfego antes de publicar. Todos os administradores
continuam compartilhando os mesmos dados, sem isolamento por escola.

Nenhuma configuração de produção foi ativada no projeto e nenhum deploy foi feito.
