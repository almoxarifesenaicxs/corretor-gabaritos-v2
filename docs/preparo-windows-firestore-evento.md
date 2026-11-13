# Preparar o backend local no Windows para o Firestore do evento

**Este guia prepara a estação; não executa o piloto nem autoriza conexão ao Firestore real.** Leia antes [operação local](local-operacional.md), [checklist Firestore](checklist-firestore-evento.md) e [piloto controlado](piloto-firestore-evento.md). Execute os comandos de inicialização somente depois de configurar e conferir o projeto, a conta e os índices; qualquer chamada a rota de negócio pode consultar o Firestore real.

## Estado verificado em 12/11/2026

- O backend lê variáveis diretamente de `os.environ` durante `criar_app()`/`carregar_ambiente()`. Não carrega `.env` ou `.ps1` automaticamente. Neste terminal, `APP_AMBIENTE`, `FIRESTORE_MODO`, `FIREBASE_PROJECT_ID`, `GOOGLE_APPLICATION_CREDENTIALS`, `INTEGRIDADE_CHAVE`, `SERVIR_FRONTEND` e `LOCAL_OPERACIONAL_HOST` estão ausentes.
- Existe `Backend/.env.real.ps1`, ignorado pela regra `.env.*` do `.gitignore` e não rastreado pelo Git. **Seu conteúdo não foi aberto nem validado.** Revise-o privadamente antes de decidir reutilizá-lo; não o execute automaticamente. Não há `.env.example` na raiz ou em `Backend`.
- `.gitignore` também ignora `.secrets/`, arquivos `*firebase-adminsdk*.json` e `*service-account*.json`. Um JSON com outro nome **não** fica necessariamente protegido. Guarde credenciais fora de toda a pasta do repositório; não dependa apenas do ignore.
- `Frontend/js/config.mjs` permanece apontando para a API pública da Render para a Vercel. Em `local_operacional`, a rota `/interface/js/config.mjs` responde `API_BASE_URL = ""` com `Cache-Control: no-store`. Abra a interface por `/interface/` no backend local; não abra o arquivo HTML diretamente nem use a Vercel para este modo. Nenhuma mudança no frontend é necessária.

## O que obter e onde

| Configuração | Origem e uso |
| --- | --- |
| `FIREBASE_PROJECT_ID` | [Firebase Console → Configurações do projeto → Geral](https://firebase.google.com/docs/projects/learn-more): copiar o **ID do projeto**, não o número ou nome exibido. Confirmar que é o projeto do banco `(default)` do evento. |
| `GOOGLE_APPLICATION_CREDENTIALS` | Caminho absoluto para um **JSON de chave de conta de serviço** do mesmo projeto, guardado fora do Git. A equipe responsável deve criar ou selecionar conta com permissão IAM mínima de leitura e escrita no Firestore, por exemplo [Cloud Datastore User](https://docs.cloud.google.com/firestore/native/docs/security/iam), e fornecer a chave pelo processo aprovado. [Firebase Console → Configurações do projeto → Contas de serviço](https://firebase.google.com/docs/admin/setup) explica a geração da chave; [Google Cloud Console → IAM e administrador → Contas de serviço → Chaves](https://docs.cloud.google.com/iam/docs/keys-create-delete) permite selecionar uma conta dedicada. Não gerar uma segunda chave se já existir uma aprovada. |
| `INTEGRIDADE_CHAVE` | **Não vem do Firebase.** Gerar uma vez na estação, com 32 bytes aleatórios (64 caracteres hexadecimais), guardar com proteção do Windows e reutilizar a mesma chave após reinícios. Não imprimi-la, colá-la no Git, em chats ou em `.env.example`. |
| `APP_AMBIENTE`, `FIRESTORE_MODO`, `SERVIR_FRONTEND`, `LOCAL_OPERACIONAL_HOST` | Valores fixos de execução local: `local_operacional`, `real`, `true`, `127.0.0.1`. Não são valores do Firebase Console. |

O Admin SDK lê o JSON **somente no backend**. A chave Web pública do Firebase e `ADMIN_UIDS` não participam do fluxo local sem login. Regras do SDK cliente não restringem o Admin SDK; o controle decisivo é IAM e a proteção do arquivo privado. [Práticas oficiais para chaves de serviço](https://docs.cloud.google.com/iam/docs/best-practices-for-managing-service-account-keys).

## Preparação PowerShell sem conexão

Abra uma janela PowerShell dedicada na conta Windows que executará o backend. Estes comandos **não** abrem o Firestore. Substitua apenas os dois placeholders de projeto e caminho, sem colar o conteúdo do JSON no terminal:

```powershell
Set-Location 'C:\Users\joana\Documents\corretor-gabaritos-v2\Backend'
$env:APP_AMBIENTE = 'local_operacional'
$env:FIRESTORE_MODO = 'real'
$env:FIREBASE_PROJECT_ID = '<ID_DO_PROJETO>'
$env:GOOGLE_APPLICATION_CREDENTIALS = '<CAMINHO_ABSOLUTO_DO_JSON_FORA_DO_REPOSITORIO>'
$env:LOCAL_OPERACIONAL_HOST = '127.0.0.1'
$env:SERVIR_FRONTEND = 'true'
Remove-Item Env:FIRESTORE_EMULATOR_HOST, Env:FIREBASE_AUTH_EMULATOR_HOST, Env:CORS_ORIGINS, Env:FORWARDED_ALLOW_IPS -ErrorAction SilentlyContinue
```

`PORT`, `RENDER_*`, `VERCEL` ou `K_SERVICE` presentes impedem o modo operacional; remova-os **apenas nesta janela de operação**, depois de confirmar que não pertencem a outra tarefa. Não altere variáveis de máquina, painel da Render ou painel da Vercel.

Para criar a chave de integridade **uma única vez**, escolha uma pasta privada fora do repositório, no perfil Windows do operador, e grave-a com proteção DPAPI do usuário. Os comandos abaixo não exibem o valor; revise permissões da pasta e mantenha uma forma aprovada de recuperá-la em caso de perda do perfil Windows. **Não execute novamente se o arquivo já existir**, pois uma chave diferente invalida comprovantes de correções pendentes:

```powershell
$privateDir = Join-Path $env:LOCALAPPDATA 'CorretorGabaritos\Segredos'
$keyFile = Join-Path $privateDir 'integridade.dpapi'
New-Item -ItemType Directory -Path $privateDir -Force | Out-Null
if (Test-Path -LiteralPath $keyFile) { throw 'A chave já existe: reutilize-a; não gere outra.' }
[byte[]]$bytes = New-Object byte[] 32
$rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
$hex = -join ($bytes | ForEach-Object { $_.ToString('x2') })
ConvertTo-SecureString $hex -AsPlainText -Force | ConvertFrom-SecureString |
  Set-Content -LiteralPath $keyFile -NoNewline
[Array]::Clear($bytes, 0, $bytes.Length)
$hex = $null
```

Em cada nova janela PowerShell da **mesma conta Windows**, carregue a chave para o ambiente do processo filho. DPAPI não permite recuperar a chave em outro usuário/computador sem procedimento de contingência aprovado:

```powershell
$keyFile = Join-Path (Join-Path $env:LOCALAPPDATA 'CorretorGabaritos\Segredos') 'integridade.dpapi'
if (-not (Test-Path -LiteralPath $keyFile -PathType Leaf)) { throw 'Chave de integridade ausente.' }
$secure = Get-Content -LiteralPath $keyFile -Raw | ConvertTo-SecureString
$ptr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try { $env:INTEGRIDADE_CHAVE = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($ptr) }
finally { [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($ptr) }
```

Não execute `Get-ChildItem Env:INTEGRIDADE_CHAVE`, `Write-Host $env:INTEGRIDADE_CHAVE` nem comandos que incluam a chave literal. Ela permanecerá no ambiente da janela e do backend enquanto estiverem abertos; feche a janela ao encerrar a operação.

## Verificação offline antes de iniciar

Confira **somente presença e validade**, sem exibir valores. A leitura local do JSON por `Certificate` verifica formato, chave privada e associação ao projeto, mas não abre rede nem confirma IAM/banco:

```powershell
if ($env:APP_AMBIENTE -ne 'local_operacional' -or $env:FIRESTORE_MODO -ne 'real' -or
    $env:SERVIR_FRONTEND -ne 'true' -or $env:LOCAL_OPERACIONAL_HOST -ne '127.0.0.1') {
  throw 'Modo local operacional incompleto.'
}
if (-not (Test-Path -LiteralPath $env:GOOGLE_APPLICATION_CREDENTIALS -PathType Leaf)) {
  throw 'Arquivo privado de credenciais ausente.'
}
if ($env:INTEGRIDADE_CHAVE -notmatch '^[0-9a-fA-F]{64}$') {
  throw 'Chave de integridade inválida.'
}
@'
import os
from firebase_admin.credentials import Certificate
try:
    certificado = Certificate(os.environ['GOOGLE_APPLICATION_CREDENTIALS'])
    if certificado.project_id != os.environ['FIREBASE_PROJECT_ID']:
        raise ValueError()
except Exception:
    raise SystemExit('Credenciais locais inválidas ou de outro projeto.')
print('Formato e projeto das credenciais: OK (sem conexão).')
'@ | .\.venv\Scripts\python.exe -
```

Confirme também que o caminho do JSON está fora do repositório e que as ACLs permitem acesso apenas ao operador e administradores necessários; não abra ou imprima o arquivo no relatório. O teste offline **não** valida existência do banco, permissões IAM, índices, cota ou rede. Essas verificações pertencem ao [piloto real](piloto-firestore-evento.md), após autorização explícita.

## Inicialização local posterior

Após a preparação e a autorização da operação local, na pasta `Backend`, com dependências já instaladas:

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --workers 1
```

Na **mesma máquina**, abrir `http://127.0.0.1:8000/interface/`. Verificar que o dashboard abre sem login e que `/interface/js/config.mjs` entrega a base local vazia; não alterar `Frontend/js/config.mjs`. `GET /api/health` confirma apenas o processo HTTP. Não acessar `/api/avaliacoes`, `/api/alunos` ou outras rotas de negócio até a autorização do piloto, pois essas rotas podem conectar ao Firestore real. Nunca iniciar com `--host 0.0.0.0`, proxy reverso, túnel ou encaminhamento de porta.

Antes do piloto, conferir no projeto correto os índices em estado **Ready**, IAM da conta, banco `(default)`, plano/cota, backup, manifesto de IDs fictícios e procedimento de limpeza. Não colocar o JSON, o arquivo DPAPI, a chave em texto ou o script privado `.env.real.ps1` no GitHub, Render ou Vercel.
