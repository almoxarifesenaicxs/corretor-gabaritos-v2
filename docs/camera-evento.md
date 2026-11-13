# Câmera e captura durante o evento

No modo `local_operacional`, a webcam é apenas uma forma de fornecer o cartão. Upload de **PNG, JPG ou PDF** continua disponível no mesmo fluxo de reconhecimento, OCR, revisão visual e salvamento. O navegador fecha a câmera ao sair da aba, atualizar a página ou trocar de seção; ao voltar de uma suspensão do computador, reative a webcam antes de capturar. A moldura de enquadramento é uma ajuda visual: confira sempre a imagem, o aluno, a avaliação e as respostas antes de salvar.

## Se a câmera falhar

1. Clique em **Desligar** ou **Cancelar ativação**. Se a câmera foi desconectada, reconecte-a e tente **Ativar webcam** novamente. Feche outros aplicativos que possam estar usando a câmera e confira a permissão do navegador.
2. Se não houver prévia confiável, fotografe ou digitalize o cartão por outro meio e use **Selecionar arquivo** com PNG, JPG ou PDF de até 10 MiB. Confira nitidez, orientação e enquadramento antes de reconhecer.
3. Continue a correção e a revisão visual normalmente. Não trate uma captura como resultado salvo; o salvamento só é confirmado pela resposta do backend. Em resposta inconclusiva, siga [recuperacao-evento.md](recuperacao-evento.md) antes de repetir uma folha.
4. Anote o número de cartões físicos processados e compare com o CSV e o resumo de conferência ao longo do evento.

A análise automática do enquadramento inicia cerca de 0,5 s após a ativação, depois espera 3 s entre respostas bem-sucedidas e 5 s após falha temporária; um quadro ainda indisponível é tentado novamente após 1 s. Isso limita uma câmera ativa a aproximadamente 1.200 análises por hora em condições ideais, contra até 3.000 com o intervalo anterior de 1,2 s, sem contar o tempo de processamento. Pare a câmera quando não estiver posicionando um cartão. Uma análise em andamento é abortada ao encerrar; respostas tardias não devem alterar a interface.

O ambiente de testes usa streams e APIs simulados. Antes do evento, faça um ensaio com a webcam, navegador, iluminação, rede e computador que serão usados; teste também a troca para upload de arquivo. Ainda pode haver falhas de hardware, permissões ou drivers que os testes simulados não reproduzem.
