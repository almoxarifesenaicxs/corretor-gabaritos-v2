# Estabilização dos riscos prioritários

Implementada em 01/11/2026 na branch `feature/07-alunos-correcao-visual`.
Histórico da análise em [AUDITORIA_GERAL.md](AUDITORIA_GERAL.md).
Não foram feitas migrações, gravações em nuvem ou alterações no motor de pontuação.

## Integridade no salvamento

`POST /api/correcoes/salvar` passa a exigir:

```text
prova_id: ID da avaliação cadastrada
aluno: nome conferido/editado
respostas: as 50 respostas finais no contrato do reconhecimento
resultado: resumo exibido, que deve coincidir exatamente com o recálculo
comprovante: assinatura recebida do processamento ou da revisão
operacao_id: UUID da operação de salvamento
confirmado: true
permitir_provisorio: booleano; necessário para aceitar pendências
aluno_id: opcional, para escolha explícita
novo_homonimo: opcional, para confirmar outra pessoa com o mesmo nome
```

O servidor lê a avaliação e seu gabarito oficial dentro da transação, chama
`corrigir_respostas`, rejeita divergências e persiste o resultado recalculado.
Nome/título da prova, pontuação, percentuais ou situação enviados como campos
extras são rejeitados. A situação é derivada das pendências. Pontuação 999,
percentual divergente, contrato inválido, gabarito incompatível e respostas
alteradas sem comprovante válido não produzem gravação.

O processamento com `visual=true` e a revisão `/api/correcoes/recalcular` retornam
`comprovante`. Ele usa HMAC-SHA256 sobre respostas e gabarito com chave aleatória
mantida somente na memória do processo. Não há chave no frontend ou arquivo de
credenciais. A revisão manual continua permitida e devolve um novo comprovante;
o salvamento sempre confronta esse gabarito com o que pertence à avaliação.

O comprovante protege o transporte entre processamento/revisão e salvamento;
**não autentica o operador nem comprova intenção humana ou a identidade do aluno**.
Um usuário local pode solicitar uma revisão manual válida. Não é uma proteção
contra um operador deliberadamente desonesto com acesso à máquina.

Use **um único worker**. Após reiniciar o backend, leituras/revisões ainda não
salvas precisam ser processadas/revisadas novamente. Um reenvio de operação já
gravada recupera o registro pelo ID e conteúdo, inclusive após reinício, sem
revalidar um comprovante antigo para criar outra gravação.

Os métodos internos legados de persistência permanecem para compatibilidade e
testes, com validação reforçada das contagens. Nenhuma rota pública de salvamento
aceita o contrato antigo que envia somente nome e resumo. Documentos históricos
continuam legíveis e não são atualizados automaticamente.

## Idempotência e homônimos

O frontend gera um UUID no primeiro envio e o mantém quando o mesmo conteúdo é
reenviado após erro. Alterar os dados de uma operação ainda não concluída gera
outro ID. O servidor aceita repetição do mesmo ID/conteúdo e devolve o mesmo
registro; outro conteúdo com o ID já comprometido retorna 409.

Avaliações também exigem `operacao_id`; prova, gabarito e controle da operação
são gravados na mesma transação. Correção, aluno novo, controle do nome e controle
da operação também são atômicos. Não há etapa intermediária que crie aluno isolado.

Coleções adicionais, criadas apenas ao salvar novas operações:

| Coleção | Documento e finalidade |
| --- | --- |
| `operacoes` | `avaliacao-<UUID>` ou `correcao-<UUID>`: hash canônico da entrada e registro retornado. Permite repetição segura sem criar outro documento. |
| `nomes_alunos` | SHA-256 do nome normalizado: contador de versão lido e escrito na transação. Serializa a resolução automática e a criação explícita de homônimos. |

Todas as resoluções pelo novo fluxo passam pelo controle de nome. Se outra
transação cria um homônimo entre leitura e commit, o SDK repete a transação e
refaz a decisão. Havendo mais de um cadastro exato, exige escolha de ID ou
confirmação de nova pessoa. IDs antigos são preservados, inclusive quando o
documento não possui `nome_normalizado`; a consulta inicial normaliza nomes em
memória. Nomes semelhantes nunca são usados como correspondência automática.

São persistidas as respostas finais e o hash do gabarito, sem fotografia,
base64 ou canvas. Ainda não há trilha completa de cada edição manual.
Não excluir controles de idempotência sem definir uma política de retenção:
apagá-los permite que um envio antigo seja interpretado como novo.

A garantia é para **o mesmo ID de operação**, não para qualquer nova correção do
mesmo aluno/avaliação. Nova captura, recarregamento com perda do estado da tela ou
outro ID representam nova operação; em dúvida, consultar o histórico antes de
recomeçar. Escritas externas/administrativas que não respeitem a transação não
são coordenadas por esse protocolo. Pessoas com nomes iguais continuam dependendo
da conferência do operador; o nome sozinho não comprova identidade.

## Upload e processamento

| Limite | Valor e comportamento |
| --- | --- |
| Arquivo | 10 MiB, mantendo extensão e assinatura PDF/JPG/PNG |
| Corpo multipart completo | 11 MiB, incluindo campos, arquivos adicionais e envelope |
| Outros corpos, inclusive JSON | 128 KiB |
| Dimensão máxima | 6000 pixels por eixo |
| Área máxima | 12 milhões de pixels |
| Recepção | Até quatro pedidos com corpo simultâneos por processo |
| Processamento pesado | Até dois pedidos simultâneos por processo; excesso retorna 503 |
| Prazo de recepção | 30 segundos no total e até 10 segundos sem próximo bloco; excesso retorna 408 |

O middleware conta os bytes realmente recebidos, mesmo sem `Content-Length` ou
quando o valor declarado é menor. Excesso retorna 413 antes de entregar o corpo
ao parser multipart. O corpo aceito é mantido em memória dentro desse orçamento;
o limite de recepções restringe também a quantidade de buffers simultâneos.

Cabeçalhos PNG/JPEG são verificados com Pillow antes de `cv2.imdecode`. A
renderização da primeira página PDF verifica as dimensões previstas a 150 dpi
antes de `get_pixmap`. Corrupção e dimensões incompatíveis retornam erro de
leitura (422), sem entrar na detecção das respostas. Pillow já era dependência
instalada do OCR e agora está declarado explicitamente em `requirements.txt`.

Esses limites reduzem risco de exaustão; **não isolam parsers nativos nem impõem
interrupção forçada de uma operação nativa já iniciada**. Processamento PDF hostil
ainda merece isolamento em processo e orçamento de tempo em etapa futura.
O modo local e os arquivos conhecidos continuam sendo a condição de uso.

## Recursos públicos e acesso local

A montagem em `/interface` permite somente index, páginas, componente de captura,
CSS, módulos ativos e fonte/licença da fonte. `.qa`, testes, arquivos privados,
`script.js` não utilizado e qualquer caminho fora da lista retornam 404.
Nenhum arquivo interno foi excluído ou movido nesta estabilização.

Toda a aplicação, inclusive processamento e estáticos, exige conexão de loopback,
Host local, ausência de cabeçalhos de encaminhamento e mesma origem quando
`Origin` está presente. A regra vale tanto no emulador quanto no modo real.
As proteções adicionais da dependência do Firestore real foram preservadas.

Inicie localmente, a partir de `Backend/`:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --workers 1
```

Abra `http://127.0.0.1:8000/interface/` no mesmo computador. Não usar bind público,
proxy ou túnel. `FIRESTORE_MODO=real` continua exigindo configuração explícita e
ADC já descritos em [firebase.md](firebase.md); esta estabilização não acessou
esse modo. A identidade administrativa precisará permitir as coleções adicionais
antes de seu uso real, sem conceder privilégios desnecessários.

**Não há login ou autorização individual. Não publicar.** Processos e usuários
locais com acesso ao computador ainda podem chamar a aplicação. A restrição local
é mitigação de exposição, não substituição de autenticação.

## Validação

- Python: **247 aprovados, 1 ignorado, 0 reprovados**; 39 novos casos de regressão.
- JavaScript: **16 aprovados**.
- Chrome: **7 aprovados**, incluindo reenvio após perda da resposta.
- `pip check`: sem dependências incompatíveis.
- Permanece um aviso de depreciação Starlette/httpx.

Uma repetição intermediária do Chrome teve cinco aprovações e dois timeouts nos
cenários de câmera simulada. A última execução completa passou nos sete cenários,
sem alteração do código da câmera entre essas execuções. A causa da intermitência
não foi comprovada; ela permanece uma limitação da repetibilidade do QA.

O teste opcional do emulador foi ampliado para a transação de correção/aluno e
repetição idempotente, mas continua **não executado por ausência de emulador**.
Os testes de concorrência executados usam transações simuladas com validação de
leituras, commits atômicos e nova tentativa, sem acessar a nuvem. No navegador,
OCR/reconhecimento/correção usam o backend local; persistência é interceptada.
As capturas de QA ficaram em pasta temporária fora da raiz pública.

## Arquivos desta estabilização

- Backend: `app/main.py`, `app/seguranca.py` (novo), `app/routes/correcoes.py`,
  `app/routes/interface.py`, `app/services/persistencia.py`,
  `app/services/reconhecimento.py`, `app/services/captura.py`,
  `app/services/integridade.py` (novo), `app/services/limites_imagem.py` (novo)
  e `requirements.txt`.
- Testes Python: novos `tests/test_estabilizacao.py` e
  `tests/suporte_estabilizacao.py`; adaptados `test_aluno_automatico.py`,
  `test_alunos.py`, `test_api.py`, `test_api_correcao.py`, `test_api_interface.py`,
  `test_correcao_visual.py`, `test_firestore_emulador.py`, `test_firestore_modo.py`,
  `test_nome_aluno.py` e `test_persistencia.py` em `Backend/tests/`.
  As alterações de cliente HTTP usam peer/Host de loopback explícitos; os testes
  de acesso externo permanecem negativos, sem exceção de segurança para testes.
- Frontend: `js/api.mjs`, `js/fluxo-captura.mjs`, `js/correcao-visual.mjs`,
  `tests/unit.test.mjs` e `tests/browser.test.cjs`.
- Documentação: `README.md`, atualização histórica de `docs/AUDITORIA_GERAL.md`
  e este novo `docs/estabilizacao.md`.

HTML, CSS, captura da câmera, OCR e fórmula do motor foram preservados.

Pendências: integração real com emulador, homologação de USB/fotografias/cursiva,
autenticação antes de publicação, isolamento de processamento, paginação e trilha
completa das edições. Não houve limpeza dos achados de baixo risco, commit,
merge ou push. Implementação encerrada para revisão.
