# Corretor Automático de Gabaritos V2

Sistema web desenvolvido para automatizar a correção de avaliações escolares utilizando visão computacional, processamento de imagens e comparação automática de respostas.

A aplicação foi planejada para funcionar em um computador com uma câmera USB ou webcam, permitindo capturar cartões de respostas diretamente pelo navegador, identificar as alternativas marcadas, calcular as notas e armazenar os resultados.

O objetivo é oferecer uma solução simples, rápida e organizada para o cadastro de avaliações e a correção de provas.

## Tecnologias

**Backend**
- Python 3.14.6
- FastAPI — API REST
- OpenCV — reconhecimento de respostas
- PyMuPDF — processamento de PDFs
- NumPy — processamento de imagens
- Firebase Cloud Firestore — persistência
- Pytest — testes automatizados

**Frontend**
- HTML5
- CSS3
- JavaScript
- API MediaDevices — acesso à webcam pelo navegador

**Versionamento**
- Git e GitHub

## Funcionalidades do sistema

A interface terá somente duas abas principais.

### 1. Avaliações

Responsável pelo cadastro das avaliações e dos respectivos gabaritos oficiais.

O usuário poderá:

1. Informar o nome da avaliação.
2. Ativar a câmera USB ou webcam.
3. Posicionar o cartão com as respostas oficiais na área indicada.
4. Capturar a imagem diretamente pelo navegador.
5. Visualizar as alternativas reconhecidas pelo OpenCV.
6. Conferir e corrigir manualmente as respostas, quando necessário.
7. Confirmar o gabarito oficial e salvar a avaliação.
8. Consultar as avaliações cadastradas.

Também será disponibilizada a opção de enviar arquivos PDF, JPG ou PNG.

### 2. Correção

Responsável pela leitura e correção dos cartões preenchidos pelos alunos.

O usuário poderá:

1. Selecionar uma avaliação já cadastrada.
2. Informar a identificação do aluno.
3. Ativar a câmera USB.
4. Posicionar o cartão de respostas na área indicada.
5. Capturar a imagem.
6. Executar o reconhecimento das alternativas.
7. Comparar as respostas com o gabarito oficial da avaliação.
8. Visualizar acertos, erros, questões em branco, pendências e nota.
9. Conferir o resultado e confirmar o salvamento no Firebase.

O sistema não deverá salvar automaticamente uma correção sem confirmação.

## Captura de imagens pela webcam

A aplicação utilizará a câmera conectada ao computador, sem exigir que o usuário salve uma fotografia manualmente no dispositivo.

O navegador solicitará autorização para acessar a câmera e exibirá uma visualização ao vivo do cartão.

### Moldura de enquadramento

A interface apresentará uma moldura retangular para orientar o posicionamento correto da folha.

A moldura terá três estados:

| Cor | Significado |
|---|---|
| Vermelho | Folha não identificada ou fora da área de captura |
| Amarelo | Folha identificada, mas com alinhamento inadequado |
| Verde | Folha enquadrada e pronta para captura |

A verificação deverá considerar a identificação dos limites da folha, o posicionamento, a inclinação e a visibilidade da área necessária à leitura.

Quando necessário, o processamento deverá corrigir a perspectiva da imagem.

A indicação de enquadramento adequado não substitui a validação das respostas reconhecidas.

**Observação:** o reconhecimento de cartões fotografados ainda exige implementação e validação com imagens reais de webcam. Os testes anteriores foram realizados principalmente com PDFs digitais.

## Modelo de avaliação

O sistema utiliza inicialmente um modelo fixo de 50 questões.

| Disciplina | Questões | Pontuação máxima |
|---|---|---|
| Português | 1–25 | 25 pontos |
| Matemática | 26–50 | 25 pontos |
| Total | 50 | 50 pontos |

Cada questão possui cinco alternativas: A, B, C, D e E.

O OpenCV classifica as leituras como:

- `marcada`: uma alternativa identificada.
- `branco`: nenhuma alternativa marcada.
- `multipla`: mais de uma alternativa identificada.
- `duvidosa`: marcação que exige conferência.

Questões múltiplas ou duvidosas permanecem pendentes, e a correção é considerada provisória até sua revisão.

## Arquitetura do sistema

```text
corretor-gabaritos-v2/
├── Backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── routes/
│   │   ├── services/
│   │   │   ├── reconhecimento.py
│   │   │   ├── correcao.py
│   │   │   └── persistencia.py
│   │   ├── models/
│   │   └── database/
│   ├── tests/
│   └── requirements.txt
├── Frontend/
│   ├── index.html
│   ├── pages/
│   ├── css/
│   └── js/
├── docs/
├── .gitignore
└── README.md
```

O backend é responsável pelo processamento, pela correção e pela persistência dos dados.

O frontend será responsável por apresentar as avaliações, acessar a webcam, capturar as imagens e exibir os resultados.

## Fluxo de funcionamento

**Cadastro da avaliação**

Câmera USB → Captura do gabarito oficial → OpenCV → Conferência das respostas → Cadastro no Firebase.

**Correção do aluno**

Selecionar avaliação → Câmera USB → Captura do cartão → OpenCV → Comparação com gabarito oficial → Resultado → Conferência → Salvamento no Firebase.

## Executar o backend

### Pré-requisitos

- Python e Git instalados.
- Navegador compatível com acesso à webcam.
- Câmera USB ou webcam para as futuras funções de captura.
- Dependências definidas em `Backend/requirements.txt`.

Clone o projeto:

```powershell
git clone https://github.com/JoanaCostah/corretor-gabaritos-v2.git
cd corretor-gabaritos-v2
git switch develop
```

Prepare o ambiente:

```powershell
cd Backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Inicie a API:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload
```

Endereços locais:

- API: http://127.0.0.1:8000/
- Swagger: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/health

O endpoint `POST /api/correcoes/processar` recebe um cartão PDF/JPG/PNG e um gabarito oficial explícito em JSON, realizando o processamento e retornando o resultado.

As instruções específicas de configuração do Firestore estão em `docs/firebase.md`.

## Testes automatizados

Na pasta `Backend/`, execute:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

Último resultado informado, ao concluir a Issue 05:

- 130 testes aprovados.
- 1 teste ignorado por ausência do Firestore Emulator.
- 0 testes reprovados.

Os testes não comprovam ainda o funcionamento completo da interface, da webcam USB ou do fluxo integrado com o Firestore Emulator.

## Etapas de desenvolvimento

| Issue | Descrição | Situação |
|---|---|---|
| 01 | Estrutura inicial da API REST | Concluída |
| 02 | Reconhecimento de respostas com OpenCV | Concluída |
| 03 | Motor de correção automática | Concluída |
| 04 | Integração do reconhecimento à API | Concluída |
| 05 | Persistência com Firebase Firestore | Implementada; integração e validação no emulador a confirmar |
| 06 | Interface web e câmera USB | Planejada / em desenvolvimento |

### Próximas validações

- Integração entre frontend e endpoints do backend.
- Cadastro de avaliações a partir de imagens de gabaritos oficiais.
- Acesso e captura pela webcam USB.
- Detecção da folha e moldura de enquadramento.
- Correção de perspectiva e reconhecimento de fotografias.
- Consulta e persistência de resultados pelo Firebase.
- Testes completos com cartões reais em diferentes condições de iluminação.

## Interface visual

A interface seguirá como referência o padrão visual do sistema SENAI apresentado durante o planejamento.

Características principais:

- Tema escuro, com fundo azul-marinho.
- Menu lateral contendo apenas **Avaliações** e **Correção**.
- Campos e cartões com bordas arredondadas.
- Botões e elementos de destaque em azul.
- Tipografia clara e legível.
- Layout organizado para computadores.
- Área de visualização da webcam com moldura de enquadramento.

A interface será funcional e objetiva, sem dashboards, gráficos, relatórios ou páginas desnecessárias nesta versão.

## Limitações

O reconhecimento foi validado com dois PDFs reais do modelo de cartão utilizado no projeto.

O funcionamento com webcam depende de testes adicionais para garantir confiabilidade em fotografias, variações de iluminação, inclinação e perspectiva.

O modelo inicial é restrito a 50 questões, com cinco alternativas por questão.

A aplicação ainda está em desenvolvimento. A implementação e os testes dos módulos não equivalem à homologação do sistema web completo.

## Repositório

[GitHub — Corretor Automático de Gabaritos V2](https://github.com/JoanaCostah/corretor-gabaritos-v2)

---

Projeto desenvolvido com foco em automatização de processos, visão computacional, desenvolvimento de sistemas e aplicação prática de tecnologias web.
