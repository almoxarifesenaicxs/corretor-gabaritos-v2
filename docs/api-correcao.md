# API de correção — Issue 04

`POST /api/correcoes/processar` integra `reconhecer_arquivo` e
`corrigir_respostas`, sem duplicar reconhecimento ou regras de pontuação.
As rotas `GET /` e `GET /api/health` continuam disponíveis.

## Requisição

Use `multipart/form-data` com dois campos obrigatórios:

| Campo | Tipo | Conteúdo |
| --- | --- | --- |
| `arquivo` | Arquivo | PDF, PNG, JPG ou JPEG, até **10 MiB (10.485.760 bytes)** |
| `gabarito` | Texto | Objeto JSON com exatamente as chaves `"1"` a `"50"`, cada uma contendo uma alternativa A–E maiúscula |

A validação do gabarito é compartilhada com o motor por `validar_gabarito`.
JSON malformado, chaves repetidas, estrutura incompleta, letras inválidas e
questões extras são rejeitados. O gabarito deve ser fornecido explicitamente;
o PDF preenchido de exemplo nunca é utilizado automaticamente como oficial.

A extensão é comparada sem diferenciar maiúsculas e minúsculas. A assinatura
básica deve corresponder à extensão: `%PDF-`, assinatura PNG ou início JPEG.
O MIME informado pelo cliente não determina o formato. Assinatura válida não
garante integridade: a decodificação e a detecção da grade são realizadas pelo
serviço existente. Apenas a primeira página do PDF é processada.

O tamanho disponibilizado pelo multipart é verificado, e a leitura é limitada
a 10 MiB + 1 byte para também rejeitar excesso sem depender desse metadado.
O limite é do arquivo, não do envelope multipart. A análise multipart do
framework ocorre antes da rota e pode usar armazenamento temporário próprio;
este limite não representa uma interrupção da conexão durante a recepção.

## Resultado e erros

Sucesso retorna HTTP **200** com o resultado exato do motor:
`provisorio`, `resumo`, `disciplinas` e `questoes_pendentes`.
Os contadores, pontos e percentuais mantêm o contrato descrito em
[motor-correcao.md](motor-correcao.md). O motor não fornece detalhes de todas
as questões, portanto o endpoint não acrescenta esse campo.

Múltiplas e duvidosas geram resultado provisório com HTTP 200: são resultados
de negócio válidos, pendentes de conferência. Brancos não tornam o resultado
provisório. Português corresponde a 1–25 e Matemática a 26–50.

| HTTP | Situação |
| --- | --- |
| 400 | Arquivo enviado está vazio |
| 413 | Arquivo excede 10 MiB |
| 415 | Extensão não suportada ou assinatura incompatível |
| 422 | Campo obrigatório ausente ou de tipo incompatível; gabarito inválido; arquivo não decodificável, PDF protegido ou grade inválida |
| 500 | Falha inesperada de processamento ou de I/O |

Os erros da rota retornam `{"detail": "mensagem"}`. A validação automática
dos campos obrigatórios retorna o formato padrão FastAPI, com lista em
`detail`. Mensagens de falha do processamento não incluem rastreamentos,
caminhos privados ou mensagens internas das bibliotecas.

Após checar o upload e validar o gabarito, a rota grava o conteúdo em um
diretório temporário exclusivo, com nome fixo e extensão validada, ignorando
o nome original na gravação. O contexto remove os temporários no sucesso
e na falha. Não há armazenamento permanente. PDFs são abertos por bytes para
evitar bloqueios de arquivos no Windows quando sua decodificação falha.
A rota síncrona executa no pool de threads do FastAPI.

## Executar e chamar localmente

No PowerShell, a partir da raiz:

```powershell
cd Backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Em outro terminal, a partir de `Backend`, uma chamada Python com `httpx`:

```python
import json
import httpx

# Exemplo fictício de gabarito explícito, sem relação com uma prova real.
oficial = {str(i): "A" for i in range(1, 51)}
with open("cartao.pdf", "rb") as arquivo:
    resposta = httpx.post(
        "http://127.0.0.1:8000/api/correcoes/processar",
        files={"arquivo": ("cartao.pdf", arquivo, "application/pdf")},
        data={"gabarito": json.dumps(oficial)},
        timeout=60,
    )
print(resposta.status_code)
print(resposta.json())
```

O formulário também pode ser usado em `http://127.0.0.1:8000/docs`.
Substitua o exemplo fictício pelo gabarito oficial correto antes do uso real.

## Testes e limites

```powershell
cd Backend
.\.venv\Scripts\python.exe -m pytest -q
```

A suíte inclui os 63 testes anteriores e testes HTTP de upload PDF/imagens,
resposta completa com pendências, ausência de campos, formato, assinatura,
arquivo vazio, corrupção, PDF protegido, grade ausente, gabarito inválido,
limite de tamanho, falha inesperada e remoção dos temporários inclusive nas
falhas. Os cartões HTTP válidos são sintéticos; os testes locais existentes
continuam validando os dois PDFs de referência quando disponíveis.

Resultado nesta implementação: **91 aprovados, 0 ignorados e 0 reprovados**
(28 novos casos). Permanece um aviso preexistente do Starlette/TestClient.

Foi adicionada somente a dependência `python-multipart==0.0.33`, necessária
para receber formulários com upload. Não há Firebase, autenticação, front-end,
fila de processamento ou persistência. Permanecem as limitações dos serviços
de leitura e correção: os limites de bytes não limitam a quantidade de pixels
descomprimidos, o tempo de processamento ou a concorrência. A validação de
assinatura é básica, não uma análise de segurança de documentos.
