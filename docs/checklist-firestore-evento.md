# Pré-validação do Firestore para o evento de 14/11/2026

**Estado em 12/11/2026:** auditoria de código e testes simulados, sem conexão com Firebase/Firestore real, sem consulta a alunos reais e sem alteração de índices remotos. Este checklist prepara uma homologação posterior; nenhum item que dependa do projeto real foi considerado concluído.

## Modelo e caminhos de consulta

| Coleção | Documentos e finalidade | Caminhos usados no evento |
| --- | --- | --- |
| `alunos` | `id`, `nome`, `nome_normalizado`, `criado_em`; nomes iguais podem representar homônimos distintos. | Leitura por ID, igualdade e prefixo de `nome_normalizado`, páginas ordenadas por `nome_normalizado` e ID. Alunos antigos sem o campo entram em índice em memória após uma varredura por processo/projeto. |
| `provas` (avaliações) | `id`, `titulo`, `criada_em`. | Leitura por ID em cada salvamento e ao exportar; listagem de avaliações. |
| `gabaritos` | Mesmo ID da prova, 50 alternativas oficiais. | Leitura por ID em cada salvamento; criado junto com a prova. |
| `correcoes` | `id`, `prova_id`, `aluno_id`, `aluno`, `operacao_id`, `resultado`, `respostas`, `situacao`, `processada_em`; opcionalmente `origem_lote` com ID, índice e SHA-256 da imagem. | Criação na transação; histórico por `aluno_id`; consulta legada por `aluno`; exportação paginada por ID, com filtro opcional por `prova_id`. |
| `operacoes` | Documento `correcao-<UUID>` com assinatura e registro; também `avaliacao-<UUID>`. | Leitura por ID antes de gravar ou recuperar resposta perdida. Criação na mesma transação da correção. Na exportação, varredura de operações **somente** se algum registro antigo não tiver `operacao_id`. |
| `nomes_alunos` | Documento por hash do nome normalizado, com versão. | Leitura e atualização na transação para serializar decisões concorrentes sobre homônimos. |

O salvamento verificado lê operação, prova, gabarito e controle do nome, depois consulta `alunos.nome_normalizado` ou lê o aluno escolhido por ID. O servidor recalcula a nota contra o gabarito, confere a assinatura e grava correção, operação, controle do nome e, se necessário, aluno **na mesma transação**. Reenvio do mesmo `operacao_id` e payload retorna o registro anterior; payload diferente é conflito. O histórico paginado lê 30–31 correções por página, mais o aluno e, nas páginas seguintes, o documento do cursor. A exportação lê todas as correções em páginas de 200, sem truncar silenciosamente; para 1.000 registros consulta também os títulos das avaliações distintas. Falha em qualquer página invalida a exportação inteira.

## Índices a conferir antes de operar

Não existe `firestore.indexes.json` neste repositório. O estado remoto **é desconhecido**. Com indexação automática padrão, confirme índices de campo único na coleção para `alunos.nome_normalizado` (ascendente), `correcoes.aluno_id` (ascendente), `correcoes.aluno` (ascendente) e `correcoes.prova_id` (ascendente, para exportação filtrada). Verifique se não há isenções que os removam. Consultas por ID de documento não requerem índice de campo adicional.

O histórico paginado requer validar um índice composto de escopo **COLLECTION** para `correcoes`: `aluno_id ASCENDING`, `processada_em DESCENDING`, `__name__ ASCENDING`. A direção explícita ascendente de `__name__` na consulta difere do desempate descendente padrão de um índice cujo último campo é `processada_em DESCENDING`; portanto **não assuma** que apenas os dois primeiros campos bastam. Proposta para eventual `firestore.indexes.json`, **não criada nem publicada nesta etapa**:

```json
{
  "indexes": [
    {
      "collectionGroup": "correcoes",
      "queryScope": "COLLECTION",
      "fields": [
        { "fieldPath": "aluno_id", "order": "ASCENDING" },
        { "fieldPath": "processada_em", "order": "DESCENDING" },
        { "fieldPath": "__name__", "order": "ASCENDING" }
      ]
    }
  ]
}
```

O trecho é uma proposta, não um arquivo para implantar isoladamente: antes de qualquer publicação, compare-o com os índices e isenções já existentes para não sobrescrever definições remotas. Em homologação autorizada, execute a consulta exata e confira o índice sugerido pelo Firestore; compare-o com a definição acima. Um índice em construção ou com falha **não** está pronto. Registros antigos sem `processada_em` não aparecerão na consulta ordenada; registros sem `nome_normalizado` exigem varredura inicial. Não faça migração no dia do evento.

## Configuração obrigatória do modo `local_operacional`

- `APP_AMBIENTE=local_operacional`, `LOCAL_OPERACIONAL_HOST=127.0.0.1` (ou `::1`), `SERVIR_FRONTEND=true` e Uvicorn escutando o mesmo loopback, com `--no-proxy-headers --workers 1`. Não usar Vercel, Render, proxy, túnel nem `0.0.0.0` para a operação.
- `FIRESTORE_MODO=real`, `FIREBASE_PROJECT_ID` explícito e igual ao `project_id` do arquivo privado apontado por `GOOGLE_APPLICATION_CREDENTIALS`. Banco Firestore **(default)** do projeto correto; `FIRESTORE_EMULATOR_HOST` e `FIREBASE_AUTH_EMULATOR_HOST` ausentes.
- `INTEGRIDADE_CHAVE` privada, estável entre reinícios, com 32 bytes aleatórios representados por 64 caracteres hexadecimais. Sem `CORS_ORIGINS`, `FORWARDED_ALLOW_IPS` ou variáveis que identifiquem hospedagem pública.
- JSON da conta de serviço **fora do repositório e do frontend**, protegido por permissões do Windows e sem compartilhamento. `.gitignore` cobre alguns nomes comuns e `.secrets/`, mas nomes arbitrários de JSON não são automaticamente ignorados. Confira a área de staging antes de qualquer commit. A conta precisa de acesso IAM apenas ao banco/projeto requerido. As regras de segurança do cliente Firestore **não limitam** o Admin SDK; este usa IAM.

A inicialização verifica presença, formato, projeto e chave privada do arquivo, além dos modos, host e chave de integridade. Não há fallback automático para emulador. **Não valida na inicialização** existência do banco, permissão IAM efetiva, conectividade, cotas ou índices prontos: a primeira operação pode falhar com indisponibilidade. Não interprete `/api/health` como teste de gravação.

## Projeção de consumo para 1.000 correções

Valores abaixo são **projeções de documentos**, não medição do serviço. Para cada novo salvamento com nome único: cerca de quatro leituras de documentos (operação, prova, gabarito, controle do nome) mais uma consulta exata de aluno com cobrança mínima mesmo vazia; aproximadamente **5.000 leituras** para 1.000 correções, antes de repetições, cursores e index-entry reads. Uma varredura inicial de 1.000 alunos para compatibilidade legada acrescenta cerca de **1.000 leituras por processo**. Selecionar aluno por ID acrescenta a leitura desse documento em lugar da consulta por nome. Conflitos transacionais, homônimos, sugestões e histórico aumentam as leituras.

Cada correção cria três documentos/atualizações (`correcoes`, `operacoes`, `nomes_alunos`); se criar aluno, são quatro escritas. Portanto **3.000–4.000 escritas** para 1.000 correções, sem avaliações adicionais e sem tentativas concorrentes repetidas. Uma exportação integral de 1.000 correções acrescenta aproximadamente **1.000 leituras** de correções, mais avaliações distintas e consultas mínimas de páginas vazias. Se exportar após cada lote de 50, serão aproximadamente **10.500 leituras de correções** somadas ao longo das 20 exportações, pois cada arquivo relê tudo o que foi confirmado até então. O filtro atual é por avaliação, não por lote; use-o quando houver avaliações distintas e contabilize as leituras antes de aumentar a frequência dos backups. Registros legados sem `operacao_id` podem obrigar varrer `operacoes` e elevar muito o custo.

As cotas gratuitas atualmente documentadas são 50.000 leituras e 20.000 escritas de documentos por dia, compartilhadas com todo o uso do projeto e sujeitas a regras do plano e região. Leituras de entradas de índice, armazenamento de documentos/índices e tráfego também podem ser cobrados; não há garantia de custo zero. Verifique plano, região, orçamento e uso acumulado antes da operação. **Não trate limites de orçamento como bloqueio automático garantido de cobranças.**

## Checklist de homologação real — requer autorização explícita posterior

1. [ ] Identificar projeto e banco **(default)** corretos sem copiar IDs privados ou credenciais para o Git. Confirmar plano, cotas disponíveis, região, orçamento e alertas de cobrança com o responsável.
2. [ ] Preparar conta de serviço de menor privilégio, arquivo JSON fora do repositório com ACL restrita e `FIREBASE_PROJECT_ID` correspondente. Conferir regras de acesso do SDK cliente separadamente; para o backend, conferir IAM.
3. [ ] Confirmar índices de campo único e índice composto no console; aguardar estado **Ready**. Se faltar índice, criar em janela autorizada e repetir a consulta real de histórico paginado antes do evento.
4. [ ] Usar somente avaliações/alunos fictícios em projeto de teste ou área aprovada. Verificar consulta por nome, homônimo, histórico paginado, exportação com e sem filtro, cursor e leitura de registro legado. Não executar migração de dados reais.
5. [ ] Fazer pequena gravação controlada com mesmo `operacao_id` reenviado; confirmar um único registro, recálculo da nota, origem do lote, consulta de operação e CSV. Exercitar falha de rede e reinício antes de ampliar a carga.
6. [ ] Medir leituras, escritas, latência e erros reais durante um piloto representativo. Conferir uso pelo console/Query Explain sem usar dados pessoais. Ajustar plano e janelas de exportação se a projeção não couber na cota.
7. [ ] Registrar procedimento de backup aprovado e testar restauração fora dos dados reais. Exportar CSV e conferir total, IDs de operação e pendências após cada etapa definida. Guardar cópias conforme política de dados de alunos.
8. [ ] No dia, se salvar for inconclusivo, consultar a operação antes de reenviar o **mesmo** ID. Após reinício, conferir CSV e pendências antes de reimportar ZIP: novo lote ou nova operação não deduplica automaticamente a mesma imagem.

**Fontes oficiais para conferir no dia:** [índices](https://firebase.google.com/docs/firestore/query-data/index-overview), [criação e estado de índices](https://firebase.google.com/docs/firestore/query-data/indexing), [cotas](https://firebase.google.com/docs/firestore/quotas), [cobrança](https://firebase.google.com/docs/firestore/pricing), [Admin SDK](https://firebase.google.com/docs/admin/setup) e [IAM do Firestore](https://firebase.google.com/docs/firestore/security/iam).
