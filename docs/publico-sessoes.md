# Acesso público operacional sem login

Este documento descreve o modo anterior `publico_sessoes`, preservado para
compatibilidade. **A entrega compartilhada atual usa `publico_compartilhado`**;
veja [operação pública compartilhada](publico-compartilhado.md). Sua política
de retenção de 30/37 dias não se aplica aos registros do modo compartilhado.

`APP_AMBIENTE=publico_sessoes` abre o dashboard sem Firebase Authentication.
Cada navegador recebe um identificador anônimo aleatório de 192 bits, assinado
pelo backend, válido por 30 dias e guardado no armazenamento local do navegador.
Ele é enviado exclusivamente no cabeçalho `Authorization: Bearer`; não vai em
URLs, imagens ou CSV. Não é identificação pessoal nem conta: quem obtiver esse
identificador pode acessar os dados daquela sessão. O navegador valida a sessão
na abertura e não cria outra silenciosamente quando ela expira. Limpar os dados
do navegador, perder o dispositivo ou deixar a sessão vencer impede recuperar
resultados sem uma conta; exporte CSV regularmente. Pessoas no mesmo perfil do
navegador compartilham a sessão. Um administrador da infraestrutura do projeto
Firestore dedicado ainda pode acessar os documentos.
O vencimento da capacidade não apaga automaticamente os documentos. Cada sessão
nova registra `expires_at` no documento `sessoes_publicas/{sessao}` para a
limpeza operacional. Sem identidade ou chave preservada, não há recuperação de
sessões perdidas nem como provar a titularidade de um conjunto de dados.

## Isolamento e persistência

Use um **projeto Firebase/Firestore exclusivo para o público**, nunca o projeto
operacional. O backend valida que o `project_id` do arquivo privado da conta de
serviço corresponde ao projeto público e rejeita o ID operacional conhecido.
As coleções de alunos, provas, gabaritos, correções, operações e nomes ficam sob
`sessoes_publicas/{sessao}/...`; cada requisição é limitada ao namespace
derivado da assinatura do identificador. A conta de serviço fica somente na
Render. O Admin SDK usa IAM, e as regras do SDK cliente não protegem esses
acessos. Os resultados persistem no Firestore dedicado após reinício da Render;
ZIPs e imagens intermediárias ficam apenas em arquivos temporários e se perdem
em reinícios. Uma operação de salvamento inconclusiva deve ser consultada pelo
mesmo `operacao_id` na mesma sessão antes de reenviar. Uma nova sessão não
recupera operações da anterior.

## Retenção e limpeza obrigatória

A sessão dura **30 dias**. Mantenha uma margem operacional de **7 dias** após
`expires_at` para conferência/exportação e exclua então a árvore inteira da
sessão. Uma vez vencida, a API já rejeita seu token; a margem não reabre acesso.
Execute a conferência **diariamente** no projeto público dedicado:

1. Confirme no Firebase Console o ID do projeto e do banco; compare com o
   projeto operacional e não prossiga se forem iguais. Liste documentos de
   `sessoes_publicas` com `expires_at` anterior ou igual a **agora UTC menos
   7 dias**. Anote somente os IDs das sessões elegíveis e a contagem; confira
   se houve exportação necessária antes da exclusão.
2. Para cada ID elegível, no terminal administrativo autenticado no **projeto
   público**, execute `firebase firestore:delete "sessoes_publicas/<ID_DA_SESSAO>" --recursive --project "<ID_PROJETO_PUBLICO>"`.
   Confira o projeto e o caminho no prompt de confirmação; não use `--force`
   nem `--all-collections`.
3. Verifique que o documento e todas as subcoleções da sessão desapareceram.
   Registre data, projeto, quantidade removida e eventuais falhas, sem nomes de
   alunos ou tokens. Repita apenas as falhas identificadas.

Não aplique TTL somente ao documento pai: [o Firestore não exclui suas
subcoleções](https://firebase.google.com/docs/firestore/ttl). A [Firebase
CLI](https://firebase.google.com/docs/cli) oferece exclusão recursiva, com
custos de leitura e exclusão. A rotina acima é manual; sem um responsável por
executá-la, **não há retenção efetiva**. Antes de alto volume, automatize essa
mesma política com execução revisada, sem ampliar o acesso público à API.

## Configuração manual da Render

O `render.yaml` agora está preparado para `publico_compartilhado` e mantém o
deploy automático desligado. Para usar este modo legado, altere o Blueprint
explicitamente; importar/sincronizar um Blueprint pode iniciar um deploy.
Configure os segredos antes. O serviço deve usar o plano `1c-2g` (1 CPU,
2 GiB), um worker e `/api/health` como health check. Preencha fora do Git:

- `APP_AMBIENTE=publico_sessoes`, `FIRESTORE_MODO=real`, `SERVIR_FRONTEND=false`.
- `FIREBASE_PROJECT_ID`: ID do **projeto público novo**;
  `FIREBASE_PRODUCTION_PROJECT_ID`: ID do projeto operacional, diferente.
- `GOOGLE_APPLICATION_CREDENTIALS=/etc/secrets/firestore-publico.json`:
  carregue o arquivo como **Secret File** da Render com esse nome; nunca na Vercel
  ou no repositório.
- `INTEGRIDADE_CHAVE` e `PUBLIC_SESSION_KEY`: chaves independentes de 32 bytes,
  cada uma representada por 64 caracteres hexadecimais; estáveis entre deploys.
- `ALLOWED_HOSTS=corretor-gabaritos-8yal.onrender.com` e `CORS_ORIGINS` igual à
  **origem HTTPS exata** da Vercel publicada, sem barra final, caminho ou
  curinga. Confira o domínio real no painel. Não configure `ADMIN_UIDS`,
  emuladores ou proxies confiáveis irrestritos. Mantenha
  `--no-proxy-headers --workers 1`.

O backend verifica o arquivo da conta de serviço e o projeto antes de iniciar,
mas **não** valida conectividade, IAM, existência do banco ou índices na partida.
Um piloto autorizado com dados fictícios no projeto novo precisa confirmar
gravação, consulta, histórico, exportação, reenvio idempotente e índices. O
índice composto de histórico **com escopo Collection** `correcoes` por
`aluno_id ASC`, `processada_em DESC`, `__name__ ASC` deve estar pronto no projeto
novo. Confirme também os índices automáticos de coleção para
`alunos.nome_normalizado`, `correcoes.aluno_id`, `correcoes.aluno` e
`correcoes.prova_id` quando a consulta correspondente os usar. O pai
`sessoes_publicas.expires_at` precisa do índice de campo único para a lista de
limpeza. Não é necessária consulta entre sessões com escopo Collection Group.
As regras Firestore para clientes Web/Mobile devem negar leitura e escrita;
somente a conta de serviço do backend recebe IAM de leitura/escrita de dados.
O Admin SDK ignora as regras de cliente; a conta não deve ser Owner/Editor.
Exemplo de regra para o **projeto dedicado**, a configurar manualmente:

```text
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    match /{document=**} {
      allow read, write: if false;
    }
  }
}
```

## Limites públicos

Um processamento pesado por vez; 18 por minuto no processo. O limite de criação
é oito sessões por minuto; há também seis gravações e duas exportações por minuto
no processo, e cada sessão pode fazer 120 requisições por minuto.
Uploads de cartão: 10 MiB e 12 milhões de pixels. ZIP: até 8 MiB compactados,
20 imagens/páginas, 50 MiB descompactados, 10 páginas por PDF e dois lotes
temporários no processo. Esses limites reduzem abuso e consumo, mas não impedem
um ataque distribuído; controle adicional na borda e monitoramento de CPU,
memória e cobrança serão necessários para escala maior. A câmera em HTTPS
funciona para fotografar, sem análise periódica do enquadramento pelo backend.
O ZIP é temporário; se a Render reiniciar, reimporte o arquivo após reconciliar
as operações pendentes. O armazenamento local da Render é efêmero, portanto
nenhum resultado confirmado depende dele.

Na Vercel, configure Root Directory `Frontend`, sem framework ou build. O
frontend estático aponta para a origem HTTPS da Render, não contém credenciais
Firebase e envia apenas a capacidade anônima no cabeçalho. CORS e Host são
controles complementares; a assinatura da sessão e o namespace do banco fazem
o isolamento. Não use `APP_AMBIENTE=publico` para este fluxo.

## Checklist de ativação

1. Crie o projeto Firestore **novo e exclusivo**, aplique regras que neguem
   clientes, IAM mínimo à conta de serviço e confira os índices, inclusive o
   composto do histórico e o campo `expires_at` da limpeza.
2. Confirme os domínios reais da Vercel/Render e configure todas as variáveis e
   o Secret File na Render. Preserve as duas chaves entre deploys; alterar
   `PUBLIC_SESSION_KEY` invalida todas as sessões existentes.
3. Revise os arquivos Git a publicar. Publique o código e execute **deploy
   manual** do backend; confirme build, inicialização e `/api/health`. Se a
   Vercel fizer deploy automático após push, coordene a publicação para não
   mostrar temporariamente um frontend apontando para uma API ainda em homologação.
4. Faça piloto **somente com dados fictícios**: sessão A e B em navegadores
   separados, avaliação, aluno, imagem/PDF, ZIP com PDF multipágina, revisão,
   salvamento, reenvio idempotente, histórico, CSV e recuperação. Confirme que
   B não lê nem altera registros ou lotes de A. Saúde 200 sozinha não aprova o
   piloto. Confira CPU, RSS, tempo e erros no painel Render.
5. Publique/atualize o frontend estático na Vercel, valide câmera em HTTPS,
   teste os fluxos pelo domínio final e confirme a rotina diária de limpeza.
   Se persistência, índices ou isolamento falharem, volte a Render para
   `homologacao` e não aceite dados reais até corrigir.
