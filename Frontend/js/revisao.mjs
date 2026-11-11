const $ = (id) => document.getElementById(id);

export function renderOfficial(recognized, updateButtons) {
  $("answer-grid").replaceChildren();
  let marked = 0;
  for (let block = 0; block < 2; block++) {
    const column = document.createElement("div");
    column.className = "answer-column";
    const title = document.createElement("h3");
    title.textContent = block ? "Matemática · 26–50" : "Português · 1–25";
    column.append(title);
    for (let row = 1; row <= 25; row++) {
      const number = String(block * 25 + row),
        item = recognized[number];
      const wrapper = document.createElement("label");
      wrapper.className = "answer-row";
      const label = document.createElement("span");
      label.textContent = number.padStart(2, "0");
      const select = document.createElement("select");
      select.dataset.question = number;
      select.setAttribute(
        "aria-label",
        `Alternativa oficial da questão ${number}`,
      );
      select.append(
        new Option("—", ""),
        ..."ABCDE".split("").map((value) => new Option(value, value)),
      );
      select.value = item.estado === "marcada" ? item.resposta : "";
      if (select.value) marked += 1;
      const note = document.createElement("small");
      note.textContent = item.estado === "marcada" ? "" : item.estado;
      select.addEventListener("change", () => {
        $("confirm-official").checked = false;
        note.textContent = "revisada";
        updateButtons();
      });
      wrapper.append(label, select, note);
      column.append(wrapper);
    }
    $("answer-grid").append(column);
  }
  $("review-count").textContent = `${marked}/50 lidas · confira`;
  $("official-review").hidden = false;
  $("official-empty").hidden = true;
}

export function renderResult(data) {
  $("result-empty").hidden = true;
  $("result-content").hidden = false;
  $("result-state").textContent = data.provisorio
    ? "Provisório · revisar"
    : "Sem pendências";
  $("total-score").textContent = data.resumo.pontuacao;
  $("total-percent").textContent =
    `${data.resumo.percentual_acertos}% de acertos`;
  $("result-counts").replaceChildren();
  for (const [key, title] of Object.entries({
    acertos: "Acertos",
    erros: "Erros",
    brancos: "Em branco",
    multiplas: "Múltiplas",
    duvidosas: "Duvidosas",
    pendentes: "Pendências",
  })) {
    const cell = document.createElement("div");
    cell.className = "count";
    const value = document.createElement("strong");
    value.textContent = data.resumo[key];
    cell.append(value, document.createTextNode(title));
    $("result-counts").append(cell);
  }
  $("discipline-results").replaceChildren();
  for (const [key, title] of [
    ["portugues", "Português"],
    ["matematica", "Matemática"],
  ]) {
    const summary = data.disciplinas[key],
      line = document.createElement("div");
    line.className = "discipline";
    const label = document.createElement("span");
    label.textContent = title;
    const points = document.createElement("strong");
    points.textContent = `${summary.pontuacao}/25`;
    const percentage = document.createElement("small");
    percentage.textContent = `${summary.percentual_acertos}%`;
    points.append(percentage);
    line.append(label, points);
    $("discipline-results").append(line);
  }
  $("pending-list").textContent = data.questoes_pendentes.length
    ? `Conferência manual: questões ${data.questoes_pendentes.join(", ")}. Não foi presumida uma alternativa para elas.`
    : "Resultado sem pendências de leitura. Confira os dados antes de salvar.";
  $("provisional-label").hidden = !data.provisorio;
  $("confirm-result").checked = false;
  $("allow-provisional").checked = false;
}
