# Reconhecimento de gabaritos — Issue 02

O serviço fica em `Backend/app/services/reconhecimento.py`. Não há novos
endpoints, cálculo de notas, OCR ou persistência. A API existente foi preservada.

A validação posterior com os dois PDFs reais está registrada em
[Validação com PDFs locais](validacao-pdfs-locais.md), incluindo as 50 marcações
conferidas e os parâmetros da detecção de tabelas retangulares.

## Executar localmente

No PowerShell, a partir da raiz do repositório:

```powershell
cd Backend
# Apenas se o ambiente ainda não existir:
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -c "from app.services.reconhecimento import reconhecer_arquivo; import json; print(json.dumps(reconhecer_arquivo('cartao.pdf'), ensure_ascii=False, indent=2))"
```

Substitua `cartao.pdf` pelo caminho do arquivo. Também são aceitos PNG, JPG e JPEG.
Para iniciar a API existente: `.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload`.

## Fluxo e contrato

`carregar_imagem(caminho)` retorna uma matriz NumPy BGR. PDFs têm somente a
primeira página renderizada, a 150 dpi e sem transparência. Imagens são
decodificadas pelo OpenCV, inclusive em caminhos com acentos.
`binarizar` converte para cinza e aplica Otsu com tinta branca sobre fundo preto.
`identificar_tabelas` procura primeiro duas tabelas retangulares de respostas.
Se não houver tabelas candidatas, `identificar_grade` procura o modelo circular
por contornos. Tabelas candidatas com geometria inválida geram erro.
`reconhecer_imagem` mede a tinta nas células ou no centro dos círculos.
`reconhecer_arquivo` reúne o carregamento e o reconhecimento.

O resultado contém exatamente as chaves `"1"` a `"50"`. Exemplo de entradas:

```json
{
  "1": {"resposta": "A", "estado": "marcada", "alternativas": ["A"]},
  "2": {"resposta": null, "estado": "branco", "alternativas": []},
  "3": {"resposta": null, "estado": "multipla", "alternativas": ["B", "E"]},
  "4": {"resposta": null, "estado": "duvidosa", "alternativas": ["C"]}
}
```

`alternativas` lista os candidatos com tinta acima do limiar de branco; não
representa respostas confirmadas. Uma marca forte junto de uma parcial também
produz `duvidosa`. Duas marcas fortes produzem `multipla`. Somente `marcada`
possui `resposta` diferente de `null`.

Arquivos ausentes levantam `FileNotFoundError`. Formatos não suportados,
arquivos corrompidos, PDFs protegidos/sem páginas e grades incompatíveis
levantam `ErroLeitura`. Grade inválida não retorna respostas parciais.

## Modelo circular sintético e parâmetros

Na implementação inicial, sem o cartão verdadeiro, adotou-se esta grade
sintética. Ela continua suportada; os PDFs reais usam tabelas, descritas
no documento de validação:

- Dois blocos lado a lado, cada um com 25 linhas e cinco círculos A–E.
  O esquerdo contém Português (1–25); o direito Matemática (26–50).
- As linhas dos dois blocos devem estar alinhadas, com espaçamento regular.
  A distância entre blocos deve ser pelo menos 1,5 vezes o passo das alternativas.
- São exigidos exatamente 250 contornos circulares externos. A largura deve
  estar entre 0,6% e 4% da menor dimensão da imagem, a razão largura/altura
  entre 0,8 e 1,2 e a circularidade ser pelo menos 0,68. Esse último limite
  tolera os degraus de contorno da rasterização do PDF sintético.
- Raios podem variar até 25% da mediana. Colunas, linhas e passos regulares
  toleram desvios de até 0,6 raio. Passos internos e verticais devem medir
  pelo menos 2,5 raios. Esses limites impedem agrupamentos arbitrários.
- A medição usa o disco central de 60% do raio para excluir a borda impressa.
  Até 20% de tinta é branco; acima de 20% e abaixo de 55% é duvidoso;
  a partir de 55% é preenchido. São heurísticas provisórias, sem calibração real.

Não há coordenadas absolutas da página no serviço. As coordenadas dos testes
apenas constroem o modelo sintético, que também é testado redimensionado.

## Limitações da validação sintética inicial

Os testes em `test_reconhecimento.py` usam cartões sintéticos gerados em memória
e arquivos temporários. Isoladamente, não demonstram funcionamento em cartões
reais. Os testes locais adicionais ficam em `test_pdfs_locais.py`. Os sintéticos cobrem PDF com duas
páginas (somente a primeira é lida), PDF protegido, imagens válidas e inválidas,
quatro estados de resposta, numeração, mudança de escala e grades inválidas.
Os testes originais da API fazem parte da mesma suíte.

Não há correção de perspectiva, rotação, sombras ou iluminação desigual.
Otsu pressupõe contraste suficiente. Bordas retangulares envolvendo a grade,
outros círculos na página, rasuras que alterem o contorno e círculos ausentes
podem causar rejeição. Marcas muito claras ou fora do miolo podem parecer branco;
os estados são heurísticos e não probabilidades de confiança.

Os dois PDFs reais permitiram confirmar a disposição dos blocos e implementar
a seleção das tabelas. Ainda é necessário calibrar os limiares com exemplos
de lápis, caneta, rasuras, múltiplas marcações e digitalizações/fotos reais.
A seleção de círculos permanece limitada ao modelo sintético aqui descrito;
as condições e limitações das tabelas estão no documento de validação.
