# Auditoria geral — Corretor Automático de Gabaritos V2

> **Histórico preservado:** as seções 1–10 registram a auditoria original.
> A seção 11 registra a estabilização posterior autorizada e seus limites.

Data: **01/11/2026**, horário de referência America/Sao_Paulo. Branch examinada:
`feature/07-alunos-correcao-visual`; HEAD: `195665a`.

Escopo: todos os módulos de `Backend/app/`, frontend, testes, dependências,
documentação e estrutura versionada. O repositório estava sem alterações no início.
Esta execução não implementa correções: o único arquivo de projeto criado é este
relatório. Não foram abertos arquivos de credenciais, acessados dados reais do
Firestore, atualizadas dependências ou alteradas branches.

## 1. Resumo executivo

O projeto tem uma arquitetura pequena e compreensível. Reconhecimento, pontuação,
OCR e persistência possuem responsabilidades separadas. Os fluxos principais
funcionaram nos testes disponíveis, incluindo as três áreas do frontend, captura
simulada, OCR impresso sintético, revisão manual e associação automática de alunos.
O motor de pontuação não apresentou defeito comprovado nesta auditoria.

**Não está pronto para publicação.** O uso local é adequado para desenvolvimento e
piloto supervisionado, com conferência humana e dados de teste; a auditoria não
homologa seu uso como registro definitivo de notas reais.

Há **17 achados: 4 altos, 9 médios e 4 baixos**. Não foi comprovada uma falha crítica
no cenário local examinado. Isso não certifica ausência de vulnerabilidades.
Os riscos principais são:

- Salvamento aceita pontuação adulterada pelo cliente: foi reproduzido HTTP 201
  com **999 pontos**, sem tocar no Firestore real.
- Ausência de autenticação/autorização: os controles existentes restringem o modo
  real ao acesso local, mas não identificam nem autorizam o operador.
- Limites insuficientes para recepção HTTP e memória/CPU de imagens e PDFs.
- Reenvios podem duplicar correções; uma corrida específica de homônimos pode
  escapar da exigência de seleção explícita.
- Firestore integrado e cartões fotografados em condições reais ainda não estão
  homologados; os testes de persistência desta execução foram simulados.

## 2. Arquitetura atual

| Componente | Responsabilidade e avaliação |
| --- | --- |
| `Backend/app/main.py` | Cria FastAPI, inclui dois routers, mantém `/` e `/api/health`, serve todo `Frontend/` em `/interface`. Simples; a amplitude do diretório estático merece restrição. |
| `routes/correcoes.py` | Upload, gabarito JSON explícito, processamento e resposta visual opcional. Reutiliza o motor e os detectores. |
| `routes/interface.py` | Avaliações, alunos, histórico, salvamento, revisão, OCR e análise da folha. Modelos Pydantic pequenos no próprio arquivo são adequados ao tamanho atual. |
| `services/reconhecimento.py` | Primeira página PDF a 150 dpi ou imagem BGR; Otsu; duas tabelas reais ou grade circular sintética; quatro estados de resposta. |
| `services/captura.py` | Detecção geométrica de folha A4, estados de enquadramento e retificação para 1240 × 1754. Não reconhece letras. |
| `services/nome_aluno.py` | Localiza linhas do cabeçalho, recorta Candidato e executa RapidOCR/ONNX local. Cache de um motor, trava e preenchimento manual como alternativa. |
| `services/correcao.py` | Valida exatamente 50 questões e alternativas A–E, separa disciplinas e pendências, calcula pontos e percentuais. Sem banco ou HTTP. |
| `services/correcao_visual.py` | Reutiliza geometria detectada e classifica cores. A imagem-base corresponde à imagem processada, inclusive após retificação. |
| `services/persistencia.py` | Cliente injetado, coleções, IDs, lotes atômicos, busca normalizada, histórico e compatibilidade com registros antigos. |
| `database/firestore.py` | Conexão explícita, emulador padrão, ADC somente no modo real, fechamento do cliente/app e bloqueios de produção em Pytest. |
| Frontend | Shell em `index.html`; fragmentos em `pages/` e `components/`; `app.mjs` inicializa após carregamento; `fluxo-captura.mjs` coordena o estado compartilhado. API, câmera, alunos, OCR, revisão e canvas ficam em módulos próprios. |

Não há necessidade comprovada de framework frontend, camada adicional de
repositórios, diretório de modelos preenchido artificialmente ou reescrita do motor.
`fluxo-captura.mjs` ainda tem aproximadamente 595 linhas, mas compartilha câmera,
arquivo e confirmações entre Avaliações e Correção. Extrações futuras devem resolver
duplicação concreta, sem criar uma arquitetura maior que o problema.

## 3. Funcionalidades verificadas

| Funcionalidade | Classificação | Evidência e alcance |
| --- | --- | --- |
| API básica e contratos do motor | Implementado e testado | Suítes HTTP e motor: disciplinas, limites 25/26, percentuais, estados, entradas inválidas e preservação das entradas. |
| Leitura PDF/JPG/PNG | Implementado e testado | Arquivos sintéticos, assinatura, corrupção, PDF protegido, primeira página e limpeza dos temporários. Não é teste de resistência a documentos hostis. |
| Reconhecimento nos dois PDFs digitais reais | Implementado e testado | PDFs locais presentes: 50 brancos no documento vazio e comparação das 50 marcas do preenchido com transcrição independente. O preenchido não foi tratado como gabarito oficial. |
| Nome vazio nos PDFs reais | Implementado e testado | Campo localizado e retorno sem sugestão nos dois originais. Não há amostra positiva manuscrita nesses documentos. |
| Nome impresso sintético por OCR | Implementado e testado | Inferência real local do RapidOCR, falhas e baixa confiança; navegador confere os mesmos bytes no OCR e na correção. |
| Cursiva e nomes manuscritos reais | Implementado, mas sem validação real | Há tentativa por OCR e alternativa manual; não existe corpus que demonstre qualidade em manuscritos. O score 0,96 não é probabilidade calibrada. |
| Webcam, seleção, moldura permanente e encerramento | Implementado e testado | Testes unitários, mídia simulada no Chrome, permissão negada e resposta tardia. USB física e desconexões reais permanecem sem validação. |
| Perspectiva e enquadramento | Implementado, mas sem validação real | Geometria sintética inclinada e retificação testadas. Não comprova desempenho sob sombra, papel curvo, desfoque ou distorção de lente. |
| Correção visual e conferência manual | Implementado e testado | Caixas detectadas, cores nos pixels do canvas, números/símbolos, atualização e reconfirmação; posições inseguras não são inventadas. |
| Cadastro automático, busca, ordem e histórico de alunos | Implementado e testado | Persistência simulada com codec real do SDK e testes Chrome; nomes semelhantes não são associados. Há ressalva de concorrência em A07. |
| Lotes Firestore e fluxo completo com banco | Parcialmente implementado/validado | Chamadas de lote e conflitos testados com mocks. O teste opcional do emulador foi ignorado e ainda exercita principalmente o fluxo anterior, não o novo cadastro automático em lote. |
| Firestore real e restrição local | Implementado, mas sem validação real | Configuração e bloqueios testados com conexão substituída; sem ADC ou RPC real durante a auditoria. |
| Autenticação e autorização de operadores | Ausente | Nenhuma identidade ou permissão de usuário é exigida pelas rotas. |
| Idempotência e rastreabilidade das respostas salvas | Ausente | Cada novo pedido recebe UUID; documento guarda resumo, sem as 50 respostas revisadas ou evidência da origem. |

As proporções A4, região do nome e limiares das tabelas/círculos estão descritos
em `interface-web.md`, `ocr-nome-aluno.md`, `reconhecimento.md` e
`validacao-pdfs-locais.md`. Não foram encontradas coordenadas fictícias usadas
para desenhar alternativas. O reconhecimento assume ordem fixa das disciplinas e
das alternativas: não lê seus rótulos. Otsu global e limiares de tinta podem falhar
sob iluminação desigual; rejeição geométrica não detecta todos os falsos brancos.

## 4. Problemas encontrados

As localizações abaixo correspondem ao HEAD auditado e são aproximadas.
“Alta” pode indicar bloqueio para publicação, sem implicar exposição pública atual.

| ID / gravidade | Arquivo e localização | Problema, evidência e consequência | Recomendação | Complexidade |
| --- | --- | --- | --- | --- |
| **A01 — Alto** | `services/persistencia.py:52–75,160–173`; `routes/interface.py:143–154` | `_validar_resultado` valida tipos e sinais, mas não máximos, somas, percentuais ou vínculo com gabarito. Alterar somente `resumo.pontuacao` para 999 passou na validação e recebeu 201 na rota com banco simulado. A rota também não exige as respostas nem consulta o gabarito da prova para salvar. Notas inconsistentes ou de outra prova podem ser aceitas. | Receber respostas finais e ID da prova; buscar o gabarito no servidor e reutilizar `corrigir_respostas` antes de persistir. Validar também invariantes do contrato. Não mudar a fórmula do motor. | Média |
| **A02 — Alto** | `routes/interface.py:28–67`; `main.py:8–17` | Sem autenticação/autorização. A barreira de loopback/Host/Origin funciona no modo real, mas processos locais podem operar com os privilégios do backend. Rotas de processamento não usam essa barreira. Publicação, proxy que oculte a origem ou máquina compartilhada ampliariam o risco. Não foi demonstrado desvio das barreiras atuais. | Manter loopback sem túnel/proxy. Antes de publicar, exigir identidade e autorização em leituras e escritas, limitar privilégios da identidade do servidor e proteger também o processamento. | Alta |
| **A03 — Alto** | `services/reconhecimento.py:14–38`; `services/captura.py:9–20`; `routes/correcoes.py:59–85` | Decodificação integral e `get_pixmap(dpi=150)` sem limite próprio de dimensões/pixels, orçamento de memória ou prazo de processamento. Um arquivo comprimido pequeno pode expandir muito. Várias chamadas simultâneas e cópias NumPy/base64 aumentam o consumo. Não foram executados ataques de exaustão. | Validar dimensões da imagem e área/dimensões de renderização PDF antes de grandes alocações; impor orçamento de pixels, concorrência e tempo. Considerar isolamento para parsing nativo de arquivos não confiáveis. | Média/alta |
| **A04 — Alto** | `routes/correcoes.py:28–45`; `main.py:8–17` | Os 10 MiB são verificados dentro da rota, depois do parser multipart. Não há middleware próprio de limite total do corpo. O parser instalado aceita até 1000 arquivos e seu `max_part_size` limita campos de texto, não o conteúdo dos arquivos. Dados excedentes podem consumir recepção/disco antes do 413. JSON também não tem orçamento próprio. | Limitar o corpo durante a recepção, inclusive sem confiar em `Content-Length`; restringir quantidade de partes e definir limites coerentes para upload e JSON. Validar com payloads pequenos e limites reduzidos nos testes. | Média |
| **A05 — Médio** | `main.py:17`; `Frontend/.qa/` local | Todo `Frontend/` é servido. `GET /interface/.qa/cartao.png` retornou 200; o teste de navegador também é acessível. A pasta ignorada contém aproximadamente 20 MB de ferramentas e artefatos. `.gitignore` não restringe HTTP: capturas privadas colocadas ali seriam servidas se o caminho fosse conhecido. Não se constatou foto pessoal nessa verificação. | Manter QA fora da raiz estática e servir somente os diretórios/arquivos necessários; testar bloqueio de pastas internas e ocultas. | Baixa/média |
| **A06 — Médio** | `services/persistencia.py:184,219,238–249`; `fluxo-captura.mjs:549–575` | Cada salvamento usa novo UUID. O navegador impede repetição após sucesso conhecido, mas uma resposta perdida permite novo envio e nova correção. `novo_homonimo=true` repetido pode criar também outra identidade. | Definir chave de idempotência por operação confirmada e persistir seu resultado atomicamente; permitir retomada sem duplicação. | Média |
| **A07 — Médio** | `services/persistencia.py:215–249` | A consulta de correspondências ocorre antes de um lote que não protege essa leitura. Foi simulado: existe um aluno exato; outro pedido cria homônimo entre consulta e commit; o primeiro salva no ID anterior sem seleção explícita, embora já existam dois exatos no commit. A deduplicação pelo ID determinístico continua válida no caso comum. | Serializar a resolução do nome em transação com registro de controle por nome normalizado, abrangendo também criação explícita de homônimos, ou exigir escolha explícita de ID quando aplicável. Testar concorrência no emulador. | Média |
| **A08 — Médio** | `services/persistencia.py:100–107,255–289` | Busca e correspondências leem todos os alunos; histórico lê todas as correções e provas para filtrar em Python. A digitação gera consultas sucessivas. Crescimento aumenta latência, memória e leituras faturadas. | Consultar exatos por campo indexado; paginar listagens e histórico por `aluno_id`; tratar legado por nome separadamente. Manter busca por trecho simples enquanto o volume justificar. | Média |
| **A09 — Médio** | `tests/test_firestore_emulador.py:14–49`; `tests/test_captura.py`; `tests/test_nome_aluno.py` | Falta validação integrada de lotes de alunos/avaliações no emulador e de fotos/manuscritos reais. Mocks de commit e exemplos impressos não comprovam comportamento do SDK sob concorrência ou confiabilidade óptica. | Acrescentar ciclo seguro no emulador para o fluxo atual e corpus autorizado de fotos/manuscritos, com revisão independente das 50 respostas e medição de falsos brancos/marcações. | Média |
| **A10 — Médio** | `services/persistencia.py:234–236`; `fluxo-captura.mjs:552–560` | Só o resumo final é salvo. Não ficam as 50 respostas finais, alterações manuais ou referência verificável do gabarito usado. Após recarregar, o histórico não permite reconstruir ou explicar a nota. Não é necessário guardar fotografia para corrigir essa lacuna. | Persistir respostas finais e referência/hash do gabarito, além de indicação das revisões manuais, com contrato pequeno e compatibilidade com documentos antigos. | Média |
| **A11 — Médio** | `routes/correcoes.py:78–85`; `correcao_visual.py:16–45`; `routes/interface.py:194–205` | No modo visual, a imagem é carregada para reconhecer e carregada novamente para geometria; binarização/detecção também se repetem. OCR e correção enviam a mesma imagem em pedidos separados, repetindo retificação/decodificação. A geometria permanece coerente, mas o custo cresce. | Primeiro reutilizar a matriz já carregada e a geometria dentro do mesmo pedido; medir antes de unificar pedidos de OCR e correção. Evitar cache permanente de fotos. | Baixa/média |
| **A12 — Médio** | `Backend/requirements.txt`; `Frontend/tests/browser.test.cjs:1–9`; docs de QA | Há 41 pins, mas 29 outros pacotes instalados, usados transitivamente, não estão fixados ali. Playwright depende de instalação separada e não tem versão reproduzível versionada. A documentação de QA está espalhada. Instalação limpa pode variar sem alteração do código. | Separar lista de dependências diretas de constraints/lock reproduzível, sem instalar nada nesta auditoria; registrar versão e preparação do QA em um roteiro único. | Média |
| **A13 — Médio** | `js/api.mjs:1–3`; `js/paginas.mjs:8–15`; `fluxo-captura.mjs:463–575` | `fetch` não tem prazo padrão. `setBusy(true)` só se desfaz no fim do pedido; carregamento de fragmentos mantém a página inerte enquanto aguarda. Os AbortControllers de câmera/OCR tratam cancelamento, não um prazo geral. Requisição pendurada pode bloquear a operação indefinidamente. | Definir prazos e mensagens de recuperação por operação. Para gravação com resposta inconclusiva, conferir idempotência/histórico antes de incentivar reenvio. | Baixa/média |
| **A14 — Baixo** | `README.md:109,178,228`; `docs/interface-web.md:182–207` | README ainda fala em implementar reconhecimento fotografado e funções futuras já implementadas; informa cinco cenários Chrome, hoje seis. O roteiro antigo gera `cartao.png` e `multipla.png`, mas o conjunto atual também exige `nome-impresso.png` e `visual-mista.png`. | Consolidar instruções atuais, distinguir implementação de homologação e preservar resultados históricos das issues como históricos. | Baixa |
| **A15 — Baixo** | `Frontend/js/script.js`; `css/style.css:198,288,311,401,560`; `fluxo-captura.mjs:201` | `script.js` é vazio e não participa do grafo de imports/HTML/testes/docs. Há seletores sem correspondência no HTML e na geração dinâmica atual: `.local-dot`, `.camera-glyph`, `.page-header h1 span`, `.empty-state > div`. `onMessage: message` é passado a `Students`, mas o construtor só recebe `onSelect`. São resíduos de manutenção, sem defeito funcional comprovado. | Remover apenas esses resíduos após aprovação e comparação visual; não remover módulos ativos ou seletores usados dinamicamente. | Baixa |
| **A16 — Baixo** | `tests/test_api_interface.py:99–113`; `tests/test_persistencia.py:20–69` | Alguns mocks aceitam chamadas não configuradas. No teste de pendência, a asserção de ausência de `document.create` não verifica `batch.commit`, que é o caminho atual do salvamento automático. O HTTP 422 verifica comportamento útil, mas a asserção de gravação é incompleta. | Fortalecer mocks com contrato e verificar o caminho de lote e estado final, sem apagar testes nem replicar cada linha da implementação. | Baixa |
| **A17 — Baixo** | `routes/correcoes.py:89–91`; `routes/interface.py:66,174,189,210`; `services/nome_aluno.py:104` | Exceções inesperadas são sanitizadas corretamente, porém não há registro diagnóstico próprio nesses blocos. Erros diferentes podem virar o mesmo 500 ou OCR indisponível, dificultando manutenção. | Registrar causa e identificador da operação somente no servidor; excluir nomes, imagens, conteúdo de credenciais e outros dados pessoais dos logs. Preservar mensagens HTTP sanitizadas. | Baixa |

### Evidências adicionais das reproduções

**A01:** um resultado válido de 50 acertos foi copiado e apenas
`resumo.pontuacao` foi alterado para 999. `_validar_resultado` o aceitou.
`POST /api/correcoes/salvar` com repositório/cliente simulados e lógica real do
serviço retornou 201 contendo 999. Não houve conexão com banco. A falha está na
fronteira de persistência, não no cálculo de `corrigir_respostas`.

**A07:** foi usado o banco em memória da suíte. Um segundo aluno homônimo foi
inserido imediatamente antes do commit do primeiro pedido. A correção foi salva
no cadastro anterior sem ID explicitamente escolhido, com dois alunos exatos já
existentes. Não foi um teste de concorrência contra Firestore real.

**A05:** o teste serviu somente um PNG sintético já existente. A conclusão é sobre
a abrangência da montagem estática; não se tentou obter arquivo de credencial,
atravessar diretórios ou procurar dados privados em artefatos.

## 5. Código e arquivos desnecessários

| Elemento | Verificação e decisão recomendada |
| --- | --- |
| `Frontend/js/script.js` | Zero bytes; não referenciado por HTML, imports, testes ou documentação. Candidato comprovado a exclusão, pendente de aprovação. |
| CSS e opção descritos em A15 | Comparados HTML, código gerador e referências de runtime. Candidatos pontuais a simplificação; não justificam reescrever o stylesheet. |
| `Backend/app/models/` | Pasta vazia, não versionada como arquivo. Não há necessidade de preenchê-la para “completar arquitetura”. Mantê-la ou removê-la é opcional. |
| `Frontend/.qa/` | Ferramentas e imagens efetivamente usadas no QA local; não são código morto. Recomendação é mover a preparação para fora da raiz pública, não apagar seus artefatos sem análise. |
| `__pycache__`, `.pytest_cache`, `.venv` | Artefatos normais de desenvolvimento, ignorados. Não devem ser versionados nem tratados como implementação do aplicativo. |
| Métodos antigos de persistência | `criar_prova`, `cadastrar_gabarito`, `cadastrar_aluno`, consultas e listagens seguem usados em testes, documentação e/ou compatibilidade. Não recomendar exclusão por ausência de chamada na UI. |
| `__init__.py`, OFL e PNG documental | Pacotes Python, licença da fonte e exemplo visual têm função. Não são candidatos a remoção. |
| Dependências aparentemente indiretas | Não remover `networkx`, `psutil`, `tabulate`, `pymupdf4llm` ou `pymupdf_layout` apenas porque não aparecem nos imports do aplicativo: os metadados do PyMuPDF 2.0 instalado as exigem. ONNX Runtime exige `flatbuffers`; RapidOCR exige PyYAML e outros pacotes. |

A inspeção AST de todos os módulos Python não apontou imports sem uso no aplicativo.
Isso é um indicador estático, não prova universal de inexistência de código morto.
O inventário inicial tinha 66 arquivos versionados, aproximadamente 598 kB no
total; a fonte Manrope e o exemplo sintético são os maiores e têm finalidade clara.
Não há motivo técnico para uma limpeza indiscriminada.

## 6. Segurança e Firebase

### Proteções confirmadas

- Emulador é o padrão e exige host de loopback e projeto `demo-*`. Configuração
  desconhecida falha sem fallback silencioso.
- Modo real exige escolha explícita, projeto e ADC, e rejeita host de emulador.
  Importar a aplicação não inicializa credenciais ou cliente.
- Antes de abrir conexão real, as rotas verificam IP remoto local, Host local,
  ausência de cabeçalhos de proxy e igualdade de Origin quando presente.
- A documentação orienta bind em `127.0.0.1` e `--no-proxy-headers`. Um proxy que
  se apresente como cliente local não é distinguível apenas por essas verificações.
- Pytest bloqueia a conexão real no factory e protege a criação direta de clientes
  síncronos pelo `conftest.py`. Os testes atuais preservam essa barreira.
- Avaliação e gabarito são criados no mesmo lote; aluno novo e correção também.
  `create` impede sobrescrita e o conflito no ID determinístico é tratado.
- IDs são estáveis. Normalização exata usa NFC/espaços/casefold e preserva acentos;
  busca ignora acentos, mas semelhança não associa pessoas automaticamente.
- Históricos por ID e legados por nome são separados, sem migração automática.
- Timestamps são UTC com timezone. Usam relógio do backend, não timestamp de commit
  do Firestore; relógios divergentes podem afetar a ordenação entre máquinas.
- Uploads usam assinatura/extensão e nome temporário controlado. Os temporários
  são removidos em sucesso e exceção tratada. Não há armazenamento de fotografia
  no documento Firestore.
- Dados de alunos e avaliações são inseridos no DOM com `textContent`, `Option`
  ou células de tabela. O `innerHTML` encontrado carrega os fragmentos locais
  fixos, não nomes enviados pelo usuário. Não foi demonstrada injeção de HTML/XSS.
- O `.gitignore` cobre ambiente virtual, caches, `.env*`, `.secrets`, nomes comuns
  de chaves e PDFs locais. Nenhum arquivo de credencial foi identificado no
  inventário versionado atual por seu caminho; seu conteúdo e histórico de
  segredos não foram inspecionados. Nomes arbitrários de chave não são cobertos
  automaticamente pelo ignore.

### Limites e publicação

O SDK servidor não depende das Security Rules do cliente para autorizar suas
operações; usa a identidade administrativa do backend. Portanto, regras de
Firestore não substituem autorização nas rotas. Isso é descrito pela
[documentação oficial de segurança do Firestore](https://firebase.google.com/docs/firestore/security/rules-conditions).

Sem autenticação, autorização, proteção de recursos e garantia de integridade no
salvamento, **não disponibilizar publicamente**. Mesmo localmente, limitar o
acesso ao computador e conferir notas/identidades. CORS ausente não é autorização
contra clientes HTTP diretos. Não foi inspecionado IAM, regras, backups, retenção
ou orçamento de um projeto real; esses itens não podem ser declarados seguros.

O serviço não oferece exclusão; checagens de existência de prova/aluno e gravação
não são uma única transação de leitura e escrita. Exclusões externas concorrentes
podem deixar referências órfãs. Não há evidência de perda causada por exclusão
automática no código atual. Backups e retenção precisam ser definidos antes de
usar a base como registro definitivo de dados escolares.

### Dependências

`pip check` terminou sem incompatibilidades. Foram consultados, sem instalar ou
atualizar pacotes, os metadados de versão da API pública do PyPI: **41 entradas
fixadas** e **29 outros pacotes instalados** (sem incluir pip/setuptools).
O campo `vulnerabilities` estava vazio nas versões consultadas. O significado
desse campo e o endpoint por versão estão na
[documentação da API JSON do PyPI](https://docs.pypi.org/api/json/).

Isso não é certificação de segurança, análise do código binário, verificação da
origem dos wheels ou auditoria completa de vulnerabilidades transitivas/native
fora desse inventário. Não foi executado `pip-audit`, instalado scanner ou feita
atualização. Dependências JavaScript de QA não receberam varredura completa de
advisories. O risco comprovado desta revisão é a ausência de limites próprios e
de reprodução completa das dependências, sem atribuir CVE não demonstrada.

## 7. Testes

### Execução segura

| Verificação | Resultado |
| --- | --- |
| Python: `.\.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`, em `Backend/` | **208 aprovados, 1 ignorado, 0 reprovados**, 1 aviso preexistente Starlette/httpx |
| JavaScript: `node --test Frontend/tests/*.test.mjs` | **15 aprovados, 0 ignorados, 0 reprovados** |
| Chrome: `node --test Frontend/tests/browser.test.cjs` | **6 aprovados, 0 ignorados, 0 reprovados** |
| `python -m pip check` | Sem dependências incompatíveis |
| Verificações adicionais em memória | Pontuação 999 aceita; corrida de homônimo reproduzida; arquivos internos servidos pelo mount estático |
| Inventário dos fragmentos e referências literais JS | 68 IDs HTML, sem duplicidades; nenhuma referência literal consultada apontou para ID ausente |

Pytest foi executado com bytecode desabilitado, sem atualizar cache de pytest e
sem `FIRESTORE_EMULATOR_HOST`. Credenciais de arquivo foram removidas somente do
ambiente dos subprocessos de validação, sem ler ou modificar o arquivo ou a
configuração persistente. O modo desses subprocessos foi `emulador`, projeto
`demo-auditoria`. O teste ignorado é exclusivamente o ciclo opcional do emulador.
Os PDFs locais estavam presentes e seus testes não foram ignorados.

O servidor de QA foi iniciado em `127.0.0.1:8877`, sem proxy headers, no ambiente
seguro descrito, e encerrado ao terminar. A persistência no navegador foi
interceptada por mocks. Somente reconhecimento, OCR e correção usaram o backend
local real. Os quatro PNGs sintéticos necessários foram copiados para diretório
temporário fora do projeto; capturas de QA foram gravadas nesse diretório, sem
substituir os artefatos existentes do repositório. Playwright e Chrome já estavam
instalados; nenhuma dependência foi acrescentada.

### Qualidade e limites de cobertura

Os testes verificam comportamento relevante: falhas HTTP, limpeza, contrato do
motor, reconhecimento comparado com transcrição independente, serialização do
SDK, conflitos de criação, herança de registros antigos, edição manual,
reconfirmação, cores do canvas e descarte de respostas tardias.

A repetição entre serviço, rota e navegador representa em geral níveis diferentes
de integração; não justifica apagar testes. Helpers importados de outros módulos
`test_*` podem futuramente ir para fixtures compartilhadas, se houver dificuldade
de manutenção, sem obrigação de nova estrutura agora.

Não foi obtida porcentagem de cobertura de linhas: nenhum plugin foi instalado.
As provas exploratórias desta auditoria foram executadas em memória, não incluídas
na suíte permanente, em respeito ao escopo de leitura. Logo, a suíte verde atual
**não significa que os achados A01/A07 estejam cobertos por regressão**.

Continuam pendentes: SDK/commit real no emulador para o novo fluxo, concorrência
real de múltiplos operadores, perda da resposta após gravação, limites de pixels
e corpo HTTP, sombras/desfoque/fotos em várias resoluções, letra cursiva, teclado
e leitor de tela completos. Os testes existentes cobrem redimensionamento
sintético, não uma matriz de qualidade de todas as resoluções.

## 8. Melhorias recomendadas

1. **Integridade antes do salvamento:** A01 e A06. Recalcular no servidor usando
   gabarito da avaliação e tornar o envio confirmado idempotente.
2. **Proteção operacional:** A03–A05. Limitar corpo/pixels/processamento e retirar
   ferramentas/artefatos da superfície estática, mantendo uso local.
3. **Identidade e persistência:** A07, A09 e A10. Proteger resolução concorrente
   de homônimos, validar lotes no emulador e registrar as respostas finais.
4. **Homologação óptica:** A09. Fotografias autorizadas e transcrição independente;
   medir erros em vez de prometer reconhecimento de manuscritos.
5. **Preparação para crescimento:** A08, A11–A13. Consultas seletivas, reutilização
   de processamento, prazos HTTP e ambiente reproduzível.
6. **Manutenção pequena:** A14–A17. Atualizar instruções, remover resíduos
   comprovados, fortalecer mocks e melhorar diagnóstico sanitizado.
7. **Publicação somente em etapa própria:** A02. Autenticação, autorização, IAM
   mínimo, transporte seguro e política de dados antes de abrir acesso em rede.

## 9. Plano de correção

| Etapa | Ajuste pequeno e verificável | Critério de aceite |
| --- | --- | --- |
| 1 | Corrigir a fronteira de salvamento, sem alterar a fórmula do motor | Pontuação adulterada e gabarito de outra prova rejeitados/recalculados; notas válidas preservadas. |
| 2 | Idempotência de avaliação/correção e confirmação de homônimos sob concorrência | Mesmo envio não duplica; nova tentativa após resposta perdida recupera o mesmo registro; corrida exige decisão correta. |
| 3 | Limites de entrada e raiz estática | Corpo excedente barrado antes de spool excessivo; dimensões/pixels fora do orçamento rejeitados; `.qa`/testes não servidos. |
| 4 | Integração segura do banco | Emulador `demo-*`: avaliação+gabarito, aluno+correção, consulta de histórico, falhas e concorrência; sem produção. |
| 5 | Evidência da correção | Guardar respostas finais e referência do gabarito, sem imagens e sem migrar registros antigos automaticamente. |
| 6 | Corpus real e recuperação de interface | Documentar resultados por condição e manuscrito; timeout recuperável sem repetir gravações indevidamente. |
| 7 | Organização e desempenho pontuais | Reduzir dupla decodificação, melhorar consultas conforme volume, corrigir docs/mocks e remover somente resíduos aprovados. |
| 8 | Segurança para eventual publicação | Revisão específica de autenticação/autorização e implantação; não transformar a configuração local atual em serviço público. |

Executar a suíte em cada etapa e comparar o comportamento visual. Nenhuma dessas
correções foi implementada nesta auditoria.

## 10. Parecer final

| Pergunta | Parecer |
| --- | --- |
| O sistema está organizado? | **Sim, de forma adequada ao porte.** A separação de serviços e fragmentos é compreensível; há resíduos pequenos e coordenação frontend ainda concentrada. |
| As funcionalidades estão integradas corretamente? | **Nos cenários testados, sim.** Há lacunas importantes de confiança no salvamento, concorrência de homônimos e integração real com banco/fotografias. |
| Existem arquivos/implementações desnecessários? | **Poucos elementos comprovados:** `script.js` vazio, seletores e opção não consumida. Dependências transitivas e métodos legados não devem ser removidos indiscriminadamente. |
| Há risco de perda ou inconsistência de dados? | **Sim, sobretudo inconsistência:** notas adulteradas, reenvios duplicados, corrida de identidade e ausência de respostas auditáveis. Lotes protegem contra gravação parcial; não foi comprovada exclusão indevida pelo sistema. |
| Está pronto para uso local? | **Para desenvolvimento e piloto supervisionado, com ressalvas.** Preferir emulador; corrigir A01 antes de confiar em notas persistidas como registro oficial. A câmera física e manuscritos exigem homologação. |
| Está pronto para publicação? | **Não.** Faltam autenticação/autorização e proteção de recursos; o modo administrativo real deve continuar restrito à máquina local. |
| O que corrigir primeiro? | **A01**, depois idempotência/concorrência e limites de processamento/recepção; validar o fluxo no emulador antes de homologar persistência. Autenticação é pré-requisito de qualquer publicação. |

Não houve alteração de código, testes, dependências, configuração, credenciais ou
dados reais; apenas a criação deste relatório e artefatos temporários de execução
fora do repositório. Nenhum commit, merge, push ou alteração de branch foi feito.
As correções permanecem pendentes de aprovação.

## 11. Estabilização autorizada — 01/11/2026

Esta seção atualiza o estado sem substituir evidências e conclusões históricas.
Detalhes do contrato, limites, coleções e execução em
[estabilizacao.md](estabilizacao.md).

| Achado | Estado após estabilização | Evidência / limite |
| --- | --- | --- |
| A01 | Corrigido no salvamento HTTP | Respostas obrigatórias, comprovante HMAC, consulta transacional do gabarito da avaliação, recálculo pelo motor existente e comparação do resumo. 999, percentuais/situação divergentes e alterações sem comprovante válido são rejeitados sem gravação. Revisão manual válida continua permitida. |
| A02 | Mitigado para uso local; publicação bloqueada | Toda a aplicação exige peer/Host local, mesma origem quando fornecida e ausência de proxy headers. Autenticação/autorização continuam ausentes por decisão de escopo. |
| A03 | Mitigado; isolamento ainda pendente | Máximo de 6000 pixels/eixo e 12 MP, validação antes de decodificar/renderizar, até dois processamentos e quatro recepções por processo. Não há interrupção forçada ou sandbox de parser nativo. |
| A04 | Corrigido quanto ao orçamento de recepção | 11 MiB multipart e 128 KiB nos demais corpos, medição real antes do parser, inclusive sem tamanho declarado. Prazo de recepção e concorrência limitados. Arquivo mantém 10 MiB. |
| A05 | Corrigido | Lista explícita de arquivos estáticos públicos. Testes HTTP verificam 404 para `.qa`, testes e caminhos privados; arquivos não foram removidos. |
| A06 | Corrigido para reenvio do mesmo ID | UUID obrigatório e transação atômica com controle em `operacoes`, tanto para avaliação quanto correção. Mesmo conteúdo retorna o mesmo registro; outro conteúdo com ID comprometido retorna 409. Novo ID continua representando nova operação. |
| A07 | Corrigido no fluxo HTTP, com teste simulado | Controle transacional por nome em `nomes_alunos`; concorrência força nova leitura antes de associar/criar. Regressões simulam homônimo concorrente e reenvio concorrente. Falta executar o caso no emulador; escritores externos precisam respeitar o protocolo. |
| A08 | Pendente | Consulta inicial ainda percorre alunos para preservar IDs/documentos antigos sem migração. Paginação e índices ficam para outra etapa. |
| A09 | Pendente de homologação | Teste opcional do emulador ampliado, mas ignorado sem serviço configurado. USB física, fotos e manuscritos reais continuam sem homologação. |
| A10 | Parcialmente corrigido como parte de A01 | Novos documentos guardam respostas finais e hash do gabarito. Não existe trilha completa de cada edição manual; documentos antigos não foram migrados. |
| A11 | Pendente | Não foi unificado o pipeline de OCR/visualização nesta etapa. |
| A12 | Pendente | Pillow declarado explicitamente por seu novo uso direto; não foi criado lock completo nem atualizadas dependências. |
| A13 | Parcialmente mitigado | Recepção HTTP tem prazo; não foi acrescentado timeout geral ao fetch ou limite de execução forçada do código nativo. |
| A14–A17 | Fora do escopo de limpeza | Resíduos de código/CSS, atualização geral dos textos e diagnóstico não foram tratados. Ajustes de testes se limitaram ao novo contrato, acesso local e transações. |

Validação: **247 testes Python aprovados, 1 ignorado e 0 reprovados**,
**16 JavaScript aprovados**, **7 Chrome aprovados**, `pip check` sem conflitos.
São 39 novos casos Python e um novo cenário Chrome. O teste ignorado é o do
Firestore Emulator; persistência e concorrência executadas com dependências
simuladas, sem ADC ou Firebase real. O motor de pontuação permaneceu inalterado.

Na repetição intermediária do Chrome, os dois cenários de câmera simulada tiveram
timeout; a execução completa final passou nos sete cenários sem alteração da
câmera. A causa não foi comprovada, e a intermitência continua registrada como
limitação de QA, sem alegação de homologação física.

Parecer atualizado: as proteções aumentam a segurança do uso local supervisionado,
mas **não tornam a aplicação pronta para publicação** nem substituem homologação
do banco e das imagens reais. Operadores/processos locais continuam confiáveis
por premissa; nomes não comprovam identidade e uma revisão manual válida pode
alterar respostas. Executar um único worker, sem proxy/túnel, em loopback.
Após reinício, comprovantes ainda não salvos precisam ser renovados por nova
leitura/revisão; operações já comprometidas podem ser recuperadas por reenvio
do mesmo ID/conteúdo. Sem migração de documentos existentes ou acesso à nuvem.

Nenhum commit, merge ou push foi realizado. As próximas alterações aguardam revisão.
