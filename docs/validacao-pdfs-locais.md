# Validação com PDFs locais — Issue 02

Validação realizada em 30/10/2026, com Python 3.14.6. Os arquivos privados
estão em `Backend/tests/fixtures/local/`, pasta ignorada pelo Git. Nenhum PDF
foi modificado ou incluído no versionamento.

## Documentos e layout observado

Ambos os PDFs têm uma página A4 (595,32 × 841,92 pontos). A renderização é
feita a 150 dpi. Há duas tabelas: Português à esquerda e Matemática à direita.
Cada tabela possui uma coluna numérica, cinco alternativas A–E, cabeçalho
e 25 linhas de respostas. A numeração no papel reinicia em 1 em Matemática;
no retorno, Português ocupa 1–25 e Matemática 26–50.

As posições verticais das tabelas diferem entre os dois documentos. As marcas
do preenchido são X/x em células retangulares, frequentemente à esquerda do
centro da célula. O modelo anterior de círculos rejeitou ambos os documentos
(14 e 13 candidatos circulares, respectivamente). Alterar somente o limiar
de preenchimento de círculos não resolveria essa diferença estrutural.

## Ajuste implementado

Antes da detecção de círculos, o serviço procura tabelas por abertura
morfológica horizontal e vertical. Os elementos estruturantes medem
respectivamente largura/40 e altura/60 da imagem (mínimo de dez pixels),
para preservar segmentos de grade e eliminar a maior parte das letras.
Os blocos candidatos devem ter pelo menos 25% da largura e 30% da altura
da imagem. Não são usadas coordenadas absolutas dos documentos.

Projeções das linhas identificam sete limites verticais e 27 horizontais
por tabela. São exigidas duas tabelas lado a lado, passos regulares (variação
máxima de 15% da mediana), verticais presentes em pelo menos 90% da altura
e horizontais em 95% da largura. A primeira horizontal aceita 78%, pois o
cabeçalho não cobre a coluna numérica. As projeções inicialmente selecionam
linhas com pelo menos 70% da extensão. As duas tabelas podem diferir em até
1% da altura da imagem no alinhamento vertical.

A coluna numérica e o cabeçalho são descartados. Cada célula A–E é medida
com margem interna de 10% (mínimo de dois pixels), para excluir as linhas
sem exigir marcação no centro. Até 0,3% de tinta é branco; entre 0,3% e 1,5%
é duvidoso; a partir de 1,5% é marcado. Esses limites se aplicam somente às
tabelas. Os limiares e os testes do modelo circular foram preservados.
O serviço detecta presença de tinta; não interpreta a letra X nem faz OCR.
Nos arquivos inspecionados, as 250 células do branco tiveram taxa zero; no
preenchido, exatamente 50 células tiveram tinta, entre 3,45% e 5,56% da área
interna. As outras 200 tiveram taxa zero. Isso separa as marcas observadas
dos limiares adotados, sem estabelecer calibração para outras amostras.

## Reconhecimento conferido visualmente

`Gabarito em Branco.pdf`: todas as questões 1–50 retornaram
`{"resposta": null, "estado": "branco", "alternativas": []}`.

`Gabarito Prova AIB.pdf`: 50 respostas marcadas, zero em branco, zero múltiplas
e zero duvidosas. As alternativas abaixo são a transcrição visual usada como
expectativa independente nos testes. Não constituem gabarito oficial.

| Questão no bloco | Português (API 1–25) | Matemática (API 26–50) |
| --- | --- | --- |
| 1 | C | C |
| 2 | D | D |
| 3 | A | B |
| 4 | C | C |
| 5 | B | D |
| 6 | D | B |
| 7 | D | B |
| 8 | C | B |
| 9 | C | B |
| 10 | B | B |
| 11 | A | C |
| 12 | C | D |
| 13 | A | C |
| 14 | B | C |
| 15 | B | A |
| 16 | B | B |
| 17 | B | C |
| 18 | C | C |
| 19 | B | B |
| 20 | B | B |
| 21 | A | C |
| 22 | C | C |
| 23 | B | B |
| 24 | C | B |
| 25 | D | B |

## Testes e reprodução

```powershell
cd Backend
.\.venv\Scripts\python.exe -m pytest -q
# Apenas a integração local:
.\.venv\Scripts\python.exe -m pytest tests/test_pdfs_locais.py -q
```

Resultado da suíte completa: **23 aprovados, 0 ignorados, 0 reprovados**.
Inclui os 18 testes anteriores e cinco novos casos. Há um aviso de depreciação
preexistente do Starlette/TestClient sobre httpx. A API não foi modificada.

Os dois testes de referência comparam as 50 respostas com branco/transcrição
visual. Três casos adicionais alteram somente a imagem em memória do PDF
em branco: duas marcas (múltipla), pequeno resíduo (duvidosa), e remoção de
uma linha (erro de grade). Essas alterações controladas não são exemplos
de rasuras reais. Se o PDF necessário estiver ausente, o respectivo teste
é ignorado com motivo explícito; arquivos presentes e ilegíveis causam falha.

## Limitações e revisão manual

A validação cobre estes dois PDFs digitais. Não comprova desempenho em fotos,
escaneamentos, marcas manuscritas, perspectiva, sombras ou outros layouts.
Os limiares de tinta são heurísticos e ainda precisam de amostras variadas.
Não há nota, correção contra resposta oficial ou extração de dados pessoais.

Nenhuma das 50 leituras do preenchido exigiu revisão nesta comparação visual.
Leituras `multipla` ou `duvidosa` sempre retornam resposta nula e devem ser
revisadas manualmente. Erros de grade exigem nova captura ou verificação do
layout. Marcas apagadas, muito pequenas, próximas da borda, ruído, carimbos
e rasuras podem passar pelos limiares como branco ou marcação: mesmo uma
leitura `marcada` não é garantia de intenção do candidato.

A detecção confirma a geometria; não lê os rótulos Português, Matemática ou
A–E. A ordem é uma premissa deste modelo. Tabelas de mesma geometria com outra
ordem de disciplinas ou alternativas precisam de revisão antes do uso.
