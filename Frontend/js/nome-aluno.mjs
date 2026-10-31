// Sugestão local revisável; nunca sobrescreve uma edição manual ou salva dados.
export class StudentNameReader {
  constructor({field, status, recognize, onChange, onPending}) {
    Object.assign(this, {field, status, recognize, onChange, onPending});
    this.job = 0;
    this.revision = 0;
    this.autoValue = null;
    field.addEventListener('input', () => {
      this.revision++;
      this.autoValue = null;
      status.textContent = 'Nome editável. Confira antes de confirmar o salvamento.';
    });
  }
  clear() {
    this.job++;
    this.controller?.abort();
    if (this.autoValue !== null && this.field.value === this.autoValue) {
      this.field.value = '';
      this.onChange();
    }
    this.autoValue = null;
    this.onPending(false);
    this.status.textContent = 'O nome será sugerido após a captura. Você também pode digitá-lo.';
  }
  async read(file, fields) {
    this.clear();
    if (this.field.value.trim()) {
      this.status.textContent = 'Nome digitado mantido. Confira se corresponde ao cartão.';
      return;
    }
    const job = this.job, revision = this.revision;
    this.controller = new AbortController();
    this.onPending(true);
    this.status.textContent = 'Lendo o nome no cartão…';
    try {
      const data = await this.recognize(file, fields, this.controller.signal);
      if (job !== this.job || revision !== this.revision || this.field.value.trim()) return;
      this.status.textContent = data.mensagem;
      if (data.estado === 'sugerido' && data.nome) {
        this.field.value = data.nome;
        this.autoValue = data.nome;
        this.onChange();
      }
    } catch (error) {
      if (job === this.job && revision === this.revision) {
        this.status.textContent = 'Não foi possível ler o nome. Preencha manualmente.';
      }
    } finally {
      if (job === this.job) this.onPending(false);
    }
  }
}
