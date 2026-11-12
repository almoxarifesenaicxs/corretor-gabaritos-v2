import { request } from "./api.mjs";
const $ = (id) => document.getElementById(id);

// Somente consulta e escolha de homônimos. Nenhum cadastro ocorre neste módulo.
export class Students {
  constructor({ onSelect }) {
    this.onSelect = onSelect;
    this.selectedId = null;
    this.matchJob = 0;
    this.listJob = 0;
    $("student-link-select").addEventListener("change", () =>
      this.select($("student-link-select").value || null),
    );
    $("student-new-homonym").addEventListener("change", () => {
      this.select(null);
      $("student-link-select").value = "";
      $("student-link-select").disabled = $("student-new-homonym").checked;
    });
    $("student-name").addEventListener("input", () => {
      this.resetSelection();
      clearTimeout(this.matchTimer);
      this.matchJob++;
      this.matchTimer = setTimeout(() => this.refreshMatches(), 350);
    });
    $("student-search").addEventListener("input", () => {
      clearTimeout(this.searchTimer);
      this.listJob++;
      this.searchTimer = setTimeout(() => this.load(), 300);
    });
  }
  clear() {
    clearTimeout(this.matchTimer);
    clearTimeout(this.searchTimer);
    this.matchJob++;
    this.listJob++;
    this.historyId = null;
    this.selectedId = null;
    $("students-list").replaceChildren();
    $("student-history").replaceChildren();
    $("student-history-title").textContent = "";
    $("student-link-select").replaceChildren();
    $("student-link-status").textContent = "";
    $("student-search").value = "";
  }
  select(id) {
    this.selectedId = id;
    this.onSelect(id);
  }
  resetSelection() {
    this.select(null);
    $("student-new-homonym").checked = false;
    $("student-link-select").disabled = false;
  }
  saveOptions() {
    return {
      aluno_id: this.selectedId,
      novo_homonimo: $("student-new-homonym").checked,
    };
  }
  showAmbiguity(matches) {
    this.resetSelection();
    $("student-link-select").replaceChildren(
      new Option("Selecione o cadastro correto", ""),
      ...matches.map(
        (a) => new Option(`${a.nome} · cadastro ${a.id.slice(0, 8)}`, a.id),
      ),
    );
    $("student-link-select").hidden = false;
    $("student-homonym-label").hidden = !matches.length;
    $("student-link-status").textContent =
      "Há pessoas cadastradas com esse nome. Selecione o cadastro ou confirme outra pessoa, depois confirme o salvamento novamente.";
  }
  async refreshMatches() {
    const job = ++this.matchJob,
      name = $("student-name").value.trim();
    $("student-link-select").hidden = true;
    $("student-homonym-label").hidden = true;
    $("student-link-status").textContent =
      "O cadastro e a associação acontecem somente ao salvar a correção.";
    if (!name) return;
    try {
      const data = await request(
        "/api/alunos/correspondencias?nome=" + encodeURIComponent(name),
      );
      if (job !== this.matchJob || $("student-name").value.trim() !== name)
        return;
      const matches = data.exatos || (data.exato ? [data.exato] : []);
      if (matches.length > 1) this.showAmbiguity(matches);
      else {
        $("student-homonym-label").hidden = !matches.length;
        $("student-link-status").textContent = matches.length
          ? "Nome exato encontrado. Seu ID será reutilizado ao salvar. Se for outra pessoa com o mesmo nome, confirme abaixo."
          : "Sem correspondência exata. Um aluno será cadastrado somente quando você salvar a correção.";
        if (data.semelhantes.length)
          $("student-link-status").textContent +=
            " Nomes semelhantes não serão associados: " +
            data.semelhantes.map((a) => a.nome).join(", ");
      }
    } catch (error) {
      if (job === this.matchJob)
        $("student-link-status").textContent = error.message;
    }
  }
  async load() {
    const job = ++this.listJob;
    try {
      const students = await request(
        "/api/alunos?busca=" + encodeURIComponent($("student-search").value),
      );
      if (job !== this.listJob) return;
      $("students-list").replaceChildren();
      if (!students.length) {
        $("students-list").textContent = "Nenhum aluno encontrado.";
        return;
      }
      for (const student of students) {
        const row = document.createElement("div");
        row.className = "evaluation-item";
        const name = document.createElement("span");
        name.textContent = student.nome;
        const identity = document.createElement("small");
        identity.className = "helper";
        identity.textContent = ` · cadastro ${student.id.slice(0, 8)}`;
        name.append(identity);
        const button = document.createElement("button");
        button.className = "secondary";
        button.textContent = "Ver histórico";
        button.addEventListener("click", () => this.history(student.id));
        row.append(name, button);
        $("students-list").append(row);
      }
    } catch (error) {
      if (job === this.listJob) $("students-list").textContent = error.message;
    }
  }
  async history(id) {
    this.historyId = id;
    $("student-history").textContent = "Consultando histórico…";
    try {
      const data = await request(
        `/api/alunos/${encodeURIComponent(id)}/correcoes`,
      );
      if (this.historyId !== id) return;
      $("student-history-title").textContent = "Histórico · " + data.aluno.nome;
      $("student-history").replaceChildren();
      for (const [records, label] of [
        [data.correcoes, "Vinculadas ao cadastro"],
        [data.legadas_por_nome, "Antigas com mesmo nome — sem vínculo por ID"],
      ]) {
        const title = document.createElement("h3");
        title.textContent = label;
        $("student-history").append(title);
        if (!records.length) {
          const p = document.createElement("p");
          p.className = "helper";
          p.textContent = "Nenhuma correção.";
          $("student-history").append(p);
          continue;
        }
        const table = document.createElement("table");
        table.className = "history-table";
        const head = table.createTHead().insertRow();
        for (const text of [
          "Avaliação",
          "Pontos",
          "Acertos",
          "Data",
          "Situação",
        ]) {
          const cell = document.createElement("th");
          cell.textContent = text;
          head.append(cell);
        }
        const body = table.createTBody();
        for (const record of records) {
          const row = body.insertRow();
          for (const text of [
            record.avaliacao,
            `${record.resultado.resumo.pontuacao}/50`,
            `${record.resultado.resumo.percentual_acertos}%`,
            new Date(record.processada_em).toLocaleString("pt-BR"),
            record.situacao === "provisoria" ? "Provisória" : "Sem pendências",
          ])
            row.insertCell().textContent = text;
        }
        const scroll = document.createElement("div");
        scroll.className = "table-scroll";
        scroll.append(table);
        $("student-history").append(scroll);
      }
    } catch (error) {
      if (this.historyId === id)
        $("student-history").textContent = error.message;
    }
  }
}
