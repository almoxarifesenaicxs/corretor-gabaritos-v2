# Demonstração pública sem login

`APP_AMBIENTE=publico_demo` é independente de `producao`, `publico`,
`homologacao` e `local_operacional`. Serve uma avaliação fictícia fixa e permite
processar PDF, JPG ou PNG e revisar as 50 respostas, sem persistir correções,
alunos, imagens ou uploads. O backend não monta as rotas de gravação, histórico,
ZIP, exportação ou administração. A aba Alunos permanece vazia por definição.

O modo recusa iniciar se houver `FIRESTORE_MODO`, credenciais Google/Firebase,
`FIREBASE_PROJECT_ID`, `ADMIN_UIDS` ou `INTEGRIDADE_CHAVE` no ambiente. Na Render,
configure manualmente `ALLOWED_HOSTS=corretor-gabaritos-8yal.onrender.com`,
`CORS_ORIGINS=https://corretor-gabaritos-v2-frontend.vercel.app` e
`SERVIR_FRONTEND=false`. Mantenha `--no-proxy-headers` e um worker. Antes de
trocar `APP_AMBIENTE=homologacao` por `publico_demo`, remova as variáveis
Firebase/Firestore do serviço e valide o host e a origem reais. O Blueprint
continua em homologação e com deploy automático desligado; esta mudança não
ativa nem publica o modo.

No frontend hospedado, `PUBLIC_DEMO` abre o dashboard diretamente e mostra o
aviso de usar apenas cartões fictícios. No localhost, a interface mantém a API
local. A câmera em HTTPS continua disponível, porém sem análise periódica de
enquadramento no servidor. O reconhecimento ocorre quando o visitante confirma
e envia a imagem. O processamento é sequencial, limitado a um por vez e a 12
requisições caras por minuto por processo, além dos limites existentes de 10 MiB
por arquivo, 12 milhões de pixels e prazo de recepção. O limite não substitui
proteção de borda contra abuso distribuído; monitore CPU e memória na Render.

Nenhum dado real de aluno deve ser enviado à demonstração. Os arquivos são
processados em diretório temporário e removidos após a resposta, mas o modo
sem login não oferece sigilo de entrada contra o operador da infraestrutura.
ZIP, exportação e recuperação ficam reservados aos modos operacionais.
