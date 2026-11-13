import { request } from "./api.mjs";
const $ = (id) => document.getElementById(id);

// Somente consulta e escolha de homônimos. Nenhum cadastro ocorre neste módulo.
export class Students {
  constructor({ onSelect }) {
    this.onSelect = onSelect;
    this.selectedId = null;
    this.matchJob = 0;
    this.listJob = 0;
    this.listCursor = null;
    this.historyCursor = null;
    this.listSearch = "";
    $("students-more").addEventListener("click", () => this.load(true));
    $("student-history-more").addEventListener("click", () => {
      if (this.historyId) this.history(this.historyId, true);
    });
    $("student-history-legacy").addEventListener("click", () => {
      if (this.historyId) this.loadLegacy(this.historyId);
    });
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
    this.listCursor = null;
    this.historyCursor = null;
    this.listSearch = "";
    $("students-more").hidden = true;
    $("student-history-more").hidden = true;
    $("student-history-legacy").hidden = true;
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
  saved(record) {
    // O retorno da gravação já contém o aluno escolhido. A lista será
    // consultada quando a aba Alunos for aberta, sem leitura extra por salvar.
    if (record.aluno_id) {
      this.selectedId = record.aluno_id;
      $("student-new-homonym").checked = false;
      $("student-link-select").disabled = false;
    }
    this.listCursor = null;
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
  async load(append = false) {
    const job = ++this.listJob;
    const search = $("student-search").value.trim();
    const cursor = append && search === this.listSearch ? this.listCursor : null;
    if (append && !cursor) return;
    if (!append) {
      this.listCursor = null;
      this.listSearch = search;
    }
    $("students-more").disabled = true;
    try {
      const page = await request(
        "/api/alunos?pagina=true&limite=30&busca=" + encodeURIComponent(search) +
        (cursor ? "&cursor=" + encodeURIComponent(cursor) : ""),
      );
      if (job !== this.listJob || search !== $("student-search").value.trim()) return;
      if (!append) $("students-list").replaceChildren();
      this.listCursor = page.proximo_cursor;
      $("students-more").hidden = !page.proximo_cursor;
      $("students-more").textContent = "Carregar mais alunos";
      if (!page.alunos.length && !append) {
        $("students-list").textContent = "Nenhum aluno encontrado.";
        return;
      }
      for (const student of page.alunos) {
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
      if (job === this.listJob) {
        if (append) $("students-more").textContent = error.message + " — tentar novamente";
        else $("students-list").textContent = error.message;
      }
    } finally {
      if (job === this.listJob) $("students-more").disabled = false;
    }
  }
  async history(id, append = false) {
    const cursor = append && this.historyId === id ? this.historyCursor : null;
    if (append && !cursor) return;
    const job = append ? this.historyJob : (this.historyJob = (this.historyJob || 0) + 1);
    this.historyId = id;
    if (!append) {
      this.historyCursor = null;
      $("student-history").textContent = "Consultando histórico…";
      $("student-history-legacy").hidden = true;
    }
    $("student-history-more").disabled = true;
    try {
      const data = await request(
        `/api/alunos/${encodeURIComponent(id)}/correcoes?pagina=true&limite=30` +
        (cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""),
      );
      if (this.historyId !== id || this.historyJob !== job) return;
      this.historyCursor = data.proximo_cursor;
      $("student-history-more").hidden = !data.proximo_cursor;
      $("student-history-more").textContent = "Carregar mais correções";
      if (append) {
        const body = $("student-history").querySelector(".history-table tbody");
        for (const record of data.correcoes) this.historyRow(body, record);
        return;
      }
      $("student-history-title").textContent = "Histórico · " + data.aluno.nome;
      $("student-history").replaceChildren();
      this.renderHistoryGroup(data.correcoes, "Vinculadas ao cadastro");
      $("student-history-legacy").hidden = false;
    } catch (error) {
      if (this.historyId === id && this.historyJob === job) {
        if (append) $("student-history-more").textContent = error.message + " — tentar novamente";
        else $("student-history").textContent = error.message;
      }
    } finally {
      if (this.historyId === id && this.historyJob === job)
        $("student-history-more").disabled = false;
    }
  }
  async loadLegacy(id) {
    const job = this.historyJob;
    $("student-history-legacy").disabled = true;
    try {
      const data = await request(
        `/api/alunos/${encodeURIComponent(id)}/correcoes?pagina=true&legadas=true`,
      );
      if (this.historyId !== id || this.historyJob !== job) return;
      this.renderHistoryGroup(data.legadas_por_nome, "Antigas com mesmo nome — sem vínculo por ID");
      $("student-history-legacy").hidden = true;
    } catch (error) {
      if (this.historyId === id && this.historyJob === job)
        $("student-history-legacy").textContent = error.message + " — tentar novamente";
    } finally {
      if (this.historyId === id && this.historyJob === job)
        $("student-history-legacy").disabled = false;
    }
  }
  renderHistoryGroup(records, label) {
    const title = document.createElement("h3");
    title.textContent = label;
    $("student-history").append(title);
    if (!records.length) {
      const p = document.createElement("p");
      p.className = "helper";
      p.textContent = "Nenhuma correção.";
      $("student-history").append(p);
      return;
    }
    const table = document.createElement("table");
    table.className = "history-table";
    const head = table.createTHead().insertRow();
    for (const text of ["Avaliação", "Pontos", "Acertos", "Data", "Situação"]) {
      const cell = document.createElement("th");
      cell.textContent = text;
      head.append(cell);
    }
    const body = table.createTBody();
    for (const record of records) this.historyRow(body, record);
    const scroll = document.createElement("div");
    scroll.className = "table-scroll";
    scroll.append(table);
    $("student-history").append(scroll);
  }
  historyRow(body, record) {
    const row = body.insertRow();
    for (const text of [
      record.avaliacao,
      `${record.resultado.resumo.pontuacao}/50`,
      `${record.resultado.resumo.percentual_acertos}%`,
      new Date(record.processada_em).toLocaleString("pt-BR"),
      record.situacao === "provisoria" ? "Provisória" : "Sem pendências",
    ]) row.insertCell().textContent = text;
  }
}
