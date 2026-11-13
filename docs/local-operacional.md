# Operação local para o evento

`APP_AMBIENTE=local_operacional` serve dashboard e API na mesma origem HTTP de loopback, sem formulário de login e sem Firebase Authentication. Somente o backend usa Firebase Admin SDK e Firestore real. O arquivo `Frontend/js/config.mjs` continua com a URL pública da Render; ao servir `/interface/js/config.mjs`, este modo entrega uma configuração local com `API_BASE_URL = ""`. Não abra o HTML diretamente como arquivo nem use a Vercel para operar este modo.

## Preparação no Windows

Use uma estação dedicada e uma conta Windows restrita. Antes do evento, configure fora do repositório um arquivo JSON **de conta de serviço do projeto correto**, com permissão mínima para o Firestore, e uma chave aleatória estável de 32 bytes em hexadecimal para `INTEGRIDADE_CHAVE`. Nunca copie esses valores para o frontend, Git, scripts versionados ou capturas de tela. O banco Firestore **(default)** deve existir e a conta deve ter permissão para ler e gravar nele. Configure backup/exportação e teste restauração antes de usar dados reais.

No PowerShell, a partir da raiz do projeto, com as dependências Python já instaladas em `Backend/.venv`:

```powershell
Set-Location Backend
$env:APP_AMBIENTE = "local_operacional"
$env:LOCAL_OPERACIONAL_HOST = "127.0.0.1"
$env:SERVIR_FRONTEND = "true"
$env:FIRESTORE_MODO = "real"
$env:FIREBASE_PROJECT_ID = "ID_DO_PROJETO"
$env:GOOGLE_APPLICATION_CREDENTIALS = "CAMINHO_ABSOLUTO_DO_JSON_PRIVADO"
# INTEGRIDADE_CHAVE deve vir de um segredo privado, estável, com 64 caracteres hexadecimais.
if (-not $env:INTEGRIDADE_CHAVE) { throw "Configure INTEGRIDADE_CHAVE no ambiente privado antes de iniciar." }
Remove-Item Env:FIRESTORE_EMULATOR_HOST, Env:FIREBASE_AUTH_EMULATOR_HOST, Env:CORS_ORIGINS, Env:FORWARDED_ALLOW_IPS -ErrorAction SilentlyContinue
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-proxy-headers --workers 1
```

Abra `http://127.0.0.1:8000/interface/` **no mesmo computador**. Para IPv6, configure `LOCAL_OPERACIONAL_HOST=::1`, inicie com `--host ::1` e abra `http://[::1]:8000/interface/`. Não use `--host 0.0.0.0`, proxy reverso, encaminhamento de porta, túnel, acesso remoto à porta ou variáveis de ambiente da Render. `PORT`, variáveis `RENDER_*` e outras marcas de hospedagem impedem a inicialização. O comando de operação mantém `--no-proxy-headers`.

Antes de consultar avaliações ou alunos, confira a instância que realmente atende à porta 8000: `GET /api/health` deve retornar 200; `GET /api/auth/me` e `GET /docs` devem retornar 404. Se `/api/auth/me` retornar 401 ou `/docs` retornar 200, a instância está em outro modo (normalmente `local`) ou foi iniciada com código antigo. Encerre essa instância e inicie novamente o Uvicorn **no mesmo PowerShell em que as variáveis acima foram definidas**; alterar variáveis em outro terminal ou após a inicialização não muda o modo do processo em execução. Não consulte rotas de negócio para diagnosticar o modo, pois elas podem acessar o Firestore real.

O processo falha ao iniciar se modo, projeto, arquivo de credencial, chave de integridade, frontend ou configuração de rede estiverem incompletos ou contraditórios. A conta de serviço e o projeto do arquivo devem corresponder a `FIREBASE_PROJECT_ID`. Não há fallback para emulador ou armazenamento temporário. A conexão e as permissões do banco só podem ser confirmadas com um ensaio controlado **após autorização para acessar o projeto real**; até lá, erros do Firestore impedem salvar e aparecem como indisponibilidade, sem mudar o destino da persistência.

## Segurança e continuidade

O servidor aceita somente cliente e endereço de escuta loopback, Host exato e Origin da mesma origem. Rejeita `Forwarded` e `X-Forwarded-*`. CORS fica vazio; não existe autenticação de usuário neste modo. **Qualquer pessoa com acesso à sessão Windows ou acesso físico ao computador pode ver e alterar os dados**; não há isolamento entre operadores. Bloqueie a tela quando se afastar e evite computador compartilhado. Uma pessoa que já controla a máquina pode criar um proxy local; a proteção de loopback não substitui a segurança física e do sistema operacional.

Antes de corrigir em escala, ensaie com dados fictícios: cadastrar avaliação, processar PDF/JPG/PNG, revisar, salvar, consultar histórico e repetir a mesma operação para conferir idempotência. Confirme a chave de integridade estável em reinicializações. A fila de processamento mantém os limites existentes de upload (10 MiB), corpo HTTP, concorrência e tamanho de imagem; evite várias correções simultâneas sem teste de carga. Monitore CPU, RAM e espaço livre. Se a rede ou o Firestore falhar, **não interprete a resposta como confirmação de salvamento**: confira o histórico antes de repetir, usando o mesmo `operacao_id` quando possível. Faça exportações e cópias de segurança periódicas conforme o procedimento aprovado para dados pessoais.

Este modo é local, não é a configuração da Render nem da Vercel. Os demais modos (`local`, `local_publico`, `homologacao`, `producao` e `publico`) mantêm suas regras próprias.
