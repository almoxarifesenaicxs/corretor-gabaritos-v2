# Persistência com Firebase Firestore — Issue 05

A camada fica em `app/services/persistencia.py`, com conexão explícita em
`app/database/firestore.py`. Não há conexão na importação dos módulos nem
gravação automática em `POST /api/correcoes/processar`. As rotas adicionadas
na Issue 06 usam essa camada e agora selecionam seu destino por `FIRESTORE_MODO`.
Os serviços de OpenCV e o motor de correção não mudaram nesta configuração.

## Coleções e contrato

| Coleção | Identificador do documento | Campos |
| --- | --- | --- |
| `provas` | UUID gerado pelo serviço | `id`, `titulo`, `descricao` opcional, `criada_em` |
| `gabaritos` | ID da prova (um gabarito por prova) | `id`, `prova_id`, `alternativas`, `criado_em` |
| `correcoes` | UUID gerado pelo serviço | `id`, `prova_id`, `aluno`, `resultado`, `situacao`, `processada_em` |

As datas são `datetime` UTC com fuso, obtidas no backend no momento da
operação. O SDK as serializa como timestamps do Firestore; não são strings
JSON. `descricao` ausente é armazenada como nulo. `aluno` é texto informado
manualmente, sem relação com autenticação ou extração de dados do cartão.

`alternativas` segue exatamente o gabarito do motor: objeto com chaves
textuais `"1"` a `"50"` e valores A–E maiúsculos. A validação reutiliza
`validar_gabarito`. O serviço exige que a prova exista antes do cadastro.
Usa `DocumentReference.create`, com o ID da prova, para rejeitar a segunda
gravação de modo atômico, inclusive em tentativas concorrentes. Não há operação
de atualização/substituição de gabarito nesta etapa.

`resultado` mantém o objeto do motor, incluindo resumo, disciplinas,
provisoriedade e questões pendentes, sem alterar contagens, notas ou percentuais.
A validação da persistência verifica tipos e campos do contrato de transporte;
não recalcula a correção nem certifica a origem do resultado. O chamador deve
passar a saída real do motor e associá-la à prova correta.
`situacao` é `provisoria` ou `sem_pendencias`, derivada de `resultado.provisorio`.
PDFs, imagens e objetos binários não são armazenados.

## Instalação

No PowerShell, a partir da raiz:

```powershell
cd Backend
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip check
```

Bibliotecas adicionadas: `firebase-admin==7.7.0`,
`google-cloud-firestore==2.34.1`, `google-api-core==2.43.2` e
`google-auth==2.62.0`. Instalação e suíte verificadas em Python 3.14.6,
sem conflitos encontrados por `pip check`. As dependências transitivas são
instaladas pelo pip; as versões preexistentes do projeto foram preservadas.

## Emulador local — caminho padrão

Use a [Firebase Local Emulator Suite](https://firebase.google.com/docs/emulator-suite/install_and_configure).
Instale os pré-requisitos da versão atual do Firebase CLI e do Java conforme
essa documentação. Em uma pasta de configuração local, execute
`firebase init emulators`, selecione somente Firestore, configure host
`127.0.0.1` e porta `8080`, e inicie:

```powershell
firebase emulators:start --only firestore --project demo-corretor-local
```

Em outro terminal PowerShell, defina:

```powershell
$env:FIRESTORE_EMULATOR_HOST = "127.0.0.1:8080"
$env:FIREBASE_PROJECT_ID = "demo-corretor-local"
$env:FIRESTORE_MODO = "emulador"
```

Não inclua `http://` na variável do host. O wrapper exige endereço de loopback
(`127.0.0.1`, `localhost` ou `[::1]`) com porta e um projeto `demo-*`.
Isso restringe os testes e o uso padrão a uma base local. O SDK conecta ao
emulador através de `FIRESTORE_EMULATOR_HOST`, conforme a
[documentação oficial](https://firebase.google.com/docs/emulator-suite/connect_firestore).
Nesta implementação, o emulador recebe credenciais anônimas; não precisa de
chave privada, login ou credenciais de produção. Não há fallback para nuvem
se o emulador estiver indisponível.

As variáveis devem existir no processo antes da abertura do cliente. Um arquivo
`.env` não é carregado automaticamente. Cada bloco `with` inicializa um app
Firebase nomeado e isolado, cria seu cliente e fecha ambos ao sair. Não altere
as variáveis de destino durante a execução desse bloco.

## Operações disponíveis e exemplo

Execute a partir de `Backend`, usando o Python do ambiente virtual:

```python
from app.database.firestore import conectar_firestore
from app.services.persistencia import Persistencia
from app.services.correcao import corrigir_respostas

# Demonstração fictícia. Em uso real, informe o gabarito oficial verificado.
oficial = {str(i): "A" for i in range(1, 51)}
respostas = {
    str(i): {"resposta": "A", "estado": "marcada", "alternativas": ["A"]}
    for i in range(1, 51)
}
resultado = corrigir_respostas(respostas, oficial)

with conectar_firestore() as cliente:  # Somente emulador por padrão.
    repo = Persistencia(cliente)
    prova = repo.criar_prova("Prova de exemplo", descricao="50 questões")
    repo.cadastrar_gabarito(prova["id"], oficial)
    assert repo.consultar_prova(prova["id"]) == prova
    print(repo.listar_provas())
    print(repo.consultar_gabarito(prova["id"]))

    correcao = repo.salvar_correcao(prova["id"], "Aluno de exemplo", resultado)
    print(repo.consultar_correcao(correcao["id"]))
    print(repo.listar_correcoes(prova["id"]))
```

`consultar_prova`, `consultar_gabarito` e `consultar_correcao` retornam um
dicionário ou `None` quando ausentes. Listagens retornam listas, sem ordem
garantida. Filtrar correções de uma prova inexistente retorna lista vazia.

O salvamento é sempre uma chamada explícita. Para um resultado provisório,
a chamada padrão falha; após decisão do usuário, passe
`permitir_provisorio=True` a `salvar_correcao`. Isso armazena o resultado
pendente sem atribuir alternativas presumidas nem torná-lo definitivo.

Entradas inválidas e provas inexistentes levantam `ValueError` (incluindo
`ErroCorrecao` para gabaritos inválidos). Conflitos de criação levantam
`RegistroExistente`; falhas de RPC do banco levantam `ErroPersistencia`,
preservando a exceção original como causa para diagnóstico interno. Não
devolva essa causa diretamente em futuros endpoints HTTP.

## Firestore real — ativação explícita somente para uso local

As rotas de persistência leem `FIRESTORE_MODO` no backend:

| Valor | Comportamento |
| --- | --- |
| Variável ausente ou `emulador` | Usa o emulador; exige host local e projeto `demo-*` |
| `real` | Usa `conectar_firestore(emulador=False)`; exige projeto real, ADC e acesso HTTP local direto |
| Vazio ou outro valor | Rejeita a configuração com HTTP 503, sem fallback |

Ter credenciais configuradas não ativa a conexão real. `conectar_firestore()`
continua sendo uma função de baixo nível cujo padrão é emulador, independentemente
da variável de seleção das rotas. O módulo não conecta na importação nem na
inicialização da aplicação; o cliente é aberto quando uma operação de
persistência é solicitada.

No Firebase Console, escolha o projeto e crie a base Cloud Firestore padrão
`(default)`. Configure permissões mínimas da identidade do backend para as
operações necessárias. O SDK Admin usa credenciais do servidor; não substitui
uma futura autenticação/autorização da aplicação e não deve ser exposto ao
navegador.

A conexão real requer chamada explícita `conectar_firestore(emulador=False)`,
`FIREBASE_PROJECT_ID` com o ID real e ausência de `FIRESTORE_EMULATOR_HOST`.
Usa [Application Default Credentials](https://firebase.google.com/docs/firestore/quickstart-server).
Prefira identidade gerenciada em ambiente hospedado. Se for necessário um
arquivo de credencial local, forneça seu caminho por
`GOOGLE_APPLICATION_CREDENTIALS`, mantenha-o fora do repositório e não cole
seu conteúdo em código, logs ou testes. Não foi criado arquivo de chave nesta
issue. `.gitignore` protege `.env*`, `.secrets/`, nomes padrão de chaves do
Firebase e os arquivos de depuração; não protege automaticamente qualquer
nome arbitrário de arquivo de credenciais.

Não execute a opção real para validar testes. Ela é bloqueada em processos
Pytest. O projeto/base reais não foram acessados por esta implementação.

### Ativar no PowerShell

Os comandos abaixo são instruções para uso pelo responsável pelo projeto;
**não foram executados durante a implementação**. No terminal do backend:

```powershell
cd Backend
$env:FIRESTORE_MODO = "real"
$env:FIREBASE_PROJECT_ID = "seu-id-real-do-projeto"
Remove-Item Env:FIRESTORE_EMULATOR_HOST -ErrorAction SilentlyContinue
# Apenas quando ADC depende de arquivo: use um caminho privado fora do repositório.
$env:GOOGLE_APPLICATION_CREDENTIALS = "C:\credenciais-privadas\firebase-service-account.json"

.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers
```

Substitua os exemplos pelo ID e pelo caminho reais. A credencial deve pertencer
a uma identidade autorizada para o projeto, com privilégios mínimos adequados.
Se ADC já estiver configurado por outro mecanismo, não defina um caminho de
arquivo desnecessário. Não crie chaves apenas para executar testes. Um `.env`
não é carregado automaticamente; reinicie o backend no terminal configurado.

Abra `http://127.0.0.1:8000/interface/` na mesma máquina. Leituras consultam a
base real; cadastros/salvamentos confirmados gravam nela e podem gerar custos.
Nenhum valor de credencial precisa ou deve ir para o frontend.

### Restrição de acesso local

Sem autenticação, **não publique esta API, não use `--host 0.0.0.0` e não a
exponha por proxy, túnel ou encaminhamento de portas**. A opção
`--no-proxy-headers` mantém o endereço do cliente associado à conexão direta.
O backend exige, antes de abrir um cliente real:

- IP remoto de loopback, obtido da conexão (`request.client`), e Host local
  (`localhost`, `127.0.0.1` ou `::1`).
- Ausência dos cabeçalhos `Forwarded`, `X-Forwarded-For`, `X-Forwarded-Host`
  e `X-Forwarded-Proto`.
- Quando há `Origin`, coincidência exata de esquema, host e porta com a API.

Falhas dessas condições retornam 403 sem abrir conexão com o Firestore.
Configuração inválida ou falha na abertura do cliente retorna 503 sem expor
caminhos ou credenciais. Não há fallback de real para emulador ou vice-versa.

Essas verificações restringem o acesso, mas **não substituem autenticação e
autorização**: processos locais ainda podem chamar a API. Um proxy que esconda
deliberadamente sua origem não pode ser distinguido de um cliente local;
por isso o vínculo de rede deve permanecer em loopback, sem exposição externa.
Controles de autenticação/autorização são necessários antes de qualquer publicação.

### Voltar ao emulador e executar testes

Pare o backend, configure outro terminal (ou o mesmo terminal após trocar as
variáveis) e reinicie. Use um projeto demo separado:

```powershell
$env:FIRESTORE_MODO = "emulador"
$env:FIREBASE_PROJECT_ID = "demo-corretor-local"
$env:FIRESTORE_EMULATOR_HOST = "127.0.0.1:8080"
Remove-Item Env:GOOGLE_APPLICATION_CREDENTIALS -ErrorAction SilentlyContinue
```

Para rodar a suíte sem nem mesmo acessar o emulador, remova também
`FIRESTORE_EMULATOR_HOST` antes do Pytest. O teste específico de integração
será ignorado; os demais usam dependências simuladas para Firestore.

## Testes e proteção de produção

```powershell
cd Backend
.\.venv\Scripts\python.exe -m pytest -q
# Com emulador já em execução e as duas variáveis locais definidas:
.\.venv\Scripts\python.exe -m pytest tests/test_firestore_emulador.py -q
```

Resultado após a configuração de modo: **187 aprovados, 1 ignorado, 0 reprovados**.
Os casos anteriores foram preservados. Permanece somente o aviso anterior
de depreciação do Starlette/TestClient. O teste ignorado é o ciclo completo
contra o Firestore Emulator; não há alegação de integração real validada.

Os novos testes substituem a conexão para verificar a seleção dos modos nas
rotas, sem cliente Firebase real ou ADC. Cobrem modo padrão, valor desconhecido,
projeto ausente/demo, conflito com host de emulador, acesso remoto, Host externo,
origem diferente, proxy e preservação do bloqueio de produção em Pytest.
`tests/conftest.py` e os bloqueios de `conectar_firestore` não foram removidos.

Os testes unitários usam dependências simuladas e o codec real de valores
do SDK para verificar serialização/recuperação, inclusive timestamps. Cobrem
cadastros, consultas, listagens, filtro por prova, gabaritos inválidos,
conflitos, prova inexistente, preservação do resultado, decisão sobre
provisoriedade e falhas de banco. Testes de configuração verificam bloqueios,
credenciais anônimas e ausência de conexão ao importar.

`tests/conftest.py` também bloqueia a criação direta de clientes síncronos
Firestore sem emulador local e projeto demo correspondente. O único teste
com RPC exige emulador e projeto seguros antes da conexão. Sem host, é
ignorado; com host inseguro ou emulador indisponível, falha sem fallback para
produção. Cria registros com IDs isolados e remove apenas os seus próprios
documentos no final, sem limpar a base inteira. Nenhuma credencial de
produção é usada nos testes.

## Limitações, credenciais e custos

- Não há edição, exclusão, paginação, ordenação, versionamento de gabarito ou
  política de retenção. As listagens carregam todos os registros correspondentes.
- A checagem da existência da prova e a criação do registro filho não formam
  uma transação. Não há exclusão de prova no serviço; exclusões externas
  concorrentes podem produzir referências órfãs.
- Datas usam o relógio do backend, não um timestamp gerado pelo servidor.
- Cada chamada de salvar correção cria um registro novo; não há deduplicação
  nem chave de idempotência. A correção registra a prova, mas não uma versão
  independente do gabarito ou o arquivo original.
- O serviço confia que a saída do motor e a prova informada correspondem entre
  si. Não verifica a autenticidade do gabarito nem refaz cálculos do motor.
- Não há autenticação/autorização nesta issue. Não publique operações de
  persistência abertas como endpoints sem implementar os controles futuros.
- Na nuvem, leituras, gravações e armazenamento podem gerar custos. Evite
  testes em produção, proteja credenciais e configure controles de acesso,
  acompanhamento de uso e orçamento antes de habilitar uma base real.

Nenhum acesso ao Firestore real, gravação real, commit, merge ou push foi feito
durante esta configuração.
