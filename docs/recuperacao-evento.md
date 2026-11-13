# Recuperar correção com resposta inconclusiva

No modo `local_operacional`, a correção confirmada é gravada em uma transação Firestore junto com `operacoes/correcao-<operacao_id>`. Repetir **o mesmo ID e o mesmo conteúdo** retorna o registro anterior; usar o mesmo ID com conteúdo diferente é rejeitado. Uma resposta HTTP perdida não prova que o banco falhou.

Antes de enviar, o navegador guarda em `localStorage` o ID e somente os campos necessários para repetir o POST: avaliação, nome/ID do aluno, respostas, resultado conferido, comprovante e confirmações. Não guarda PDF, foto, imagem anotada, credenciais ou tokens. Até 20 correções pendentes podem ficar registradas. O armazenamento é local à origem `http://127.0.0.1:8000` (ou origem loopback usada); trocar navegador, porta, host ou perfil Windows não transfere essas pendências. O conteúdo contém dados pessoais necessários à recuperação: use computador dedicado, bloqueie a sessão Windows e limpe o perfil do navegador de acordo com a política de retenção **depois** de reconciliar todas as pendências.

Enquanto existir uma pendência, o navegador bloqueia o salvamento de outra correção com conteúdo diferente. Resolva a pendência pela consulta e pelo reenvio do mesmo ID antes de passar ao próximo cartão; isso evita que uma resposta perdida leve à criação acidental de outro ID para a mesma folha.

## Durante o evento

1. Se aparecer **“Correção salva com sucesso”** e o ID do registro, a resposta de gravação chegou. Confira o histórico quando necessário.
2. Se houver falha de rede, 503, atualização ou fechamento antes da confirmação, trate como **situação desconhecida**. Não marque como salva nem refaça a folha com um novo ID.
3. Reabra `http://127.0.0.1:8000/interface/#correcao` no mesmo navegador/perfil e no mesmo endereço. Em **“Correções aguardando confirmação”**, clique em **“Consultar estado”**.
4. Se o banco responder **confirmada**, anote o ID do registro e confira o histórico. A pendência local é removida.
5. Se responder **não encontrada agora**, isso não garante que a requisição anterior terminou. Clique em **“Reenviar mesma operação”**; o navegador consulta novamente e só então reenvia **exatamente os dados guardados com o mesmo `operacao_id`**. Se a transação anterior concluir nesse intervalo, a idempotência devolve o mesmo registro, sem criar outro.
6. Se a consulta ou o reenvio falhar, mantenha a pendência e tente novamente quando a conexão voltar. Não faça reenvios automáticos ou crie uma segunda operação para a mesma folha.

Se o armazenamento do navegador estiver ilegível ou indisponível, o envio é bloqueado antes do POST. Preserve o perfil e peça suporte; não limpe os dados do site ou reinstale o navegador. Se o computador for reiniciado, inicie backend e navegador novamente no mesmo endereço. Se o disco ou perfil for perdido, o ID local pode se perder; compare histórico e exportação/backup antes de recapturar qualquer folha. A ausência momentânea de documento de operação **não comprova que a correção jamais será gravada**. O servidor não registra nomes, respostas ou tokens em logs de recuperação.

O mecanismo depende da origem local e da persistência do navegador e Firestore. Ele não substitui backup, ensaio de restauração nem a conferência final de contagem de gabaritos versus registros antes de encerrar o evento.
