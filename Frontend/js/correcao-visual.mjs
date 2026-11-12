export const COLORS = {
  correta: "#22c55e",
  incorreta: "#ef4444",
  pendente: "#facc15",
  branco: "#94a3b8",
};
const SYMBOLS = { correta: "+", incorreta: "x", pendente: "?", branco: "-" };

export function drawAnnotations(ctx, image, positions, marks) {
  ctx.clearRect(0, 0, image.width, image.height);
  ctx.drawImage(image, 0, 0);
  let count = 0;
  for (const [number, mark] of Object.entries(marks)) {
    const row = positions[number];
    if (!row || !COLORS[mark.estado]) continue;
    const candidates = mark.alternativas.length
      ? mark.alternativas
      : Object.keys(row);
    const boxes = candidates.map((letter) => row[letter]);
    // Nunca desenhar em uma posição ausente ou fora da imagem.
    if (
      !boxes.length ||
      boxes.some(
        (box) =>
          !box ||
          ![box.x, box.y, box.largura, box.altura].every(Number.isFinite) ||
          box.x < 0 ||
          box.y < 0 ||
          box.largura <= 0 ||
          box.altura <= 0 ||
          box.x + box.largura > image.width ||
          box.y + box.altura > image.height,
      )
    )
      continue;
    ctx.strokeStyle = COLORS[mark.estado];
    ctx.fillStyle = COLORS[mark.estado];
    ctx.lineWidth = Math.max(2, image.width / 500);
    for (const box of boxes)
      ctx.strokeRect(box.x, box.y, box.largura, box.altura);
    const first = row.A || boxes[0];
    ctx.font = `bold ${Math.max(11, Math.min(17, first.altura * 0.5))}px sans-serif`;
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(
      `${number}${SYMBOLS[mark.estado]}`,
      Math.max(24, first.x - 4),
      first.y + first.altura / 2,
    );
    count++;
  }
  return count;
}

export function manualAnswer(original, selection) {
  if (selection === "original") return structuredClone(original);
  if (selection === "branco")
    return { resposta: null, estado: "branco", alternativas: [] };
  if (!/^[A-E]$/.test(selection))
    throw new Error("Selecione uma alternativa válida.");
  return { resposta: selection, estado: "marcada", alternativas: [selection] };
}

export class VisualCorrection {
  constructor({ canvas, grid, status, onReview }) {
    Object.assign(this, { canvas, grid, status, onReview });
    this.generation = 0;
  }
  clear() {
    this.generation++;
    this.image = null;
    this.original = null;
    this.responses = null;
    this.comprovante = null;
    this.positions = null;
    this.marks = null;
    this.grid.replaceChildren();
    this.canvas.hidden = true;
    this.canvas.width = 1;
    this.canvas.height = 1;
  }
  async load(data) {
    this.clear();
    this.original = structuredClone(data.respostas);
    this.responses = structuredClone(data.respostas);
    this.comprovante = data.comprovante;
    this.positions = data.visualizacao.posicoes;
    this.marks = data.marcacoes;
    this.status.textContent = data.visualizacao.mensagem;
    const generation = this.generation;
    if (data.visualizacao.imagem) {
      try {
        const image = new Image();
        image.src = data.visualizacao.imagem;
        await image.decode();
        if (generation !== this.generation) return;
        this.image = image;
        this.canvas.width = image.width;
        this.canvas.height = image.height;
        this.canvas.hidden = false;
        this.redraw();
      } catch {
        if (generation === this.generation)
          this.status.textContent =
            "Imagem indisponível. Use a conferência textual.";
      }
    }
    if (generation !== this.generation) return;
    for (let block = 0; block < 2; block++) {
      const column = document.createElement("div");
      column.className = "answer-column";
      const title = document.createElement("h3");
      title.textContent = block ? "Matemática" : "Português";
      column.append(title);
      for (let i = 1; i <= 25; i++) {
        const number = String(block * 25 + i);
        const row = document.createElement("label");
        row.className = "answer-row";
        const label = document.createElement("span");
        label.textContent = number;
        const select = document.createElement("select");
        select.dataset.studentQuestion = number;
        select.setAttribute(
          "aria-label",
          `Conferir resposta da questão ${number}`,
        );
        select.append(
          new Option(
            `Leitura: ${this.original[number].resposta || this.original[number].estado}`,
            "original",
          ),
          ..."ABCDE".split("").map((letter) => new Option(letter, letter)),
          new Option("Em branco", "branco"),
        );
        let accepted = "original";
        select.addEventListener("change", async () => {
          const updated = structuredClone(this.responses);
          updated[number] = manualAnswer(this.original[number], select.value);
          try {
            const reviewed = await this.onReview(updated);
            if (generation !== this.generation) return;
            if (!reviewed) { select.value = accepted; return; }
            this.responses = updated;
            this.comprovante = reviewed.comprovante;
            this.marks = reviewed.marcacoes;
            accepted = select.value;
            this.redraw();
          } catch {
            select.value = accepted;
          }
        });
        row.append(label, select);
        column.append(row);
      }
      this.grid.append(column);
    }
  }
  redraw() {
    if (!this.image) return;
    const count = drawAnnotations(
      this.canvas.getContext("2d"),
      this.image,
      this.positions,
      this.marks,
    );
    if (count < 50)
      this.status.textContent = `${count}/50 questões com posição segura. As demais permanecem somente no resultado textual.`;
  }
}
