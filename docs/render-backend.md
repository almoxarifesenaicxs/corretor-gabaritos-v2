# Preparação do backend para Render — Etapa 10

Preparação somente: nenhum serviço criado, deploy executado ou produção ativada.
O `render.yaml` mantém `APP_AMBIENTE=local` e deploy automático desativado.
Importar um Blueprint pode iniciar sua primeira implantação mesmo com
`autoDeployTrigger: off`: **não importar este arquivo nesta etapa**.

## Python e dependências

Python **3.14.6**, fixado em `Backend/.python-version` e em `PYTHON_VERSION` no
Blueprint. É a versão já utilizada pela suíte local, evitando trocar o runtime
sem necessidade. A Render permite fixar uma versão completa publicada.

Auditoria em 11/11/2026: os 42 pins de `Backend/requirements.txt` aceitam 3.14.6
e têm wheels universais ou Linux x86_64 compatíveis. A resolução pip em dry-run
para CPython 3.14.6, manylinux_2_28/manylinux2014/manylinux2010, exclusivamente
binária, terminou sem conflito, incluindo dependências transitivas. Nenhuma
dependência foi instalada/atualizada. `requirements.txt` foi preservado.

| Biblioteca | Versão | Distribuição principal Linux |
| --- | --- | --- |
| FastAPI | 0.162.0 | Python puro |
| OpenCV headless | 5.0.0.93 | abi3; manylinux 2.17/2.28 |
| PyMuPDF | 2.0 | abi3 a partir de CPython 3.11; manylinux 2.28 |
| NumPy | 2.5.4 | CPython 3.14; manylinux 2.27/2.28 |
| RapidOCR | 3.10.0 | Wheel universal, modelos incluídos |
| ONNX Runtime | 1.31.1 | CPython 3.14; manylinux 2.28 |

O alvo é Linux x86_64 com glibc >= 2.28, não Alpine/musl. A simulação feita no
Windows verifica disponibilidade e resolução, mas não executa bibliotecas Linux;
marcadores condicionais de ambiente também precisam ser confirmados no Linux.
O build futuro executará `pip check` e um smoke test de importação, PNG, PDF e OCR.

OpenCV headless evita a dependência da interface gráfica. PyMuPDF 2.0 declara
dependências de layout/LLM; não removê-las apenas por não haver importação direta
na aplicação. `colorama` e ferramentas de teste permanecem para preservar o
ambiente atual. As dependências transitivas ainda não estão integralmente fixadas
nem acompanhadas de hashes: um lock Linux completo é melhoria futura de
reprodutibilidade. Rever atualizações de segurança antes da implantação.

## Modelos OCR

O wheel público `rapidocr-3.10.0-py3-none-any.whl` foi inspecionado em memória.
Ele contém os três arquivos exigidos pelo código, também presentes localmente:

| Modelo | Bytes |
| --- | ---: |
| `PP-OCRv6_det_small.onnx` | 9.929.594 |
| `PP-OCRv6_rec_small.onnx` | 21.234.383 |
| `ch_ppocr_mobile_v2.0_cls_mobile.onnx` | 585.532 |

São aproximadamente 30,3 MiB em disco, não uma estimativa do custo em RAM.
O build verifica carregamento e uma inferência CPU com esses modelos. Modelos
ausentes/corrompidos fazem o build falhar. Não há download automático de modelos
em runtime; o preenchimento manual do nome continua disponível se o OCR falhar
durante o uso. Nenhum modelo foi adicionado ao repositório.

## Configuração e comandos

Raiz do serviço: `Backend`. Build:

```sh
python -m pip install --only-binary=:all: -r requirements.txt && python -m pip check && python scripts/verificar_runtime.py
```

Inicialização futura:

```sh
python -m uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --no-proxy-headers --workers 1
```

O shell expande `PORT`, fornecida pela Render. Não fixar porta de desenvolvimento.
O build não importa `app.main`, não inicializa autenticação, não abre Firestore e
não exige a pasta Frontend. O runtime usa `SERVIR_FRONTEND=false`.

| Variável | Preparação / uso futuro |
| --- | --- |
| `PYTHON_VERSION` | `3.14.6` |
| `PYTHONDONTWRITEBYTECODE` / `PYTHONUNBUFFERED` | `1` / `1` |
| `PORT` | Fornecida pela Render |
| `APP_AMBIENTE` | `local` nesta preparação; `producao` somente após autorização futura |
| `SERVIR_FRONTEND` | `false` |
| `FIRESTORE_MODO` | Preenchimento manual; produção exige `real` |
| `FIREBASE_PROJECT_ID` | Projeto real autorizado, sem `demo-` em produção |
| `ADMIN_UIDS` | UIDs explicitamente autorizados |
| `CORS_ORIGINS` | Origens HTTPS exatas |
| `ALLOWED_HOSTS` | Hosts públicos exatos da API |
| `GOOGLE_APPLICATION_CREDENTIALS` | Caminho do secret file, por exemplo `/etc/secrets/firebase-admin.json` |
| `INTEGRIDADE_CHAVE` | Segredo estável de 32 bytes em 64 caracteres hexadecimais |

Os campos a preencher estão com `sync: false`, sem valores privados. O arquivo de
credenciais deverá ser provisionado como Secret File, fora do Git. Não definir
variáveis de emulador em produção nem `FORWARDED_ALLOW_IPS=*`. Não habilitar proxy
headers no Uvicorn. O TLS externo dependerá da borda Render, conforme Etapa 09.

O modo local deste Blueprint rejeita tráfego remoto, inclusive health checks com
Host externo. Portanto, o Blueprint é deliberadamente uma preparação, não uma
configuração pronta para importar. A ativação futura exige revisar o arquivo e
seus valores, incluindo o modo de ambiente; não se deve contornar a proteção
para fazer o health check passar.

## Saúde e prontidão

`GET /api/health` informa somente que a API responde: não exige token nem abre
conexão com Firestore. As barreiras de Host/Origin e modo local continuam valendo.
Os testes verificam saúde sem Frontend e sem chamada ao validador de tokens/banco.
A inicialização de produção carrega credenciais, mas não consulta documentos.

Não foi criado outro endpoint de prontidão nesta etapa: a configuração crítica
já falha antes da inicialização e o build testa bibliotecas e OCR. Saúde não
certifica IAM, existência da base, disponibilidade do Firebase ou precisão OCR.
Antes da publicação, validar essas dependências com um fluxo administrativo em
ambiente de homologação. Se necessário, adicionar posteriormente uma verificação
de prontidão limitada, com timeout/cache e sem consultar o banco a cada health
check; evitar transformar indisponibilidade externa em reinicializações contínuas.

## Temporários, memória e CPU

As três rotas que gravam arquivos usam `TemporaryDirectory` com contexto: correção,
reconhecimento de gabarito e OCR do nome. Novos testes verificam remoção após
sucesso e exceções. Arquivos enviados não são persistidos no Firestore. Não é
necessário disco persistente para esse fluxo. Encerramento forçado/SIGKILL pode
impedir a limpeza Python; o filesystem temporário deve permanecer efêmero.

Limites mantidos: arquivo 10 MiB, envelope multipart 11 MiB, JSON 128 KiB,
12 milhões de pixels, dimensão máxima 6000, duas operações de processamento e
quatro recepções por processo. Uma imagem BGR de 12 MP ocupa cerca de 34,3 MiB;
cópias, máscaras, PDF, base64 e tensores OCR aumentam esse consumo.

Medição indicativa no Windows/Python 3.14.6, processo isolado:
- Duas binarizações simultâneas de imagens sintéticas 12 MP: 0,18 s de parede,
  0,59 s de CPU, RSS amostrado de 125,8 MiB para pico de 280,1 MiB.
- Carregamento OCR e uma inferência sintética: 0,82 s; RSS final de 201,3 MiB.
- OpenCV informou 8 threads; OCR configura 2 threads intra-op e 1 inter-op e
  serializa suas chamadas com lock.

Isso não é benchmark da Render, nem pico de um fluxo completo. O Blueprint sugere
1 CPU/2 GiB (`1c-2g`) como ponto inicial de homologação, não garantia de capacidade.
Nenhum plano foi contratado. Não assumir que 512 MiB suportam imagens grandes,
concorrência e OCR. Medir RSS, latência e saturação no Linux antes de reduzir RAM
ou aumentar workers. Threads internas podem disputar CPU; ajustes futuros exigem
medição, sem elevar os limites de segurança automaticamente.

## Validação realizada e pendências

- `pip check` no ambiente existente: sem conflitos.
- Dry-run Linux: resolução concluída, nenhuma instalação.
- Smoke test local de runtime: PNG, PDF e OCR concluídos.
- Testes de configuração e limpeza de temporários incluídos na suíte Python.
- Playwright continua ausente; cenários de navegador não executam.
- Falta executar build/smoke tests em Linux real e homologar Firebase/Render.
- O formato YAML é verificado localmente; não houve validação autenticada na API Render.

Fontes: [Python na Render](https://render.com/docs/python-version),
[Blueprint](https://render.com/docs/blueprint-spec),
[metadados PyPI RapidOCR](https://pypi.org/pypi/rapidocr/3.10.0/json),
[ONNX Runtime](https://pypi.org/pypi/onnxruntime/1.31.1/json),
[PyMuPDF](https://pypi.org/pypi/pymupdf/2.0/json).
