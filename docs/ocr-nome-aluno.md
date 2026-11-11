# OCR local do nome do aluno

O nome é sugerido na aba **Correção** após fotografar ou selecionar o cartão.
O campo continua editável e o salvamento mantém a confirmação explícita já
existente. O OCR não muda o motor de pontuação, o contrato do resultado nem
grava documentos no Firestore. Não há novas abas.

## Layout real inspecionado

Foram inspecionadas as imagens e a primeira página dos PDFs locais:

| Arquivo | Linha Candidato a 150 dpi | Resultado no original |
| --- | --- | --- |
| `Gabarito em Branco.pdf` | Aproximadamente x=280–1065, y=510 | Campo vazio; `nome=null`, `nao_identificado` |
| `Gabarito Prova AIB.pdf` | Aproximadamente x=262–965, y=273 | Campo vazio; `nome=null`, `nao_identificado` |

As imagens têm aproximadamente 1241 × 1754 pixels. As coordenadas acima
descrevem a inspeção; **não são coordenadas fixas usadas no serviço**.
Nos dois documentos o nome fica depois do rótulo **Candidato:**, antes de
Curso. O PDF em branco ainda tem uma linha curta para número entre ambos.

`recortar_nome` identifica linhas horizontais longas no cabeçalho (10–37%
da altura), junta pequenos intervalos entre sublinhados e exige a geometria
das linhas Candidato/Curso: a primeira começa mais à direita do que a segunda.
Linhas devem ter pelo menos metade da largura e começar entre 14 e 30% dela.
O intervalo vertical entre as duas deve medir 1,5–10% da altura. Cabeçalhos
desconhecidos, incompletos ou recortados retornam nome não identificado.

O recorte começa depois do rótulo, acima da linha Candidato, com extensão
limitada pela distância até Curso e pela altura da página. Há uma pequena
margem abaixo da linha para descendentes de letras; a linha horizontal é
removida antes do OCR. Isso pode prejudicar escrita que cruze o sublinhado.

## Tecnologia e compatibilidade

Foi escolhido **RapidOCR 3.10.0 + ONNX Runtime**, em CPU. O ambiente já tinha
`onnxruntime==1.31.1`; a instalação do RapidOCR e de suas dependências foi
verificada no **Python 3.14.6**, incluindo inferência real do modelo.
`pip check` não encontrou incompatibilidades. Instale normalmente:

```powershell
cd Backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

O wrapper Python e os modelos ONNX evitam depender de um executável Tesseract
separado. Tesseract foi considerado, mas sua documentação ressalta limitações
para manuscritos. Isso não significa que a alternativa escolhida garanta
leitura de qualquer letra cursiva.

São usados os modelos multilíngues **PP-OCRv6 small** incluídos no wheel
fixado do RapidOCR: `PP-OCRv6_det_small.onnx` e `PP-OCRv6_rec_small.onnx`.
A rota multilíngue inclui português. O modelo de orientação também é
referenciado por caminho local, mas seu uso está desativado: a página é
esperada em retrato, com texto na orientação correta.

Todos os caminhos são locais, explícitos e verificados antes de instanciar
o motor. Não há download automático na inferência. Se algum modelo estiver
ausente ou falhar, a resposta solicita preenchimento manual. Nenhuma imagem
é enviada ao RapidAI, a provedores de OCR ou a qualquer serviço externo.
O download de pacotes ocorre somente na instalação pelo pip.

Referências técnicas:
[RapidOCR no PyPI](https://pypi.org/project/rapidocr/),
[modelos e rotas oficiais](https://rapidai.github.io/RapidOCRDocs/main/en/model_list/),
[limitações do Tesseract para manuscritos](https://tesseract-ocr.github.io/tessdoc/FAQ).

## Fluxo de integração

1. A foto vira um `File` no navegador, sem exigir download pelo usuário.
2. Na aba Correção, o mesmo `File` é enviado ao novo endpoint de nome.
3. Para fotos da câmera, a retificação existente é aplicada antes do recorte.
   Foi adicionada uma proteção conservadora: candidatos laterais não são
   retificados, pois uma tabela de alternativas podia ser confundida com folha
   e excluir o cabeçalho. Uma folha deslocada ainda pode exigir reenquadramento.
4. O campo é recortado e pré-processado pelo OpenCV; o modelo OCR faz a leitura.
5. Apenas sugestões aceitas preenchem o campo. O usuário pode editar o nome.
6. A correção usa o mesmo arquivo capturado. O teste de navegador compara os
   bytes do arquivo enviado ao OCR e ao processamento das respostas.
7. Nome e resultado só são persistidos pela operação de salvamento confirmado.

O upload HTTP ao próprio backend acontece em duas requisições independentes,
ambas com o mesmo arquivo e a mesma opção de retificação. Não há duplicação
do algoritmo OpenCV nem alteração no motor de correção. Durante a leitura do
nome, o botão de processar aguarda sua conclusão; o campo permanece editável.

Um nome já digitado manualmente é mantido, sem OCR que o sobrescreva. Ao trocar
a captura, uma sugestão anterior não editada é removida. Respostas atrasadas
de OCR não se aplicam após troca de arquivo/aba ou edição manual. A mudança
automática ou manual do nome invalida o resultado anterior, preservando a
associação entre aluno e correção.

## Endpoint e confiança

`POST /api/alunos/reconhecer-nome` recebe multipart com `arquivo` e
`captura=false` opcional. Usa a validação existente de PDF/JPG/PNG, assinatura
e limite de 10 MiB. Arquivos temporários são removidos ao encerrar a operação.
Para PDF, somente a primeira página é considerada. Fotos não são armazenadas
permanentemente.

Exemplo de resposta de uma **amostra impressa sintética**:

```json
{
  "nome": "MARIA DA SILVA",
  "estado": "sugerido",
  "confianca": 0.9996,
  "mensagem": "Nome sugerido pelo OCR. Confira e corrija antes de confirmar o salvamento."
}
```

Estados possíveis: `sugerido`, `nao_identificado`, `baixa_confianca` e
`indisponivel`. Nos últimos três, `nome` e `confianca` são nulos, e o campo
permanece vazio para preenchimento manual, salvo se já houver texto digitado
pelo usuário. Ausência de texto não é falha da correção de respostas.
Arquivo inválido continua retornando erro HTTP apropriado; falhas conhecidas
do OCR retornam estado `indisponivel` sem expor detalhes internos.

Aceitação conservadora exige o menor score dos segmentos de texto de pelo
menos **0,96**, texto em caracteres latinos, 2–10 palavras e 4–120 caracteres.
São rejeitados números, rótulos do formulário e texto incompatível com nome.
Nomes de uma palavra, grafias não latinas ou trechos incompletos podem exigir
entrada manual. Não há dicionário de nomes, correção ortográfica, preenchimento
de letras ausentes ou consulta a cadastro de alunos.

**O score não é uma probabilidade calibrada de acerto**, especialmente em
cursiva. Um texto incorreto pode receber score alto. Por isso o nome é sempre
uma sugestão editável e depende da conferência e confirmação do usuário.

## Testes e resultados

```powershell
cd Backend
.\.venv\Scripts\python.exe -m pytest -q
cd ..
node --test Frontend/tests/unit.test.mjs Frontend/tests/nome-aluno.test.mjs
```

Resultado da validação: **168 aprovados, 1 ignorado e 0 reprovados no Pytest**;
**12 testes JavaScript e 3 cenários Chrome aprovados**. O teste Python ignorado
continua sendo o de Firestore Emulator sem configuração local. Permanece o
aviso preexistente do Starlette/TestClient. `pip check` passou sem conflitos.

Cobertura dos novos testes:

- Localização do campo nos dois PDFs reais e retorno vazio nos originais.
- Nome impresso sintético reconhecido pelo motor real, com requisições HTTP
  da biblioteca bloqueadas no teste para detectar downloads ou envio de imagens.
- Confiança baixa, ausência de texto, rótulos, números, NaN e falha do modelo.
- Nome acentuado na validação de texto (saída do modelo simulada nesse caso).
- Uso da retificação antes do OCR, preservação do upload e limpeza de temporários.
- Ausência de conexão com Firestore durante reconhecimento do nome.
- Preenchimento no frontend, edição manual, troca de captura, falha de rede
  e descarte de respostas atrasadas.
- Cenário Chrome com vídeo de canvas: captura, OCR real do backend, edição
  manual do nome, correção do mesmo arquivo e salvamento somente confirmado.

Para o cenário de navegador, mantenha o backend ativo e use a configuração
Playwright descrita em `interface-web.md`. Além de `cartao.png` e `multipla.png`,
gere `nome-impresso.png` na pasta definida em `QA_ARTIFACT_DIR` (a partir da
raiz do repositório; a pasta deve existir):

```powershell
@'
import os, sys
from pathlib import Path
import cv2
sys.path.insert(0, str(Path('Backend').resolve()))
from app.services.reconhecimento import carregar_imagem
imagem = carregar_imagem('Backend/tests/fixtures/local/Gabarito Prova AIB.pdf')
cv2.putText(imagem, 'MARIA DA SILVA', (300,265), cv2.FONT_HERSHEY_SIMPLEX,
            .8, (0,0,0), 2)
cv2.imwrite(str(Path(os.environ['QA_ARTIFACT_DIR'])/'nome-impresso.png'), imagem)
'@ | .\Backend\.venv\Scripts\python.exe -
node --test Frontend/tests/browser.test.cjs
```

Esse exemplo insere texto artificial em uma cópia em memória do cartão de
referência; não modifica o PDF nem representa uma amostra manuscrita real.
Na execução manual dessa amostra, o OCR retornou `MARIA DA SILVA` com score
**0,9996**. Outro cartão inteiramente sintético retornou o mesmo nome com
score **0,9953**. Os dois documentos reais originais retornaram nome nulo,
corretamente, pois seus campos estão vazios.

## Limitações e validação ainda necessária

**Não havia nomes manuscritos reais, nem amostras de cursiva, disponíveis.**
Não foi medida acurácia de nomes de alunos e não há comprovação de leitura
confiável em letra cursiva. Os resultados positivos relatados são de nomes
impressos sintéticos; os negativos em branco usam os PDFs reais.

É necessário testar com cartões consentidos e transcrição manual de referência,
cobrindo cursiva, letra de forma, acentos, nomes longos, caneta/lápis, rasuras,
sombras e foco. Meça erros de transcrição e falsos preenchimentos antes de
calibrar limiar ou ampliar aceitação. Para cursiva difícil, pode ser necessário
um modelo especializado ou ajustado com amostras apropriadas; não foi feito
treinamento nesta etapa.

Campos fora do modelo, folhas em paisagem, cabeça cortada, escrita sobre
linhas e caracteres pouco legíveis podem produzir ausência ou erro. OCR
local usa CPU e memória; a primeira inferência carrega os modelos, e acessos
ao motor são serializados. Falhas de leitura não bloqueiam a entrada manual.
Não houve teste de webcam USB física nem escrita cursiva real nesta entrega.

Sem commit ou push automático.
