// Estados de interface; o registro confirmado permanece no backend, não neste objeto.
export class Lote {
  constructor(manifesto) {
    if (!/^[0-9a-f]{32}$/.test(manifesto?.lote_id) ||
        !Array.isArray(manifesto?.imagens) || manifesto.imagens.length !== manifesto.total)
      throw new Error("Manifesto do lote inválido.");
    this.id = manifesto.lote_id;
    if (manifesto.lote_token !== undefined &&
        !/^[A-Za-z0-9_-]{43}$/.test(manifesto.lote_token))
      throw new Error("Credencial temporária do lote inválida.");
    this.token = manifesto.lote_token || null;
    this.imagens = manifesto.imagens.map((item, indice) => ({
      ...item, indice,
      erro: /\.pdf$/i.test(item.nome) &&
        /^Formato não suportado\. Use JPG ou PNG\.$/i.test(item.erro || "")
          ? "Este backend ainda não aceita PDF no ZIP. Reinicie o backend local com a versão atual e importe o lote novamente."
          : item.erro,
      estado: item.estado === "falha" ? "falha" : "pendente",
      valida: item.estado !== "falha",
      tentada: false,
    }));
    this.atual = null;
    this.pausado = false;
    this.cancelado = false;
  }
  proxima() {
    if (this.pausado || this.cancelado || this.atual !== null) return null;
    const item = this.imagens.find(imagem => imagem.estado === "pendente");
    if (!item) return null;
    item.estado = "carregando";
    this.atual = item.indice;
    return item;
  }
  pronta() {
    const item = this.imagens[this.atual];
    if (!item || item.estado !== "carregando") throw new Error("Imagem fora de sequência.");
    item.estado = "pronta";
  }
  processada() {
    const item = this.imagens[this.atual];
    if (!item || item.estado !== "pronta") throw new Error("Imagem fora de sequência.");
    item.estado = "revisao";
    item.tentada = true;
  }
  falha(erro) {
    const item = this.imagens[this.atual];
    if (!item) return;
    item.estado = "falha";
    item.tentada = true;
    item.erro = String(erro).slice(0, 180);
    this.atual = null;
  }
  confirmada(operacaoId) {
    const item = this.imagens[this.atual];
    if (!item || item.estado !== "revisao") return;
    if (!/^[0-9a-f-]{36}$/i.test(operacaoId || ""))
      throw new Error("Confirmação do lote sem identificador de operação.");
    item.operacaoId = operacaoId;
    item.estado = "confirmada";
    this.atual = null;
  }
  repetir(indice) {
    const item = this.imagens[indice];
    if (!item || item.estado !== "falha" || this.atual !== null || this.cancelado) return false;
    item.estado = "pendente";
    item.erro = null;
    return true;
  }
  cancelar() {
    this.cancelado = true;
    this.pausado = false;
    for (const item of this.imagens)
      if (["pendente", "carregando", "pronta", "revisao"].includes(item.estado))
        item.estado = "cancelada";
    this.atual = null;
  }
  resumo() {
    const contar = estado => this.imagens.filter(item => item.estado === estado).length;
    return {
      entradas: this.imagens.length,
      identificadas: this.imagens.filter(item => item.valida).length,
      processadas: this.imagens.filter(item => item.tentada).length,
      confirmadas: contar("confirmada"),
      pendentes_revisao: contar("revisao"),
      falhas: contar("falha"),
      canceladas: contar("cancelada"),
    };
  }
}
