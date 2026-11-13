# Contrato técnico: `APP_AMBIENTE=publico_demo`

**Estado:** especificação para implementação futura. Este documento não ativa o modo nem autoriza seu uso com dados reais. O frontend continua abrindo diretamente no dashboard, sem formulário de login ou Firebase Authentication no navegador.

## Fronteira do modo

`publico_demo` deve ser um sexto modo, selecionado explicitamente. Ele não herda a persistência nem a autorização de `local`, `local_publico`, `homologacao`, `producao` ou `publico`; o comportamento desses cinco modos não muda. O padrão continua `local` e o Blueprint da Render continua em `homologacao` até uma decisão posterior.

O modo demo usa somente um repositório efêmero, dentro do processo da API, para avaliações, gabaritos, alunos e correções fictícios. A escolha desse repositório ocorre antes de qualquer tentativa de selecionar Firestore. Nenhuma rota demo, inclusive saúde e processamento de arquivos, deve inicializar Firebase Admin, validar ID Token, abrir cliente Firestore, usar emulador ou carregar credenciais Google. Não basta apontar `Persistencia` para outra configuração: seus métodos fazem consultas e transações Firestore e a gravação verificada recalcula a nota, confere o comprovante, resolve homônimos e reutiliza `operacao_id`. O adaptador demo precisa manter o contrato de resposta e essas invariantes sem chamar Firestore. Não alterar o motor de correção.

Na inicialização, a presença de `FIRESTORE_MODO=real`, `GOOGLE_APPLICATION_CREDENTIALS`, `GOOGLE_CLOUD_PROJECT`, `GCLOUD_PROJECT`, `FIREBASE_PROJECT_ID`, `FIREBASE_CONFIG`, `ADMIN_UIDS`, `INTEGRIDADE_CHAVE` ou outras variáveis/arquivos de credenciais Firebase configurados para esse processo deve causar falha fechada, com erro sem valores secretos. Valores `FIRESTORE_EMULATOR_HOST` e `FIREBASE_AUTH_EMULATOR_HOST` também são incompatíveis com o modo: ele não usa sequer o emulador. A verificação no carregamento é complementar à separação estrutural das dependências. A assinatura de resultados, se necessária, usa chave aleatória efêmera exclusiva do processo demo. Não aceitar fallback para `publico`, `producao` ou Firestore quando o armazenamento temporário estiver indisponível. O deploy demo deve ter ambiente e serviço próprios, sem Secret File ou conta de serviço Firebase.

Somente `GET /api/health` e a criação da sessão demo dispensam identificador. O health check não consulta armazenamento ou Firebase. Documentação automática (`/docs`, `/redoc`, `/openapi.json`) e a interface servida pelo backend permanecem desativadas remotamente. `ALLOWED_HOSTS` exatos, `CORS_ORIGINS` HTTPS explícitas, `SERVIR_FRONTEND=false` e `--no-proxy-headers` são exigidos; `Host`, `Origin` e CORS não são autenticação nem autorização. Cabeçalhos `Forwarded`/`X-Forwarded-*` não concedem acesso ou identidade. O frontend estático continua na Vercel e usa a origem HTTPS da Render em `config.mjs`, sem acrescentar `/api` à URL-base.

## Sessão e isolamento

1. `POST /api/demo/sessoes` cria uma sessão vazia e retorna um identificador opaco gerado **no servidor** por gerador criptográfico, com pelo menos 256 bits de entropia (por exemplo, 32 bytes em base64url), além de `expires_at` e `idle_expires_at`. Resposta `201`, `Cache-Control: no-store` e sem dados de outras sessões. Limitar também a criação dessa sessão; uma sessão nova não pode zerar os limites globais ou por origem de rede.
2. O frontend mantém o identificador somente na memória da aba e o envia em `X-Demo-Session` para todas as rotas demo de negócio, incluindo uploads, OCR, consultas e gravações. Nunca o incluir em URL, hash, cookie, `localStorage`, `sessionStorage`, analytics, mensagens ou logs. `api.mjs` é o ponto único de envio. O CORS permite explicitamente esse cabeçalho e a origem Vercel autorizada, incluindo o preflight. Não usar `Authorization` para evitar confundir a capacidade demo com Firebase ID Token.
3. Na primeira visita, o dashboard pode aparecer imediatamente; os controles que consultam ou gravam dados esperam a criação da sessão. Se a criação falhar, mostrar indisponibilidade, sem formulário de login. Atualização/fechamento da aba cria sessão nova e perde os registros anteriores. Uma sessão demo **não autentica uma pessoa** e não deve proteger dados sensíveis: qualquer portador do identificador pode usá-la.
4. O backend guarda apenas um resumo criptográfico do identificador como chave, com estado independente por sessão. Toda consulta usa exclusivamente o repositório daquela sessão; IDs de avaliação/aluno/correção não podem recuperar registros de outra sessão, mesmo quando forem conhecidos. Listagens, busca de homônimos, gabaritos, histórico, comprovantes e chaves de idempotência pertencem ao mesmo escopo.
5. Inatividade e prazo absoluto são medidos por relógio monotônico no processo. Requisições válidas concluídas podem renovar somente o prazo de inatividade; nunca prorrogam o prazo absoluto. Expiração, remoção voluntária ou reinício descartam todo o estado. Ao receber `410`, o frontend limpa o identificador e qualquer dado de sessão em memória/DOM e oferece iniciar outra demonstração; não reenvia automaticamente uma gravação antiga à sessão nova.
6. A sessão deve ter serialização/lock por sessão para operações de escrita, com reservas atômicas das cotas. Conferir a sessão antes e depois de trabalho assíncrono; uma resposta tardia não grava em sessão expirada ou substituída. `operacao_id` repetido com o mesmo conteúdo devolve o resultado anterior; com conteúdo diferente retorna `409`. Não criar aluno/correção parcialmente quando a operação falha.

Essa separação reduz acesso cruzado acidental, mas não prova identidade. XSS, vazamento do identificador, compartilhamento da aba ou acesso físico ao computador permitem ler a sessão; por isso **somente dados fictícios**. Não prometer isolamento de pessoas sem uma barreira de identidade.

## Endpoints e dados

Todas as rotas de negócio já presentes dependem de uma sessão demo válida:

| Grupo | Rotas | Estado temporário |
| --- | --- | --- |
| Avaliações | `GET/POST /api/avaliacoes`; `GET /api/avaliacoes/{prova_id}/gabarito`; `POST /api/gabaritos/reconhecer` | Avaliação e gabarito; imagem nunca armazenada. |
| Alunos | `GET /api/alunos`; `GET /api/alunos/correspondencias`; `GET /api/alunos/{aluno_id}/correcoes`; `POST /api/alunos/reconhecer-nome` | Nomes e histórico fictícios da sessão; imagem nunca armazenada. |
| Correção e câmera | `POST /api/correcoes/processar`; `POST /api/correcoes/recalcular`; `POST /api/correcoes/salvar`; `POST /api/capturas/analisar` | Apenas resultado confirmado e respostas necessárias ao histórico. Frames, PDF/JPG/PNG e imagens de revisão não entram no repositório. |

O reconhecimento, a análise da captura, o recálculo e a revisão visual podem operar sem persistência, mas continuam exigindo sessão para aplicar cotas e evitar uma rota anônima sem orçamento. Avaliações, lista de alunos, consulta de gabarito e histórico precisam do repositório temporário para preservar o fluxo atual. Dados fictícios pré-carregados, se houver, devem ser copiados para cada sessão e nunca compartilhados por referência. Imagens e uploads podem existir apenas durante a requisição em memória/arquivo temporário, removido em sucesso, erro, cancelamento e expiração; não registrar conteúdo, nomes extraídos nem payloads em logs. `Cache-Control: no-store` nas respostas com dados da sessão.

## Limites configuráveis

Valores abaixo são **proposta inicial para validação**, não garantias de capacidade. Configuração por variáveis `DEMO_*` validadas na inicialização, com teto de segurança no código: valores ausentes usam os padrões; zero, negativo, não inteiro ou acima do teto falha fechado. Alterar limites exige repetir ensaios de memória e carga. A coluna Free é deliberadamente menor nos limites de armazenamento.

| Limite | Proposta Free | Teto inicial para outro plano | Observação |
| --- | ---: | ---: | --- |
| Inatividade | 30 min | 30 min | Não ultrapassar o prazo absoluto. |
| Vida absoluta | 2 h | 2 h | Reinício pode encerrar antes. |
| Avaliações / sessão | 5 | 10 | Inclui gabaritos. |
| Alunos / sessão | 10 | 30 | Somente cadastros fictícios. |
| Correções / sessão | 20 | 100 | Inclui registros de idempotência. |
| Sessões ativas / processo | 4 | 16 | Ao atingir o máximo, nova sessão recebe `503`; não expulsar sessão ativa para liberar vaga. |
| Estado serializado / sessão | 1 MiB | 4 MiB | Exclui imagens porque imagens não são armazenadas; rejeitar a mutação antes de ultrapassar o limite. |
| Estado total / processo | 4 MiB | 64 MiB | Soma dos estados das sessões; considerar overhead Python na medição. |
| Arquivo PDF/JPG/PNG | 10 MiB | 10 MiB | Manter limite atual; corpo multipart continua até 11 MiB. |
| Imagem decodificada | 12 milhões de pixels; lado até 6.000 | Igual | Manter limites atuais, validar antes de alocar pixels. |
| Processamentos pesados simultâneos | 1 | 2, após medição | Abrange OCR, reconhecimento, PDF e correção visual; não apenas OCR. Sem fila sem limite. |
| OCR de nome / sessão | 1/min | 2/min | OCR é mais caro que consulta. |
| OCR de nome / processo | 3/min | 8/min | Limite global, mesmo com novas sessões. |
| Reconhecimento de gabarito/correção / sessão | 3/min | 6/min | Além do limite de simultaneidade. |
| Reconhecimento de gabarito/correção / processo | 6/min | 20/min | Rejeitar antes de decodificar. |
| Análise de câmera / sessão | 10/min | 20/min | Exige ajustar a cadência atual do frontend (~1 chamada a cada 1,2 s) no modo demo; não repetir continuamente após `429`. |
| Análise de câmera / processo | 20/min | 60/min | Rejeitar excesso antes de decodificar. |
| Demais requisições / sessão | 60/min | 120/min | Consultas e operações, além das cotas específicas. |
| Criação de sessões / processo | 8/min | 20/min | Também sujeita ao limite de sessões ativas. |

Como recomendação adicional, limitar na borda confiável a **origem de rede** a 30 requisições/min e 3 criações de sessão/10 min, com exceções ajustadas para redes compartilhadas. Isso não deve ser implementado usando `X-Forwarded-For` fornecido pelo cliente nem presumindo que `scope.client` representa o visitante: o Uvicorn atual roda com `--no-proxy-headers` atrás do proxy da Render. Se não houver um gateway que forneça IP confiável e faça essa limitação, o requisito de cota por origem de rede **permanece pendente** e impede anunciar resistência a abuso. Cotas por sessão e globais são obrigatórias mesmo com gateway. `Origin` e CORS não substituem essa medida.

Nomes propostos para a configuração Free (ainda inexistentes): `DEMO_IDLE_SECONDS=1800`, `DEMO_ABSOLUTE_SECONDS=7200`, `DEMO_MAX_EVALUATIONS=5`, `DEMO_MAX_STUDENTS=10`, `DEMO_MAX_CORRECTIONS=20`, `DEMO_MAX_SESSIONS=4`, `DEMO_MAX_SESSION_BYTES=1048576`, `DEMO_MAX_TOTAL_BYTES=4194304`, `DEMO_MAX_HEAVY_CONCURRENT=1`, `DEMO_OCR_PER_SESSION_MINUTE=1`, `DEMO_OCR_GLOBAL_MINUTE=3`, `DEMO_HEAVY_PER_SESSION_MINUTE=3`, `DEMO_HEAVY_GLOBAL_MINUTE=6`, `DEMO_CAMERA_PER_SESSION_MINUTE=10`, `DEMO_CAMERA_GLOBAL_MINUTE=20`, `DEMO_REQUESTS_PER_SESSION_MINUTE=60` e `DEMO_NEW_SESSIONS_GLOBAL_MINUTE=8`. Os limites de upload/pixels permanecem nos limites existentes, sem configuração que os aumente. As cotas por origem de rede são configuração do gateway confiável, não variáveis da aplicação FastAPI.

Para `429` e `503`, enviar `Retry-After` quando possível. Respostas propostas: `428` para sessão ausente em rota de negócio; `410` para identificador inválido, desconhecido, expirado ou descartado (sem indicar se já existiu); `429` para taxa ou quantidade por sessão; `503` para capacidade global/worker ocupado; `413` para corpo/upload excessivo; `422` para arquivo ou dados inválidos; `409` para `operacao_id` reutilizado com conteúdo diferente. O health check não deve depender da existência de sessões, mas sucesso em `/api/health` não comprova capacidade para OCR.

## Render e Vercel

O Blueprint atual especifica `plan: 1c-2g`, `branch: feature/deploy-vercel-render` e `APP_AMBIENTE=homologacao`. Em etapa futura, corrigir a referência para `main`, **sem trocar o modo padrão automaticamente**. O plano Free da Render oferece 0,1 CPU e 512 MB de RAM; suspende após 15 minutos ociosos e perde estado em memória/arquivos locais no reinício. Portanto, uma sessão de 30 minutos não tem durabilidade garantida, e o primeiro acesso pode sofrer inicialização demorada. O modo demo requer um único processo/worker e uma instância; mais workers ou réplicas exigem armazenamento compartilhado, que não faz parte deste contrato. Modelos ONNX, OpenCV, PyMuPDF e cópias de imagens podem exceder 512 MB mesmo com um único processamento: medir RSS no Linux com arquivo máximo e OCR antes de considerar Free apto. O plano atual `1c-2g` é pago e não deve ser trocado por `free` apenas com base nesta especificação.

O projeto Vercel permanece estático, com `Frontend` como Root Directory. O identificador via cabeçalho evita depender de cookies entre domínios Vercel/Render. A URL HTTPS da API continua pública em `config.mjs`; não há segredo no bundle. Testar preflight para `X-Demo-Session` e origem Vercel exata; previews só entram se forem explicitamente autorizados. Não habilitar curingas de CORS, nem confiar em `Host` ou `Origin` como identidade.

## Critérios de aceitação antes de qualquer ativação

1. Inicialização demo falha com cada variável/credencial Firebase real conflitante, sem expor seus valores. Teste de integração substitui `conectar_firestore`, `firebase_admin.initialize_app` e verificação de token por funções que falham se chamadas; percorre **todas** as rotas demo, inclusive saúde, erro e concorrência.
2. `local`, `local_publico`, `homologacao`, `producao` e `publico` preservam a matriz de rotas, autenticação e restrições existente. `homologacao` continua apenas com `GET /api/health`; o Blueprint permanece nesse modo até aprovação específica.
3. Duas sessões criadas em paralelo recebem IDs distintos. A sessão B não lista, consulta por ID, busca homônimo, salva em avaliação nem lê histórico da sessão A, inclusive com IDs e `operacao_id` conhecidos. Ausência, identificador malformado ou expirado não acessa dados.
4. Relógio simulado demonstra expiração aos 30 minutos de inatividade e 2 horas absolutas, descarte integral, renovação somente após requisição válida e perda de estado após reinício. Frontend limpa resultados antigos e não reaplica gravação em sessão nova.
5. Testes concorrentes provam contagem atômica de avaliações, alunos e correções; salvamento confirmado mantém nota recalculada, comprovante e resolução de homônimos. Repetição idêntica de `operacao_id` não cria duplicatas; conteúdo divergente retorna `409`.
6. Cotas por sessão e globais, inclusive criação de sessões, rejeitam antes de OCR/decodificação; `429`/`503` preservam dados existentes e enviam recuperação clara. Câmera respeita a cadência reduzida, inclusive após `429`. Medir memória/CPU com PDF e imagem nos limites, OCR e quatro sessões no Linux do plano pretendido.
7. Upload, captura, OCR e revisão visual continuam funcionais; PDF/JPG/PNG e imagens não aparecem no estado demo, disco remanescente, logs ou resposta de outra sessão. Arquivos temporários somem após sucesso, erro e cancelamento.
8. Testes de navegador usam API simulada e comprovam dashboard direto, três abas, cabeçalho de sessão, expiração, isolamento, limites e fluxo completo. Nenhum teste contata Firebase/Firestore real ou a Render pública.
9. Configuração de Host/CORS rejeita origens inesperadas e headers ambíguos; teste por cliente HTTP sem `Origin` demonstra que CORS não é mecanismo de acesso. Revisão de borda confirma cota por origem de rede confiável antes de exposição pública.
10. Interface e documentação exibem aviso inequívoco: **“Demonstração pública. Use somente dados fictícios. Não envie provas ou nomes reais de alunos. Os dados podem desaparecer a qualquer momento.”** Esse aviso não impede tecnicamente o envio de dados reais; se a exigência for garantia de ausência de dados pessoais recebidos, uploads livres/OCR público precisam ser substituídos por arquivos sintéticos controlados.

## Próxima etapa proposta

Implementar primeiro o isolamento estrutural e os testes de falha fechada; depois o repositório efêmero e a sessão; por fim adaptar o frontend, aplicar cotas e realizar medição em Linux. Atualizar documentação e `render.yaml` somente após os testes, mantendo `APP_AMBIENTE=homologacao` até autorização específica. Não reutilizar o modo `publico` com Firestore real para a demonstração.
