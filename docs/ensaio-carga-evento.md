# Ensaio de carga para o evento de 14/11/2026

**Executado em 12/11/2026, sem Firebase real.** Este ensaio é uma verificação de laboratório, não uma aprovação para operar com dados reais. O ambiente foi Windows, Python 3.14.6, OpenCV 5.0.0, Intel Core i5-1135G7 (8 processadores lógicos) e 15,7 GiB de RAM. O motor e o fluxo de revisão visual foram executados de verdade; a persistência usou somente um cliente Firestore simulado.

## Amostra e método

`Backend/scripts/ensaio_carga_evento.py` gerou **1.000 JPGs fictícios de 50 questões**, distribuídos em **10 ZIPs de 100 imagens** em diretório temporário. As alternativas variam deterministicamente; 10 cartões têm uma questão em branco e 10 têm uma questão com duas marcas. O script importou cada ZIP pelo serviço real `LotesZIP`, leu uma imagem por vez, chamou o reconhecimento real, o cálculo real da nota, a assinatura das respostas, a classificação e a geração da visualização. Cancelou cada lote após terminar e reimportou o primeiro ZIP para verificar que recebe novo identificador. Nenhuma imagem ou ZIP de ensaio foi mantido no repositório.

O tempo de reconhecimento mede `reconhecer_arquivo()` por imagem. O tempo do fluxo mede reconhecimento, correção, assinatura e visualização. O tempo total do ensaio inclui geração dos ZIPs e sobrecarga de arquivos temporários. **Revisão, identificação de alunos, confirmação e operação humana não foram cronometradas.** Não houve chamada HTTP real, câmera, RapidOCR para nomes nem rede Firestore no teste de 1.000 imagens.

| Medida observada | Resultado |
| --- | ---: |
| ZIPs / imagens processadas | 10 / 1.000 |
| Geração dos ZIPs | 8,059 s |
| Processamento sequencial total | 51,912 s |
| Tempo total do script | 60,007 s |
| Reconhecimento: mediana / p95 / p99 | 19,4 / 22,3 / 35,0 ms |
| Fluxo com visualização: mediana / p95 / p99 | 48,7 / 57,0 / 70,5 ms |
| Reconhecimento: mínimo / máximo | 16,9 / 48,3 ms |
| Pico de memória do processo | 159,4 MiB |
| CPU do processo | 78,14 s de CPU; média de 130,2% de um núcleo durante 60,007 s |
| Erros de leitura ou divergências | 0 |
| Questões ambíguas / em branco identificadas | 10 / 10 |

A CPU pode passar de 100% de um núcleo porque bibliotecas nativas usam mais de uma thread. O pico de memória foi obtido do contador de pico do processo no Windows; não representa consumo do navegador, do sistema operacional ou de outros processos. Os resultados só se aplicam a esses cartões digitais limpos, nesta máquina. Fotografias, sombras, inclinação, resolução maior, PDF e cartões físicos podem mudar radicalmente latência e taxa de erro. O tempo automático de aproximadamente 52 s **não** equivale ao tempo para concluir 1.000 correções, pois cada item exige revisão humana e salvamento individual.

Para repetir, na pasta `Backend`, execute `\.venv\Scripts\python.exe scripts/ensaio_carga_evento.py`. Não configure credenciais reais para o ensaio. O script usa apenas arquivos temporários e não cria cliente Firebase.

## Integridade e recuperação

`Backend/tests/test_ensaio_integridade_evento.py` gravou **1.000 correções fictícias** com 10 identificadores de lote, índices 0–99, `operacao_id` e identificador de correção únicos, usando o contrato real de persistência sobre um cliente Firestore simulado. Em 10 operações, simulou resposta perdida: um novo objeto de persistência consultou a operação já confirmada e o reenvio com o mesmo `operacao_id` retornou a mesma correção. A exportação paginada gerou 1.000 linhas de CSV, 1.000 alunos distintos e preservou os identificadores de lote, imagem, operação e correção. Não houve correção duplicada. Esse teste não mede latência ou falhas do serviço Firestore real.

Os testes JavaScript de lote verificam pausa, continuação, cancelamento e contagens em dez lotes de cem; reimportação começa em estado pendente, sem confirmação automática. Um teste de reinício cria novo catálogo de ZIPs e confirma que o lote anterior deixa de ser consultável e que a reimportação recebe outro ID. Os testes de recuperação e navegador simulam queda de conexão, resposta de salvamento perdida e atualização de página: a operação pendente conserva seu identificador e exige consulta antes de reenvio. Os testes de ZIP cobrem entradas maliciosas e limites. Esses cenários são **simulações de contrato**, não um ensaio prolongado de falhas reais de rede ou reinício físico do computador.

**Limite crítico:** os ZIPs ficam em armazenamento temporário do backend. Reiniciar o backend perde o catálogo dos lotes, embora as correções confirmadas permaneçam na persistência. O operador precisa conferir CSV e operações pendentes, depois reimportar o ZIP. A reimportação cria outro `lote_id`; a mesma imagem pode receber novo `operacao_id` se for confirmada outra vez. A idempotência protege o reenvio da **mesma operação**, mas não deduplica automaticamente uma nova operação para a mesma imagem. A conferência por `imagem_sha256`, nome, aluno e avaliação antes de confirmar é indispensável.

## Validação automatizada

- Python: **435 passaram, 1 ignorado**, 1 aviso de depreciação do TestClient.
- JavaScript: **42 passaram**.
- Navegador: **19 passaram** com API simulada.
- `git diff --check`: sem erro de whitespace; Git mostrou apenas avisos de conversão LF/CRLF em arquivos preexistentes.

## Gargalos e decisão para o evento

1. O gargalo provável é **revisão humana e gravação remota**, que este ensaio não mediu. Cronometre um piloto com cartões físicos e operadores antes de projetar quantas pessoas/equipamentos são necessários. Não extrapole os 52 s automáticos para o evento.
2. Faça lotes operacionais de cerca de 50 imagens, com conferência e exportação CSV ao fim de cada lote. Mantenha cópias dos ZIPs originais em local aprovado. O limite técnico continua 100 imagens por ZIP.
3. Execute um piloto de ponta a ponta no computador e rede do evento, com Firestore de teste ou emulador isolado, medindo leitura, gravação, falhas e recuperação. Teste também PDF, celular e imagens reais desfocadas. **Sem esse piloto, o uso com dados reais não está validado.**
4. Se o backend reiniciar, não avance automaticamente pela numeração do ZIP. Reconcile cada operação pendente e as linhas do CSV antes de reimportar. Nunca trate o indicador local de progresso como prova de gravação.
5. Registre horário de início/fim, total conferido e backup de CSV após cada lote. A exportação precisa terminar sem falha; um arquivo parcial não deve ser tratado como cópia de segurança.

Não foi acessado ou alterado nenhum dado real de alunos; não houve deploy nem mudança de configuração da Render/Vercel.
