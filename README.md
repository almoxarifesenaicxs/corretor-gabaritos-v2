# Corretor Automático de Gabaritos V2

Sistema de correção automática de provas por meio de processamento de imagens, desenvolvido para identificar respostas marcadas em cartões de gabarito, compará-las com um gabarito oficial e calcular os resultados por disciplina e da avaliação completa.

O sistema utiliza visão computacional para analisar cartões de respostas digitalizados, reduzindo a necessidade de conferência manual. Questões com marcações múltiplas ou leituras duvidosas são sinalizadas para revisão, evitando a atribuição automática de respostas sem evidência suficiente.

Este documento apresenta a arquitetura, as funcionalidades implementadas, as instruções de execução e o planejamento do sistema. As informações refletem as etapas de desenvolvimento relatadas até a Issue 03, não constituindo homologação do sistema completo.

---

## Tecnologias e estrutura

**Backend**
- Python 3.14.6
- FastAPI — desenvolvimento da API REST.
- OpenCV — processamento de imagens e identificação de marcações.
- PyMuPDF — leitura e conversão de arquivos PDF.
- NumPy — manipulação de matrizes e imagens.
- Pytest — testes automatizados.

**Frontend**
- HTML5 — estrutura das páginas.
- CSS3 — estilização da interface.
- JavaScript — interatividade e integração futura com a API.

**Banco de dados planejado**
- Firebase Cloud Firestore — persistência futura de provas, gabaritos e resultados.

**Versionamento**
- Git e GitHub.

### Estrutura do projeto

```text
corretor-gabaritos-v2/
│
├── Backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── routes/
│   │   ├── services/
│   │   │   ├── reconhecimento.py
│   │   │   └── correcao.py
│   │   ├── models/
│   │   └── database/
│   │
│   ├── tests/
│   │   ├── test_api.py
│   │   ├── test_reconhecimento.py
│   │   ├── test_pdfs_locais.py
│   │   ├── test_correcao.py
│   │   └── fixtures/
│   │       └── local/
│   │
│   └── requirements.txt
│
├── Frontend/
│   ├── index.html
│   ├── pages/
│   ├── css/
│   │   └── style.css
│   └── js/
│       └── script.js
│
├── docs/
│   ├── reconhecimento.md
│   ├── validacao-pdfs-locais.md
│   └── motor-correcao.md
│
├── .gitignore
└── README.md
```

A organização separa o processamento, as regras de correção, as rotas da API e a interface web.

Os diretórios de modelos, banco de dados e frontend estão preparados para as próximas etapas e não devem ser considerados funcionalidades completas.

---

## Pré-requisitos

Para executar o projeto localmente, são necessários:

- Python 3.14.6 ou versão compatível com as dependências.
- Git.
- PowerShell, para os comandos apresentados.
- VS Code ou outro editor de código.
- Acesso à internet para instalar inicialmente as bibliotecas.

Não é necessário configurar Firebase, Node.js ou SQL Server para executar as funcionalidades atualmente implementadas.

## 1. Clonar o repositório

Abra o PowerShell no diretório desejado e execute:

```powershell
git clone https://github.com/JoanaCostah/corretor-gabaritos-v2.git
cd corretor-gabaritos-v2
```

Selecione a branch que contém as funcionalidades a serem executadas:

```powershell
git switch develop
git pull --ff-only origin develop
```

A branch `main` pode não conter as funcionalidades mais recentes durante o desenvolvimento.

## 2. Preparar o backend

A partir da raiz do projeto:

```powershell
cd Backend
python --version
python -m venv .venv
```

Instale as dependências utilizando diretamente o interpretador do ambiente virtual:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Essa abordagem evita depender da ativação do ambiente virtual no PowerShell.

O arquivo `Backend/requirements.txt` mantém as dependências utilizadas pelo backend.

Não é necessário instalar cada biblioteca manualmente quando o arquivo já está atualizado.

## 3. Executar a API REST

Na pasta `Backend/`, execute:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Por padrão, a API será disponibilizada em:

- API: http://127.0.0.1:8000/
- Health: http://127.0.0.1:8000/api/health
- Swagger: http://127.0.0.1:8000/docs

A rota de health permite verificar se a API responde, mas não confirma o funcionamento do reconhecimento e da correção.

**Situação atual:** a API básica está implementada. Os serviços de reconhecimento e correção ainda não estão integrados a um endpoint de envio e correção de provas.

Mantenha o terminal aberto enquanto utilizar a API.

## 4. Reconhecimento de cartões com OpenCV

O módulo `Backend/app/services/reconhecimento.py` realiza a leitura e identificação das alternativas marcadas.

### Formatos de entrada

O reconhecimento aceita:

- PDF.
- JPG.
- PNG.

Para PDFs, o processamento utiliza a primeira página do documento.

O modelo inicialmente validado contém 50 questões, divididas em:

| Disciplina | Questões | Alternativas |
|---|---|---|
| Português | 1 a 25 | A, B, C, D, E |
| Matemática | 26 a 50 | A, B, C, D, E |
| Total | 50 | Cinco por questão |

### Processamento das imagens

O fluxo de reconhecimento compreende:

1. Leitura e conversão do arquivo em imagem.
2. Conversão para escala de cinza.
3. Aplicação de binarização.
4. Identificação da estrutura do cartão de respostas.
5. Localização das células ou áreas de marcação.
6. Análise da quantidade de tinta.
7. Identificação da alternativa selecionada.
8. Classificação de respostas sem marcação ou inconsistentes.

A implementação contempla cartões com células retangulares e marcações em X, preservando o suporte anterior ao reconhecimento circular.

### Estados de reconhecimento

| Estado | Significado |
|---|---|
| `marcada` | Uma alternativa identificada |
| `branco` | Nenhuma alternativa identificada |
| `multipla` | Mais de uma alternativa marcada |
| `duvidosa` | Leitura sem confiança suficiente |

Respostas múltiplas ou duvidosas não devem receber uma alternativa presumida.

### Validação com documentos reais

Foram utilizados dois arquivos de referência:

**Gabarito em Branco.pdf**
- 50 questões identificadas.
- 50 respostas classificadas como em branco.

**Gabarito Prova AIB.pdf**
- 50 alternativas reconhecidas.
- Marcações conferidas visualmente.
- Nenhuma questão múltipla ou duvidosa no documento testado.

O documento preenchido é utilizado apenas como referência de reconhecimento, não como gabarito oficial.

Os arquivos locais de referência devem permanecer em:

```text
Backend/tests/fixtures/local/
```

Essa pasta deve estar ignorada pelo Git para evitar o envio de documentos privados ao repositório.

A validação realizada não comprova o desempenho com fotografias, sombras, rasuras, rotações ou outras variações de captura.

Mais informações estão disponíveis em `docs/reconhecimento.md` e `docs/validacao-pdfs-locais.md`.

## 5. Motor de correção automática

O módulo `Backend/app/services/correcao.py` realiza a comparação das respostas reconhecidas com um gabarito oficial informado explicitamente.

O motor é independente da API REST, do frontend e do banco de dados.

### Regras de correção

- A prova contém 50 questões.
- Cada questão vale um ponto.
- Português possui pontuação máxima de 25 pontos.
- Matemática possui pontuação máxima de 25 pontos.
- A pontuação máxima geral é de 50 pontos.
- O gabarito oficial deve conter exatamente 50 alternativas válidas.
- As alternativas permitidas são A, B, C, D e E.

O resultado contempla:

- Acertos.
- Erros.
- Questões em branco.
- Marcações múltiplas.
- Leituras duvidosas.
- Pontuação por disciplina.
- Pontuação geral.
- Percentuais de acerto.
- Pendências de conferência.

### Resultados provisórios

Questões múltiplas ou duvidosas permanecem pendentes de revisão.

Enquanto houver pendências, o resultado será identificado como provisório.

Exemplo:

| Indicador | Resultado |
|---|---|
| Acertos | 49 |
| Questões múltiplas | 1 |
| Pontuação contabilizada | 49/50 |
| Percentual | 98% |
| Situação | Provisório |

A pontuação contabilizada não deve ser confundida com uma nota definitivamente confirmada quando existirem pendências.

### Gabarito oficial

O sistema exige o fornecimento explícito das respostas corretas.

O arquivo `Gabarito Prova AIB.pdf` não é utilizado automaticamente como chave oficial.

A autenticidade do gabarito deverá ser garantida por um processo externo ao motor nesta etapa.

As regras e os contratos completos estão documentados em `docs/motor-correcao.md`.

## 6. Executar os testes automatizados

Na pasta `Backend/`, execute:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

De acordo com o relatório de conclusão da Issue 03:

| Etapa | Testes aprovados |
|---|---:|
| Issue 02 — API e reconhecimento | 23 |
| Issue 03 — Novos testes do motor | 40 |
| Total após a Issue 03 | 63 |

**Último resultado relatado:** 63 aprovados, 0 ignorados e 0 reprovados.

Permaneceu um aviso preexistente relacionado ao Starlette/TestClient.

Os testes verificam os comportamentos implementados, mas não substituem uma validação completa da aplicação web com usuários e documentos variados.

## 7. Estrutura de desenvolvimento com Git

O projeto utiliza branches separadas para organizar a implementação.

| Branch | Responsabilidade |
|---|---|
| `main` | Versão estável |
| `develop` | Integração das funcionalidades |
| `feature/01-api-basica` | API REST inicial |
| `feature/02-opencv` | Reconhecimento de respostas |
| `feature/03-motor-correcao` | Motor de correção |

As Issues 01 e 02 foram integradas à `develop`.

A Issue 03 foi implementada, mas sua integração deve ser confirmada no histórico do Git, pois o último relatório do Codex foi emitido antes do commit e do push.

### Fluxo recomendado

Para iniciar uma nova funcionalidade, utilize a `develop` atualizada:

```powershell
git switch develop
git pull --ff-only origin develop
git switch -c feature/nome-da-funcionalidade
```

Após a implementação e validação, revise os arquivos alterados, crie o commit e envie a branch ao GitHub.

A integração deverá ocorrer após revisão, preferencialmente por Pull Request.

Não desenvolva funcionalidades diretamente na `main`.

## 8. Próximas etapas do desenvolvimento

| Issue | Funcionalidade | Situação |
|---|---|---|
| 01 | API REST básica | Implementada |
| 02 | Reconhecimento OpenCV | Implementada e validada |
| 03 | Motor de correção | Implementada e testada |
| 04 | API de envio e correção de provas | Planejada |
| 05 | Persistência com Firebase | Planejada |
| 06 | Interface web | Planejada |

### Issue 04 — Integração com API REST

Integrar o reconhecimento OpenCV e o motor de correção ao FastAPI.

A API deverá permitir o envio de arquivos, o fornecimento do gabarito oficial e a obtenção do resultado em JSON.

### Issue 05 — Persistência com Firebase

Implementar o armazenamento de provas, gabaritos oficiais e resultados de correção utilizando Cloud Firestore.

A persistência deverá preservar os resultados e permitir consultas posteriores.

### Issue 06 — Interface web

Desenvolver inicialmente três áreas:

- **Provas:** cadastro das avaliações e dos gabaritos oficiais.
- **Correção:** envio dos cartões de respostas e apresentação de pendências.
- **Resultados:** consulta das correções e notas.

O frontend consumirá os endpoints disponibilizados pela API REST.

## 9. Problemas frequentes

| Sintoma | Verificação |
|---|---|
| Python não reconhecido | Confirmar instalação e caminho do interpretador |
| Ambiente virtual incorreto | Utilizar `Backend/.venv/Scripts/python.exe` |
| Erro ao importar FastAPI | Instalar as dependências do `requirements.txt` |
| API não inicia | Conferir a pasta atual e o comando Uvicorn |
| Porta 8000 ocupada | Encerrar o processo anterior ou definir outra porta |
| Swagger indisponível | Confirmar que a API está em execução |
| PDF não reconhecido | Conferir formato, integridade e compatibilidade do cartão |
| Respostas incorretas | Verificar grade, qualidade do arquivo e parâmetros de detecção |
| Questões duvidosas | Realizar conferência manual |
| Gabarito inválido | Informar exatamente 50 alternativas válidas |
| Testes não encontrados | Executar Pytest a partir de `Backend/` |
| Código não aparece na `main` | Conferir se a funcionalidade está na `develop` ou em uma branch de feature |

## 10. Limitações atuais

O sistema ainda está em desenvolvimento.

As principais limitações são:

- Reconhecimento validado apenas com os dois PDFs digitais de referência.
- Ausência de validação ampla com fotografias e cartões danificados.
- Modelo fixo de 50 questões com alternativas A–E.
- Motor de correção sem autenticação do gabarito oficial.
- Ausência de endpoint integrado para envio e correção de provas.
- Persistência Firebase ainda não implementada.
- Interface web ainda não integrada aos serviços.
- Resultados com questões pendentes exigem conferência manual.

A conclusão dos testes automatizados não equivale à homologação do sistema completo.

## Referências

- [Repositório GitHub](https://github.com/JoanaCostah/corretor-gabaritos-v2)
- `docs/reconhecimento.md` — Funcionamento do reconhecimento.
- `docs/validacao-pdfs-locais.md` — Resultados da validação com PDFs.
- `docs/motor-correcao.md` — Regras e contratos da correção.

---

## Considerações finais

O Corretor Automático de Gabaritos V2 está sendo desenvolvido de forma modular e incremental, com separação entre reconhecimento de respostas, regras de correção, API REST, persistência e interface web.

Até a Issue 03, o projeto possui mecanismos implementados e testados para reconhecer respostas em cartões compatíveis e calcular resultados com base em um gabarito oficial informado.

As próximas etapas transformarão esses componentes em uma aplicação web integrada, com armazenamento dos resultados e utilização por meio de uma interface acessível ao usuário.
