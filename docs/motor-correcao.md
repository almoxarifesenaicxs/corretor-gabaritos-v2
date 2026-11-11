# Motor de correção — Issue 03

Implementado em `Backend/app/services/correcao.py`, sem dependências novas,
endpoints HTTP, banco de dados ou alterações no reconhecimento. A função
`corrigir_respostas(respostas, gabarito_oficial)` exige os dois argumentos.
Não abre PDFs, não interpreta imagens e nunca deduz um gabarito.

## Entradas

As duas entradas são dicionários com exatamente as chaves textuais `"1"` a
`"50"`. A ordem de inserção não importa. Português corresponde a 1–25 e
Matemática a 26–50.

O gabarito oficial associa cada chave a uma única alternativa maiúscula
`A`, `B`, `C`, `D` ou `E`. Não são aceitas listas, chaves inteiras, valores
nulos, questões ausentes/extras, espaços ou letras minúsculas.
O chamador deve fornecer explicitamente um gabarito cuja origem oficial
tenha sido verificada. O código valida sua estrutura, não sua autenticidade.
`Gabarito Prova AIB.pdf` é somente uma amostra de respostas preenchidas e
não é utilizado pelo motor como gabarito oficial.

As respostas seguem exatamente o contrato de `reconhecer_imagem` ou
`reconhecer_arquivo`. Cada questão tem os três campos obrigatórios:

```json
{"resposta": "A", "estado": "marcada", "alternativas": ["A"]}
```

| Estado | Resposta | Alternativas candidatas |
| --- | --- | --- |
| `marcada` | A–E | Lista com somente a resposta |
| `branco` | `null` | Lista vazia |
| `multipla` | `null` | Pelo menos duas alternativas |
| `duvidosa` | `null` | Pelo menos uma alternativa |

As candidatas devem ser letras A–E válidas e únicas. Uma questão duvidosa
pode ter várias candidatas sem que o motor escolha alguma. Campos extras,
tipos inválidos e estados inconsistentes são rejeitados. Entradas inválidas
levantam `ErroCorrecao`, uma subclasse de `ValueError`, antes de produzir
qualquer resultado. As entradas não são modificadas.

## Pontuação e saída

- `acertos`: questões marcadas cuja resposta coincide com a oficial.
- `erros`: questões marcadas cuja resposta diverge da oficial.
- `brancos`, `multiplas`, `duvidosas`: contagens separadas, não somadas a erros.
- `pendentes`: soma de múltiplas e duvidosas.
- `pontuacao`: um ponto por acerto; sem desconto por erro.
- `pontuacao_maxima`: 50 no resumo, 25 em cada disciplina.
- `percentual_acertos`: acertos / total de questões × 100, arredondado a
  duas casas. O denominador inclui brancos e pendências, sem renormalização.

As cinco contagens (acertos, erros, brancos, múltiplas e duvidosas) somam 50
no resumo e 25 por disciplina. As pendências não recebem pontos enquanto
aguardam conferência, nem são tratadas como erro definitivo. Se houver qualquer
pendência, `provisorio` será `true`; caso contrário será `false`, mesmo que
existam respostas em branco. `questoes_pendentes` lista suas chaves em ordem
numérica. Não há alteração automática de resposta ou fluxo de revisão manual;
após a conferência externa, o chamador pode corrigir as entradas e recalcular.

Exemplo de saída para 50 respostas corretas:

```json
{
  "provisorio": false,
  "resumo": {
    "acertos": 50,
    "erros": 0,
    "brancos": 0,
    "multiplas": 0,
    "duvidosas": 0,
    "pendentes": 0,
    "pontuacao": 50,
    "pontuacao_maxima": 50,
    "percentual_acertos": 100.0
  },
  "disciplinas": {
    "portugues": {
      "acertos": 25, "erros": 0, "brancos": 0,
      "multiplas": 0, "duvidosas": 0, "pendentes": 0,
      "pontuacao": 25, "pontuacao_maxima": 25, "percentual_acertos": 100.0
    },
    "matematica": {
      "acertos": 25, "erros": 0, "brancos": 0,
      "multiplas": 0, "duvidosas": 0, "pendentes": 0,
      "pontuacao": 25, "pontuacao_maxima": 25, "percentual_acertos": 100.0
    }
  },
  "questoes_pendentes": []
}
```

## Exemplo executável

A partir de `Backend`, execute este código em Python usando o ambiente virtual:

```python
from app.services.correcao import corrigir_respostas

# Gabarito fictício escolhido explicitamente para demonstrar a chamada.
# Não representa respostas oficiais de nenhuma prova real.
oficial = {str(i): "A" for i in range(1, 51)}
respostas = {
    str(i): {"resposta": "A", "estado": "marcada", "alternativas": ["A"]}
    for i in range(1, 51)
}
resultado = corrigir_respostas(respostas, oficial)
print(resultado["resumo"])  # 50 pontos, 100%

respostas["26"] = {
    "resposta": None, "estado": "multipla", "alternativas": ["A", "B"]
}
resultado = corrigir_respostas(respostas, oficial)
assert resultado["provisorio"] is True
assert resultado["questoes_pendentes"] == ["26"]
assert resultado["resumo"]["pontuacao"] == 49
assert resultado["resumo"]["percentual_acertos"] == 98.0
assert resultado["disciplinas"]["matematica"]["percentual_acertos"] == 96.0
```

Para integrar com o OpenCV, substitua apenas a construção de `respostas`
por `reconhecer_arquivo(caminho_do_cartao)`, importado de
`app.services.reconhecimento`. Forneça separadamente o gabarito oficial.

## Validação e limites

No PowerShell, a partir da raiz:

```powershell
cd Backend
.\.venv\Scripts\python.exe -m pytest -q
```

Na implementação da Issue 03: **63 aprovados, 0 ignorados, 0 reprovados**.
São 40 novos casos e os 23 anteriores, incluindo os PDFs locais disponíveis.
Permanece um aviso preexistente de depreciação do Starlette/TestClient.
Os testes locais são ignorados explicitamente se seus PDFs privados faltarem.

Os testes do motor cobrem as cinco categorias de resposta, pontuação por
disciplina, percentuais, limites 25/26, validação estrutural, preservação das
entradas, obrigatoriedade do gabarito e integração com uma imagem sintética
processada pelo OpenCV. Nenhuma expectativa usa o PDF preenchido como gabarito.

O motor não detecta enganos do reconhecimento que já tenham sido classificados
como marcação válida ou branco. Mantém as limitações de leitura documentadas
na Issue 02. Não há suporte a pesos, questões anuladas, alternativas fora de
A–E ou provas com quantidade diferente de 50 questões.
