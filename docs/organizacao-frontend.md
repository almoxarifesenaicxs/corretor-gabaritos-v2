# Organização do frontend

Abra a aplicação pelo FastAPI em `/interface/`. O `index.html` contém o menu,
cabeçalho, mensagens, rodapé e pontos de inserção do conteúdo.

- `pages/avaliacoes.html`: identificação, conferência do gabarito e lista de avaliações.
- `pages/correcao.html`: identificação do aluno, vínculo, resultado e correção visual.
- `pages/alunos.html`: pesquisa, listagem e histórico.
- `components/captura.html`: captura compartilhada por Avaliações e Correção.

Esses arquivos são fragmentos HTML com templates identificados por `data-slot`;
não são documentos para abertura direta. `js/paginas.mjs` busca os quatro arquivos
em paralelo, verifica os pontos de inserção e substitui os placeholders sem
adicionar contêineres. Todos permanecem no DOM, como antes, e a navegação mantém
a alternância de visibilidade. Não há recarregamento a cada troca de aba.

`app.mjs` coordena o carregamento e só então importa o layout e o fluxo da
aplicação. A navegação permanece desabilitada até a inicialização. Uma falha no
carregamento apresenta uma mensagem para recarregar, sem iniciar a câmera ou
consultar dados da aplicação.

`fluxo-captura.mjs` mantém o estado compartilhado, a navegação e a coordenação
dos serviços existentes. `revisao.mjs` renderiza o gabarito e o resultado.
Os módulos de API, câmera, OCR, alunos e correção visual continuam separados.
O CSS e os contratos HTTP não foram alterados.

Validação: suíte Python, testes unitários JavaScript e testes Chrome com câmera
simulada e persistência simulada. Os testes de navegador incluem navegação nas
três áreas, cadastro, correção, OCR, moldura, carregamento atrasado e falha de
fragmento. A validação não utiliza o Firebase real nem comprova uma webcam USB física.
