# Interface web e webcam USB — Issue 06

Interface local em HTML, CSS e JavaScript, com somente duas abas: **Avaliações**
e **Correção**. Tema escuro, menu lateral e tons de azul conforme a descrição
SENAI fornecida. Não havia imagem da referência visual anexada para comparação
exata. Não há framework, etapa de build, dashboard ou dados fictícios no produto.

## Executar

No PowerShell, a partir da raiz:

```powershell
cd Backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Abra **http://127.0.0.1:8000/interface/**. O mesmo servidor entrega frontend e
API, sem necessidade de CORS ou outro servidor. A rota `/` continua retornando
o JSON original. Não abra `index.html` diretamente por `file://`.

Para listar e salvar avaliações/correções, inicie o Firestore Emulator conforme
[firebase.md](firebase.md) e defina, **no terminal do backend antes de iniciá-lo**:

```powershell
$env:FIRESTORE_EMULATOR_HOST = "127.0.0.1:8080"
$env:FIREBASE_PROJECT_ID = "demo-corretor-local"
```

As rotas de persistência desta interface usam o emulador por padrão
(`FIRESTORE_MODO=emulador` ou variável ausente). Sem configuração válida,
retornam 503 e exibem a indisponibilidade na tela,
sem listas fictícias ou fallback para produção. A interface ainda permite
selecionar e reconhecer um candidato a gabarito sem banco; cadastrar avaliações
e selecioná-las para correção exige persistência configurada. Para usar uma base
real, é necessário `FIRESTORE_MODO=real`, projeto real, ADC e acesso local direto.
Veja os comandos PowerShell e as restrições em [firebase.md](firebase.md).
Não publique a API administrativa; execute em loopback sem proxy.

## Fluxos

### Avaliações

1. Informe o nome da avaliação.
2. Ative a webcam e fotografe o cartão com as respostas oficiais, ou selecione
   um PDF/JPG/PNG de até 10 MiB.
3. Clique em reconhecer. A imagem ou o PDF é processado pelos serviços existentes.
4. Confira as 50 alternativas. Cada questão pode ser editada; branco, múltipla
   ou duvidosa fica sem resposta pré-selecionada. Todas precisam receber A–E.
5. Marque a confirmação do gabarito oficial e clique em salvar. Alterar uma
   alternativa desmarca a confirmação. O backend valida novamente o gabarito.
6. Prova e gabarito são criados em um único lote atômico do Firestore: não há
   avaliação parcialmente cadastrada por falha entre as duas gravações.

Não há cadastro automático a partir do cartão preenchido. A origem oficial
das respostas deve ser conferida pela pessoa responsável. Nenhum dos PDFs
de exemplo é adotado como gabarito pelo sistema.

### Correção

1. Selecione uma avaliação cadastrada e informe a identificação textual do aluno.
2. Capture ou selecione o cartão e clique em reconhecer e corrigir.
3. A interface consulta o gabarito salvo e usa o endpoint de correção existente.
4. Confira acertos, erros, brancos, múltiplas, duvidosas, pendências, pontuação
   e percentual geral/por disciplina. As questões pendentes são listadas.
5. Marque a conferência e clique em salvar. Resultados provisórios exigem
   também a opção explícita de salvar com pendências.

Trocar aluno, avaliação ou arquivo invalida o resultado em memória, evitando
salvar a leitura anterior associada a novos dados. Durante processamento e
salvamento, controles do contexto ficam bloqueados. Após sucesso, o botão
de salvar correção fica desabilitado para evitar repetição acidental. Não há
idempotência no servidor em caso de repetição de uma requisição de gravação.

Os detalhes de todas as respostas do aluno não fazem parte do retorno do motor;
por isso a tela mostra seus contadores e questões pendentes, sem criar uma
edição automática das respostas do aluno. Para revisar pendências, confira o
cartão e repita a leitura quando necessário, ou salve-o explicitamente como
provisório. Nenhuma alternativa é presumida para múltiplas ou duvidosas.

## Câmera e enquadramento

O navegador usa `getUserMedia({audio: false, video: ...})`, solicita permissão,
lista câmeras de vídeo e permite trocar o dispositivo. Identifique a webcam USB
pelo nome listado; o navegador pode apresentar também câmeras internas/virtuais.
Não é possível garantir pelo nome que o dispositivo seja USB.

A imagem ao vivo é apresentada com uma moldura A4 em retrato e, quando detectado,
um polígono sobre os cantos da folha. A captura usa canvas e Blob no navegador;
não é necessário salvar um arquivo no computador. Uma prévia permite conferir
a fotografia. O botão **Nova captura** reabre a câmera para repetir a foto.

Enquanto o vídeo está ativo, é enviado um frame reduzido a no máximo 800 pixels
no lado maior. Há uma análise por vez, com pausa de 1,2 segundo após a resposta,
sem processamento pesado contínuo no frontend. A análise não salva o frame em
disco nem no Firestore. A foto para reconhecimento tem no máximo 1920 pixels
no lado maior. Requisições de análise são canceladas ao encerrar a câmera;
respostas atrasadas são descartadas. A câmera encerra suas trilhas ao trocar
de aba, selecionar arquivo, fotografar, processar, ocultar ou sair da página.
Permissões concedidas tardiamente também têm suas trilhas encerradas.

Estados são calculados em `app/services/captura.py` a partir do frame:

| Estado | Verificação |
| --- | --- |
| Vermelho | Nenhum quadrilátero candidato com área suficiente, folha aparentemente cortada ou análise indisponível |
| Amarelo | Quatro cantos visíveis, mas posição, tamanho, inclinação ou proporção ainda inadequados |
| Verde | Candidato visível, centralizado, suficientemente grande, alinhado e com proporção próxima de A4 |

O serviço reduz a imagem a até 800 pixels, aplica Canny e fechamento morfológico,
e procura contornos convexos de quatro vértices. Candidatos precisam ocupar
pelo menos 15% do frame e ter razão largura/altura entre 0,48 e 0,95. Cantos
devem ficar a mais de 2,5% das bordas para considerar a folha visível.
O verde exige área de pelo menos 30%, centro a menos de 12% do centro do frame,
inclinação horizontal/vertical de até aproximadamente 4°, lados opostos com
razão menor que 1,12 e largura/altura entre 0,63 e 0,79.

Esses parâmetros são heurísticos, testados com imagens sintéticas. Um retângulo
de fundo pode ser confundido com folha: não há identificação semântica do papel.
O verde **não valida foco, contraste, sombras, presença da grade ou respostas**.
Falhas de rede nunca são apresentadas como enquadramento validado.

A captura manual é permitida em qualquer estado. Se não havia verde, a tela
avisa que o enquadramento não foi validado e requer atenção. Para capturas da
webcam, o backend tenta corrigir a perspectiva quando encontra os quatro
cantos visíveis. Usa `getPerspectiveTransform`/`warpPerspective`, normalizando
para **1240 × 1754**, proporção A4 dos PDFs reais. Se não encontra folha visível,
mantém a captura manual original; a detecção da grade ainda pode rejeitá-la.
Uploads comuns não são retificados automaticamente. O algoritmo de reconhecimento
da Issue 02 não foi alterado; a retificação é um pré-processamento opcional.

Referências: [getUserMedia e contexto seguro](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/getUserMedia),
[seleção de dispositivos](https://developer.mozilla.org/en-US/docs/Web/API/MediaDevices/enumerateDevices),
[transformações OpenCV](https://docs.opencv.org/4.12.0/da/d54/group__imgproc__transform.html).

## Endpoints

| Método e rota | Uso |
| --- | --- |
| `GET /interface/` | Interface e assets locais |
| `GET /api/avaliacoes` | Lista provas persistidas |
| `POST /api/avaliacoes` | JSON `{titulo, alternativas, confirmado: true}`; cria prova e gabarito juntos |
| `GET /api/avaliacoes/{id}/gabarito` | Recupera as 50 alternativas da avaliação |
| `POST /api/gabaritos/reconhecer` | Multipart `arquivo` e `captura` opcional; retorna candidato de 50 questões, sem salvar |
| `POST /api/capturas/analisar` | Multipart `arquivo` JPG/PNG; retorna `estado`, `mensagem`, `cantos` normalizados e `folha_visivel`, sem salvar |
| `POST /api/correcoes/processar` | Rota existente, preservada; recebe `arquivo`, `gabarito` JSON e novo campo opcional `captura=false` |
| `POST /api/correcoes/salvar` | JSON `{prova_id, aluno, resultado, confirmado: true, permitir_provisorio: false}`; grava somente após confirmação |

Cadastros retornam 201; reconhecimento/análise/listagem retornam 200. Arquivos
continuam limitados a 10 MiB e passam pela validação de extensão e assinatura
compartilhada. Campo ausente, dado inválido ou falta de confirmação retorna 422;
arquivo vazio 400, tamanho excedido 413, formato incompatível 415, gabarito não
encontrado 404, conflito 409 e indisponibilidade conhecida do banco 503.
Falhas inesperadas retornam mensagem genérica sem caminhos ou rastreamentos.
Temporários do reconhecimento são removidos mesmo em falhas.

## Testes automatizados executados

```powershell
cd Backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..
node --test Frontend/tests/unit.test.mjs
```

- **Pytest: 152 aprovados, 1 ignorado, 0 reprovados**. O teste ignorado ainda
  exige Firestore Emulator. Mantidos os testes anteriores; novos testes cobrem
  confirmação, cadastro em lote, validação do gabarito pelo motor, consulta,
  salvamento provisório, falhas de banco, estáticos, análise geométrica,
  retificação, captura manual, arquivo inválido e limpeza de temporários.
- **JavaScript: 8 aprovados** usando `node:test`, sem instalar dependências.
  Incluem câmera simulada, liberação de trilhas, permissão tardia, cancelamento,
  falha de análise, validação de arquivos e conferência das 50 alternativas.
- **Chrome/Playwright: 1 cenário aprovado**, passando por câmera simulada,
  fotografia, reconhecimento real do backend, edição e confirmação do gabarito,
  seleção de avaliação, correção, invalidação ao trocar aluno, confirmação
  adicional de provisoriedade, salvamento e permissão negada. A persistência
  nesse teste é simulada por interceptação HTTP; não escreveu no Firestore.
  Foram conferidos screenshots desktop e viewport de 390 pixels, sem overflow
  horizontal. Isso não comprova funcionamento com webcam física.

O teste de navegador é opcional e requer Chrome, Playwright e backend ativo.
Para reproduzir no Windows, a partir da raiz do repositório:

```powershell
# Dependência de QA isolada; não altera dependências do aplicativo.
npm.cmd install --prefix "$env:TEMP\corretor-issue06-qa" playwright
$env:NODE_PATH = "$env:TEMP\corretor-issue06-qa\node_modules"
$env:QA_ARTIFACT_DIR = "$env:TEMP\corretor-issue06-qa"
$env:QA_CHROME_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$env:QA_BASE_URL = "http://127.0.0.1:8000"

@'
import sys, tempfile
from pathlib import Path
import cv2
sys.path.insert(0, str(Path('Backend').resolve()))
sys.path.insert(0, str(Path('Backend/tests').resolve()))
from test_reconhecimento import cartao
destino = Path(tempfile.gettempdir()) / 'corretor-issue06-qa'
marcas = {(i, 0): 'cheia' for i in range(1, 51)}
cv2.imwrite(str(destino/'cartao.png'), cartao(marcas))
marcas[(27, 1)] = 'cheia'
cv2.imwrite(str(destino/'multipla.png'), cartao(marcas))
'@ | .\Backend\.venv\Scripts\python.exe -

node --test Frontend/tests/browser.test.cjs
```

As imagens e dados desse cenário são identificados como testes e ficam fora
do repositório. O frontend não exibe essas amostras como avaliações reais.

## Roteiro pendente com câmera USB física

1. Inicie o emulador e backend e abra a interface por localhost em Chrome/Edge.
2. Conecte a webcam USB; permita acesso. Confira seleção entre câmera interna
   e USB, imagem ao vivo, repetição da foto e encerramento pelo botão desligar.
3. Negue permissão e tente novamente após liberá-la. Teste câmera ocupada por
   outro aplicativo, câmera desconectada e permissão revogada durante o vídeo.
4. Use cartão A4 retrato sobre fundo escuro. Confira vermelho sem folha/cantos
   cortados, amarelo com inclinação/folha pequena/deslocada, e verde com quatro
   cantos visíveis e folha centralizada. Teste sombras e objetos retangulares
   de fundo para identificar falsos positivos e ajustar parâmetros futuramente.
5. Fotografe em vermelho/amarelo e confira o aviso de captura manual. Fotografe
   em verde e compare a leitura após retificação com as marcações visíveis.
6. Repita com diferentes distâncias, foco, iluminação, marcas de lápis/caneta,
   rasuras e cartões parcialmente cortados. Não presuma que verde garante leitura.
7. Reconheça o cartão oficial, confira as 50 respostas e edite uma. Confira que
   a confirmação é removida ao editar e que não salva com questões em branco.
   Confirme e verifique avaliação e gabarito no emulador após recarregar a página.
8. Selecione a avaliação e corrija um cartão de aluno. Compare cada contagem e
   pontuação com uma correção manual independente. Troque aluno/avaliação e
   confirme que o resultado anterior deixa de estar disponível para salvar.
9. Confira que reconhecer não cria documentos. Confirme e salve um resultado
   definitivo e outro provisório, exigindo as duas confirmações neste último.
   Verifique os documentos no emulador e a ausência de imagens/PDFs no banco.
10. Troque de aba, oculte a janela e saia da página. Confira que o indicador de
    uso da webcam se apaga. Teste backend/emulador indisponíveis e arquivo inválido.

## Limitações

Ainda não houve validação física de webcam USB, retificação de foto real ou
ciclo completo desta interface com Firestore Emulator. Os testes do banco são
simulados e o cenário de navegador usa mídia sintética. Cartões em paisagem,
papéis sem contraste, curvas, sombras, desfoque e recortes podem falhar. A
normalização A4 não garante corrigir toda distorção de lente ou de perspectiva.

A frequência da análise é limitada, mas cada usuário ativo gera processamento
no backend. O limite de bytes não limita pixels descomprimidos. Não há fila,
controle de concorrência global, autenticação, autorização ou proteção contra
adulteração de resultados pelo cliente: o salvamento valida o contrato, mas
confia no resultado enviado, conforme a camada de persistência existente.
Use em ambiente local; controles para publicação em rede não fazem parte desta
issue. Falhas de gravação após envio podem exigir conferência no emulador antes
de repetir, pois não há deduplicação no servidor.

Nenhuma foto ou resultado é salvo automaticamente. Sem commits, merges, push
ou início de outra issue.
