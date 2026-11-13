# Exportação e conferência no evento

Disponível **somente** no backend iniciado com `APP_AMBIENTE=local_operacional`, acessado diretamente pelo loopback no próprio computador. A rota `GET /api/correcoes/exportar` também exige esse modo; não está disponível em `homologacao`, `publico_demo` ou outros modos. O frontend local usa a API local e mostra a seção **Exportação e conferência do evento** na aba Correção.

## Procedimento para o operador

1. Pare novas correções por alguns instantes. Resolva as operações pendentes exibidas na aba Correção e confira a conexão com o banco.
2. Em **Exportação e conferência do evento**, escolha **Todas as avaliações** ou uma avaliação e clique em **Baixar correções em CSV**. Aguarde a mensagem de conclusão; se aparecer erro, descarte qualquer arquivo daquela tentativa e tente novamente. O sistema só inicia o download após ler todas as páginas.
3. Confira na tela o total de correções confirmadas, alunos distintos e pendências conhecidas neste navegador. Clique em **Baixar resumo de conferência** para guardar o manifesto JSON, que contém os pares `correcao_id`/`operacao_id` e os IDs de operações ainda pendentes no navegador.
4. Compare a contagem do CSV com a contagem do resumo e com o número físico de cartões já processados. Verifique IDs ausentes ou repetidos. Resolva pendências com **Consultar estado** antes de repetir uma folha. Repita a exportação em intervalos regulares e ao encerrar o evento.
5. Guarde CSV e resumo em local seguro com acesso restrito e cópia de segurança. Eles contêm nomes e notas de alunos. Não envie os arquivos para serviços públicos nem deixe cópias em computadores compartilhados.

O CSV usa UTF-8 com BOM, ponto e vírgula e uma linha por correção. Campos: ID da correção, ID da operação, ID e nome do aluno, ID e título da avaliação, data/hora UTC, acertos, erros, brancos, pontuação total, pontuação de Português e Matemática e situação. Campos textuais que poderiam ser interpretados como fórmula em planilhas recebem um apóstrofo inicial; os valores numéricos e os IDs originais permanecem no manifesto JSON. Nenhuma imagem, resposta individual, token ou credencial é exportada.

**Todas as avaliações** significa todas as correções presentes no banco, inclusive de períodos anteriores. O modelo atual não possui um identificador de evento. Se houver dados anteriores, selecione cada avaliação do evento e confira seus arquivos separadamente; não interprete a opção geral como filtro automático pela data de 14/11/2026.

Correções antigas podem não ter `operacao_id` no próprio documento. Nesse caso, a exportação consulta as operações confirmadas para reconstruir o vínculo. Se não existir vínculo, a linha permanece no CSV com ID de operação vazio e o resumo informa `operacoes_sem_id`; **não invente um ID**. Para registros sem `aluno_id`, a contagem de alunos distintos por nome é apenas aproximada e o resumo marca `alunos_distintos_exatos=false`.

A consulta percorre páginas de até 200 documentos, sem limite silencioso. Acima de 20.000 correções ou 40.000 operações legadas examinadas, a exportação falha explicitamente e não gera arquivo. O filtro por avaliação usa `prova_id`; se o Firestore solicitar um índice para `prova_id` com ordenação por nome do documento, crie-o e valide-o antes do evento em ambiente controlado. Uma falha em qualquer página ou avaliação associada também cancela o arquivo inteiro. A exportação não é um snapshot transacional de todo o Firestore: novas gravações simultâneas podem alterar a contagem durante a leitura. Por isso o procedimento pede uma pausa para a conferência. A contagem de pendências vem apenas do navegador/perfil/origem em uso, não de outros computadores.

O modo local não separa pessoas com acesso físico à mesma sessão do Windows. Proteja o computador e confira as cópias regularmente. O CSV é uma cópia de conferência e não substitui um backup testado do Firestore.
