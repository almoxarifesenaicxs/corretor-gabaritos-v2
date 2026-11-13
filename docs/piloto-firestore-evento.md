# Piloto controlado do Firestore real para o evento

**Preparado em 12/11/2026; não executado.** Este procedimento depende de autorização explícita posterior para ler, criar e remover documentos no projeto Firebase escolhido. Até lá, não conectar ao Firestore nem iniciar o backend com credenciais reais. Leia também [checklist-firestore-evento.md](checklist-firestore-evento.md).

## Estado local verificado nesta preparação

Neste terminal, `APP_AMBIENTE`, `FIRESTORE_MODO`, `FIREBASE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS` e `INTEGRIDADE_CHAVE` estão **ausentes**. Portanto a existência, estrutura, chave privada e associação do arquivo de credenciais ao projeto **não foram verificáveis**. Não foi procurado nenhum arquivo de chave por nome no computador. `FIRESTORE_EMULATOR_HOST`, `FIREBASE_AUTH_EMULATOR_HOST`, `CORS_ORIGINS`, `FORWARDED_ALLOW_IPS` e indicadores de hospedagem examinados também estão ausentes. Nenhum valor secreto foi exibido.

## Pré-condições para uma execução autorizada

1. Escolher o **projeto e banco `(default)` exatos**. Preferir projeto de homologação isolado com os mesmos índices e IAM; se o projeto do evento for indispensável, reservar uma janela controlada e usar somente os IDs exclusivos abaixo. Confirmar plano, cotas, orçamento, horário e responsável pela execução.
2. Em estação Windows dedicada, configurar `APP_AMBIENTE=local_operacional`, `FIRESTORE_MODO=real`, `FIREBASE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS`, `INTEGRIDADE_CHAVE`, `SERVIR_FRONTEND=true` e `LOCAL_OPERACIONAL_HOST=127.0.0.1`. O JSON deve ficar **fora do repositório**, com ACL restrita. Nunca registrar seus campos, chave privada ou variável `INTEGRIDADE_CHAVE` no manifesto ou em logs. `GOOGLE_APPLICATION_CREDENTIALS` deve apontar para arquivo existente; `firebase_admin.credentials.Certificate` deve aceitar o arquivo e retornar `project_id` igual a `FIREBASE_PROJECT_ID`, sem conexão de rede nessa verificação. Nenhum emulador, CORS, proxy, túnel ou variável Render/Vercel deve estar presente.
3. No console do projeto correto, conferir os índices de campo único `alunos.nome_normalizado`, `correcoes.aluno_id`, `correcoes.aluno` e `correcoes.prova_id`; conferir o composto `correcoes(aluno_id ASC, processada_em DESC, __name__ ASC)` no escopo de coleção e em estado **Ready**. O arquivo local `firestore.indexes.json` não existe; isso não informa o estado remoto. Não criar ou publicar índices automaticamente. Conferir a conta de serviço e IAM separadamente das regras do SDK cliente.
4. Só após essas verificações e autorização de acesso real, iniciar **um worker** com `uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --workers 1`. Abrir apenas `http://127.0.0.1:8000/interface/` na mesma máquina. `GET /api/health` testa a API, **não** o Firestore.

## Identificação e manifesto privado

Gerar um UUID aleatório `piloto_id` **uma vez**, antes de qualquer POST. Usar:

- Título: `PILOTO FICTICIO EVENTO <piloto_id>`.
- Aluno: `Aluno Ficticio Piloto <piloto_id>`; não usar nome de pessoa real.
- `operacao_id` da avaliação: UUID aleatório `op_avaliacao`.
- `operacao_id` da correção: outro UUID aleatório `op_correcao`.
- Gabarito fictício: 50 respostas `A`. Respostas fictícias: 50 marcas `A`; nenhuma imagem é necessária para este teste de persistência.

Antes da primeira escrita, guardar **fora do repositório** um manifesto local privado com `piloto_id`, projeto/banco escolhidos, os dois IDs de operação, título, nome fictício, payloads exatos, horário de início e campos vazios para `prova_id`, `aluno_id`, `correcao_id` e resultado da limpeza. O manifesto não contém credenciais nem dados pessoais, mas contém o comprovante da operação; protegê-lo e retê-lo até reconciliar ou limpar o teste. Não recriar UUIDs depois de resposta inconclusiva.

Para garantir que nada preexistente será reutilizado ou removido, o responsável deve fazer **leituras exatas, não varredura ampla**, antes do POST: `operacoes/avaliacao-<op_avaliacao.hex>`, `operacoes/correcao-<op_correcao.hex>`, o ID determinístico do aluno (`sha256` do nome normalizado) em `alunos`, o mesmo hash em `nomes_alunos`, e igualdade de `alunos.nome_normalizado`. Todos devem estar ausentes. Se algum existir, **parar e gerar outro `piloto_id` e novas operações**. A criação de prova/correção usa `create` e transação; jamais sobrescrever um documento anterior.

## Sequência do piloto, após autorização

1. Criar a avaliação por `POST /api/avaliacoes` com `titulo`, `alternativas` de 1 a 50, `confirmado=true` e `op_avaliacao`. Antes de enviar, salvar o payload no manifesto. Registrar o `prova_id` retornado; se a resposta se perder, repetir **o mesmo** payload e ID de operação, nunca criar outro.
2. Recalcular as 50 respostas fictícias por `POST /api/correcoes/recalcular` para obter `resultado` e `comprovante` do backend. Preparar o payload de `POST /api/correcoes/salvar` com `prova_id`, nome fictício, `respostas`, `resultado`, `comprovante`, `confirmado=true`, `permitir_provisorio=false` e `op_correcao`. Salvar o payload no manifesto **antes** do envio. Não enviar `novo_homonimo` ou `aluno_id`: o nome exclusivo deve criar um aluno novo.
3. Consultar `GET /api/operacoes/correcao/<op_correcao>` e conferir estado `confirmada` e o mesmo `correcao_id`. Se o POST não retornar, consultar essa rota antes de reenviar. Se a consulta falhar por rede, classificar como **desconhecida** e aguardar; não gerar nova operação. Se `nao_encontrada`, reenviar apenas o payload original e o mesmo ID, depois consultar novamente.
4. Reenviar o mesmo POST deliberadamente e exigir retorno do **mesmo** `correcao_id`, sem segunda correção. Consultar `GET /api/alunos/<aluno_id>/correcoes?pagina=true` e conferir o aluno retornado, uma correção, avaliação e nota esperada. Essa consulta exercita o índice composto.
5. Exportar por `GET /api/correcoes/exportar?prova_id=<prova_id>` e conferir uma linha CSV, os IDs de avaliação, aluno, operação e correção, 50 acertos, zero erros/brancos e a contagem do resumo. A exportação sem filtro pode conter dados reais e **não deve ser usada** neste piloto no projeto do evento. Guardar apenas o CSV filtrado em local privado de teste.
6. Registrar tempos, códigos HTTP, contagem de leituras/escritas e eventuais erros de índice ou IAM. Não imprimir payloads, credenciais ou respostas contendo dados além do conjunto fictício nos logs compartilhados.

## Limpeza segura, após conferência e autorização de remoção

A API não tem endpoint administrativo de exclusão para esses documentos. A limpeza deve ser feita **posteriormente**, em operação controlada do Admin SDK ou console, usando **somente IDs do manifesto**, nunca `delete collection`, filtro por prefixo ou varredura genérica. O piloto pode criar até seis documentos: `provas/<prova_id>`, `gabaritos/<prova_id>`, `operacoes/avaliacao-<op_avaliacao.hex>`, `alunos/<aluno_id>`, `correcoes/<correcao_id>` e `operacoes/correcao-<op_correcao.hex>`, além de `nomes_alunos/<sha256(nome_normalizado)>` (sete no total). Se o piloto falhar antes do salvamento, haverá menos documentos.

Antes de remover qualquer um, reler os sete IDs e verificar `piloto_id` no título/nome, vínculos entre IDs, operações originais e **versão 1** do controle de nome. Confirmar que o nome fictício não foi usado por outra correção e que nenhum documento foi alterado após o piloto. Se houver divergência, concorrência, documento preexistente ou incerteza, **não apagar**: preservar o manifesto e encaminhar para análise. Depois de backup do CSV filtrado e dessa conferência, apagar os documentos criados pelo piloto em lote/transação com pré-condições de atualização para não remover alterações concorrentes. Confirmar por leitura exata que todos os IDs de teste foram removidos; registrar o resultado no manifesto. A remoção dos documentos de operação elimina a possibilidade de reenviar idempotentemente o piloto, por isso ela ocorre **somente no fim**.

Se a organização não autorizar exclusão em projeto compartilhado, manter os registros fictícios identificados, documentar a pendência e excluí-los apenas em janela própria. Não sacrificar dados existentes para obter uma limpeza completa.

## Critérios objetivos de aprovação

O piloto só é aprovado se: (1) projeto/conta/banco e índices forem confirmados; (2) todas as rotas funcionarem só no loopback; (3) prova, aluno e correção forem criados exclusivamente com IDs novos; (4) o salvamento recalculado e assinado confirmar exatamente uma correção; (5) consulta por operação e reenvio devolverem o mesmo ID; (6) histórico paginado retornar uma correção sem erro de índice; (7) CSV filtrado e resumo tiverem uma linha e IDs/notas corretos; (8) latência e uso do Firestore forem registrados; (9) não houver erro de IAM, cota ou conexão; e (10) a limpeza autorizada terminar sem afetar documento preexistente, ou a retenção controlada ficar registrada. Qualquer falha deixa o piloto **inconclusivo**, não aprovado.

Em queda de rede, resposta perdida ou reinício, manter o manifesto, consultar a operação original e reconciliar antes de novo POST. Não interpretar `/api/health`, a existência da avaliação, o estado do navegador ou um CSV parcial como confirmação do salvamento. Não executar o ensaio de 1.000 itens no projeto real antes de aprovar este piloto pequeno.
