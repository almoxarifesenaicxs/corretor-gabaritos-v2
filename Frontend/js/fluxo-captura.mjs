import { renderOfficial, renderResult } from "./revisao.mjs";
import { tabFromHash } from "./paginas.mjs";

import {
  request,
  upload,
  jsonPost,
  validateFile,
  officialFromSelections,
  isApiAccessAllowed,
  apiUrl,
  requestBinary,
} from "./api.mjs";
import { Lote } from "./lote.mjs";
import { Camera, cameraError } from "./camera.mjs";
import { StudentNameReader } from "./nome-aluno.mjs";
import { Students } from "./alunos.mjs";
import { VisualCorrection } from "./correcao-visual.mjs";
import { createRecovery } from "./recuperacao.mjs";

const $ = (id) => document.getElementById(id);
let tab = "avaliacoes",
  source = null,
  sourceIsCapture = false,
  photoConfirmed = true,
  previewUrl = null;
let result = null,
  resultContext = null,
  evaluations = [],
  busy = false,
  state = "vermelho",
  cameraRequest = 0,
  cameraStarting = false;
let videoReadyCleanup = null;
let processGeneration = 0;
let sessionGeneration = 0;
let reviewRequest = 0;
const sessionCurrent = (generation) =>
  generation === sessionGeneration && isApiAccessAllowed();
let namePending = false;
const pendingOperations = new Map();
const recovery = createRecovery();
const recoveryStates = new Map();
let latestExport = null;
let lote = null;
let origemLote = null;
let loteOperacao = null;
let restaurandoLote = false;
let loteRestauracaoPendente = null;
const LOTE_KEY = "corretor:lote-operacional:v1";

function persistirLote() {
  if (!recovery.enabled) return;
  try {
    if (lote?.cancelado) localStorage.removeItem(LOTE_KEY);
    else if (lote) localStorage.setItem(LOTE_KEY, JSON.stringify({
      id: lote.id, atual: lote.atual, operacao: loteOperacao,
      estados: lote.imagens.map(item => ({ estado: item.estado, tentada: item.tentada,
        erro: item.erro, operacaoId: item.operacaoId })),
    }));
  } catch { /* A recuperação das operações de salvamento usa mecanismo separado. */ }
}

function renderLote() {
  if (!recovery.enabled) return;
  const resumo = $("batch-summary");
  const lista = $("batch-errors");
  lista.replaceChildren();
  if (!lote) {
    resumo.textContent = "Nenhum lote importado.";
    $("batch-current").textContent = "";
  } else {
    const dados = lote.resumo();
    resumo.textContent = `Itens no ZIP: ${dados.entradas} · Imagens identificadas: ${dados.identificadas} (inclui páginas PDF) · Processadas: ${dados.processadas} · Confirmadas: ${dados.confirmadas} · Pendentes de revisão: ${dados.pendentes_revisao} · Falhas: ${dados.falhas} · Canceladas: ${dados.canceladas}`;
    for (const item of lote.imagens) {
      const linha = document.createElement("div");
      linha.textContent = `${item.indice + 1}. ${item.nome}${item.pagina ? ` · página ${item.pagina}` : ""}: ${item.estado}${item.erro ? ` — ${item.erro}` : ""}`;
      if (item.estado === "falha" && !lote.cancelado) {
        const repetir = document.createElement("button");
        repetir.type = "button";
        repetir.className = "secondary";
        repetir.textContent = "Tentar novamente";
        repetir.addEventListener("click", () => {
          if (lote.repetir(item.indice)) renderLote();
        });
        linha.append(" ", repetir);
      }
      lista.append(linha);
    }
  }
  persistirLote();
  updateButtons();
}

async function restaurarLote() {
  if (!recovery.enabled || lote) return;
  let anterior;
  try { anterior = JSON.parse(localStorage.getItem(LOTE_KEY) || "null"); }
  catch { localStorage.removeItem(LOTE_KEY); return; }
  if (!/^[0-9a-f]{32}$/.test(anterior?.id)) return;
  restaurandoLote = true;
  updateButtons();
  try {
    const manifesto = await request(`/api/lotes/${anterior.id}`);
    if (lote) return;
    const restaurado = new Lote(manifesto);
    if (!Array.isArray(anterior.estados) || anterior.estados.length !== restaurado.imagens.length)
      throw new Error("Estado local do lote incompatível.");
    for (const estado of anterior.estados) {
      if (estado.estado !== "confirmada") continue;
      if (!/^[0-9a-f-]{36}$/i.test(estado.operacaoId || ""))
        throw new Error("Identificador de confirmação do lote ausente.");
      const confirmado = await request(`/api/operacoes/correcao/${encodeURIComponent(estado.operacaoId)}`);
      if (confirmado.estado !== "confirmada")
        throw new Error("Correção do lote não confirmada pelo backend.");
    }
    for (const [indice, estado] of anterior.estados.entries()) {
      const item = restaurado.imagens[indice];
      if (item.estado === "falha") continue;
      if (estado.estado === "confirmada" || estado.estado === "falha") {
        item.estado = estado.estado;
        item.operacaoId = estado.operacaoId;
        item.tentada = Boolean(estado.tentada);
        item.erro = estado.estado === "falha" ? String(estado.erro || "Falha anterior.").slice(0, 180) : null;
      }
    }
    if (Number.isInteger(anterior.atual) && anterior.atual >= 0 &&
        anterior.atual < restaurado.imagens.length && anterior.operacao &&
        recovery.get(anterior.operacao)) {
      restaurado.atual = anterior.atual;
      restaurado.imagens[anterior.atual].estado = "revisao";
      loteOperacao = anterior.operacao;
    }
    restaurado.pausado = true;
    lote = restaurado;
    $("batch-pause").textContent = "Continuar";
    $("batch-current").textContent = loteOperacao
      ? "Há salvamento inconclusivo: consulte a operação pendente antes de continuar."
      : "Lote restaurado em pausa. Confira o CSV antes de continuar; imagens não revistas devem ser carregadas novamente.";
    renderLote();
  } catch (error) {
    if (error.status === 404) localStorage.removeItem(LOTE_KEY);
    else loteRestauracaoPendente = anterior.id;
    $("batch-current").textContent = error.status === 404
      ? "ZIP temporário perdido. Confira o CSV e reimporte o lote."
      : "Restauração pendente: confira o CSV e a conexão. Após a conferência, cancele este lote para reimportar.";
    message("Não foi possível restaurar o lote com confirmação do backend. Confira o CSV e tente novamente. " + error.message, true);
  } finally {
    restaurandoLote = false;
    updateButtons();
  }
}

async function carregarImagemLote() {
  if (!lote || lote.pausado || lote.atual !== null || busy) return;
  const generation = sessionGeneration;
  try {
    if (recovery.list().length)
      throw new Error("Resolva a operação inconclusiva antes de continuar o lote.");
    const item = lote.proxima();
    if (!item) { message("Não há outras imagens pendentes neste lote."); return; }
    renderLote();
    setBusy(true, "Carregando imagem do lote…");
    const resposta = await requestBinary(`/api/lotes/${lote.id}/imagens/${item.indice}`);
    if (!sessionCurrent(generation)) return;
    const dados = await resposta.arrayBuffer();
    if (!sessionCurrent(generation)) return;
    if (!dados.byteLength || dados.byteLength > 10 * 1024 * 1024)
      throw new Error("Imagem vazia ou acima de 10 MiB.");
    const resumo = [...new Uint8Array(await crypto.subtle.digest("SHA-256", dados))]
      .map(byte => byte.toString(16).padStart(2, "0")).join("");
    if (!sessionCurrent(generation)) return;
    if (resumo !== resposta.headers.get("X-Image-SHA256"))
      throw new Error("Imagem do lote não passou na conferência de integridade.");
    const nome = item.nome.split("/").at(-1);
    const pdf = /\.pdf$/i.test(nome);
    const tipo = /\.png$/i.test(nome) ? "image/png" : "image/jpeg";
    const nomeImagem = pdf ? `${nome.replace(/\.pdf$/i, "")}-pagina-${item.pagina}.jpg` : nome;
    const arquivo = new File([dados], nomeImagem, { type: tipo });
    validateFile(arquivo);
    $("student-name").value = "";
    students.resetSelection();
    students.refreshMatches();
    setSource(arquivo, false, true);
    origemLote = { lote_id: lote.id, indice: item.indice, imagem_sha256: resumo,
      ...(pdf ? { arquivo: item.nome, pagina: item.pagina } : {}) };
    lote.pronta();
    $("batch-current").textContent = `Imagem ${item.indice + 1}/${lote.imagens.length}: ${item.nome}${item.pagina ? `, página ${item.pagina}` : ""}. Confira aluno e avaliação; reconheça e revise antes de salvar.`;
    message("Imagem do lote carregada. Nenhuma correção foi salva.");
  } catch (error) {
    if (!sessionCurrent(generation)) return;
    if (lote && lote.atual !== null) lote.falha(error.message);
    origemLote = null;
    message(error.message, true);
  } finally {
    if (sessionCurrent(generation)) {
      setBusy(false);
      renderLote();
    }
  }
}

if (recovery.enabled) {
  $("batch-panel").hidden = false;
  $("batch-file").addEventListener("change", async event => {
    const arquivo = event.target.files[0];
    if (!arquivo || busy) return;
    try {
      if (lote && !lote.cancelado) throw new Error("Conclua ou cancele o lote atual primeiro.");
      if (!/\.zip$/i.test(arquivo.name) || !arquivo.size || arquivo.size > 32 * 1024 * 1024)
        throw new Error("Selecione um ZIP não vazio de até 32 MiB.");
      setBusy(true, "Importando ZIP…");
      lote = new Lote(await upload("/api/lotes/zip", arquivo));
      origemLote = null;
      $("batch-current").textContent = "ZIP validado. Carregue a primeira imagem.";
      message("Lote importado; nenhuma correção foi salva.");
    } catch (error) { message(error.message, true); }
    finally { event.target.value = ""; setBusy(false); renderLote(); }
  });
  $("batch-next").addEventListener("click", carregarImagemLote);
  $("batch-pause").addEventListener("click", () => {
    if (!lote || busy) return;
    lote.pausado = !lote.pausado;
    $("batch-pause").textContent = lote.pausado ? "Continuar" : "Pausar";
    renderLote();
  });
  $("batch-cancel").addEventListener("click", async () => {
    if ((!lote && !loteRestauracaoPendente) || busy) return;
    try {
      if (recovery.list().length)
        throw new Error("Resolva a operação inconclusiva antes de cancelar o lote.");
      setBusy(true, "Cancelando lote…");
      await request(`/api/lotes/${lote?.id || loteRestauracaoPendente}`, { method: "DELETE" });
      lote?.cancelar();
      loteRestauracaoPendente = null;
      localStorage.removeItem(LOTE_KEY);
      origemLote = null;
      clearSource();
      invalidateResult();
      $("batch-current").textContent = "Lote cancelado. Correções já confirmadas permanecem no banco.";
      message("Lote cancelado.");
    } catch (error) { message(error.message, true); }
    finally { setBusy(false); renderLote(); }
  });
}

function downloadText(content, filename, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

if (recovery.enabled) {
  $("export-panel").hidden = false;
  $("export-results").addEventListener("click", async () => {
    if (busy) return;
    const session = sessionGeneration;
    latestExport = null;
    $("export-summary-download").disabled = true;
    $("export-status").textContent = "Consultando todas as páginas. Aguarde antes de continuar as correções.";
    try {
      setBusy(true, "Exportando resultados…");
      const provaId = $("export-evaluation").value;
      const caminho = "/api/correcoes/exportar" + (provaId ? "?prova_id=" + encodeURIComponent(provaId) : "");
      const dados = await request(caminho);
      if (!sessionCurrent(session)) return;
      if (typeof dados.csv !== "string" || !Array.isArray(dados.resumo?.identificadores) ||
          dados.resumo.identificadores.length !== dados.resumo.total_correcoes)
        throw new Error("Exportação incompleta. Nenhum arquivo foi baixado.");
      let pendencias = null;
      try { pendencias = recovery.list().map(item => item.id); }
      catch { /* O resumo deve mostrar que a contagem local é desconhecida. */ }
      latestExport = { ...dados.resumo, operacoes_pendentes_no_navegador: pendencias };
      const nome = `correcoes-${provaId || "todas"}-${new Date().toISOString().slice(0, 10)}.csv`;
      downloadText(dados.csv, nome, "text/csv;charset=utf-8");
      $("export-summary-download").disabled = false;
      $("export-status").textContent = `${dados.resumo.total_correcoes} correções confirmadas; ` +
        `${dados.resumo.alunos_distintos} alunos distintos; ` +
        `${pendencias === null ? "pendências locais desconhecidas" : pendencias.length + " operações pendentes no navegador"}. ` +
        (dados.resumo.operacoes_sem_id ? `${dados.resumo.operacoes_sem_id} registros antigos sem ID de operação; ` : "") +
        "Baixe também o resumo para conferir os identificadores.";
    } catch (error) {
      if (sessionCurrent(session)) $("export-status").textContent =
        "Exportação não concluída: " + error.message;
    } finally { if (sessionCurrent(session)) setBusy(false); }
  });
  $("export-summary-download").addEventListener("click", () => {
    if (!latestExport) return;
    downloadText(JSON.stringify(latestExport, null, 2),
      `conferencia-${new Date().toISOString().slice(0, 10)}.json`, "application/json;charset=utf-8");
  });
}
function operationId(kind, payload) {
  const fingerprint = JSON.stringify(payload);
  const pending = pendingOperations.get(kind);
  if (pending?.fingerprint === fingerprint) return pending.id;
  if (kind === "correcao") {
    const previous = recovery.matching(payload);
    if (previous) return previous;
    if (recovery.list().length)
      throw new Error("Resolva a correção pendente antes de salvar outra. Consulte o estado da operação abaixo.");
  }
  const id = crypto.randomUUID();
  pendingOperations.set(kind, { fingerprint, id });
  return id;
}
function renderRecovery() {
  if (!recovery.enabled) return;
  const list = $("recovery-list");
  list.replaceChildren();
  let entries;
  try { entries = recovery.list(); }
  catch (error) {
    $("recovery-panel").hidden = false;
    list.textContent = error.message;
    return;
  }
  $("recovery-panel").hidden = !entries.length;
  for (const entry of entries) {
    const row = document.createElement("div");
    row.className = "evaluation-item";
    const status = document.createElement("span");
    status.textContent = `Operação ${entry.id.slice(0, 8)}: ${recoveryStates.get(entry.id) || "pendente de confirmação"}`;
    const check = document.createElement("button");
    check.className = "secondary";
    check.textContent = "Consultar estado";
    check.addEventListener("click", () => checkRecovery(entry.id));
    const retry = document.createElement("button");
    retry.className = "secondary";
    retry.textContent = "Reenviar mesma operação";
    retry.disabled = recoveryStates.get(entry.id) !== "não encontrada agora";
    retry.addEventListener("click", () => retryRecovery(entry.id));
    row.append(status, check, retry);
    list.append(row);
  }
}
async function checkRecovery(id) {
  try {
    const status = await request(`/api/operacoes/correcao/${encodeURIComponent(id)}`);
    if (status.estado === "confirmada") {
      let cleanupFailed = false;
      try { recovery.confirm(id); } catch { cleanupFailed = true; }
      recoveryStates.delete(id);
      if (loteOperacao === id) {
        lote?.confirmada(id);
        loteOperacao = null;
        origemLote = null;
        pendingOperations.delete("correcao");
        result = null;
        renderLote();
      }
      renderRecovery();
      message(`Correção confirmada no banco. Registro: ${status.registro.id}` +
        (cleanupFailed ? " A pendência local não pôde ser removida." : ""), cleanupFailed);
      return "confirmada";
    }
    if (status.estado !== "nao_encontrada") throw new Error("Resposta de consulta inválida.");
    recoveryStates.set(id, "não encontrada agora");
    renderRecovery();
    message("Operação não encontrada neste instante. Pode ainda estar em trânsito; reenviar o mesmo ID é seguro.", true);
    return "nao_encontrada";
  } catch (error) {
    recoveryStates.set(id, "situação desconhecida");
    renderRecovery();
    message("Não foi possível confirmar a operação. " + error.message, true);
    return "desconhecida";
  }
}
async function retryRecovery(id) {
  if (busy || await checkRecovery(id) !== "nao_encontrada") return;
  const payload = recovery.get(id);
  if (!payload) return;
  try {
    setBusy(true, "Reenviando a mesma operação…");
    const saved = await jsonPost("/api/correcoes/salvar", payload);
    let cleanupFailed = false;
    try { recovery.confirm(id); } catch { cleanupFailed = true; }
    recoveryStates.delete(id);
    if (loteOperacao === id) {
      lote?.confirmada(id);
      loteOperacao = null;
      origemLote = null;
      pendingOperations.delete("correcao");
      result = null;
      renderLote();
    }
    renderRecovery();
    message(`Correção confirmada no banco. Registro: ${saved.id}` +
      (cleanupFailed ? " A pendência local não pôde ser removida." : ""), cleanupFailed);
  } catch (error) {
    if (error.status === 422 || error.details?.codigo === "aluno_ambiguo") {
      let cleanupFailed = false;
      try { recovery.confirm(id); } catch { cleanupFailed = true; }
      recoveryStates.delete(id);
      if (loteOperacao === id && lote && lote.atual !== null) {
        lote.imagens[lote.atual].estado = "pendente";
        lote.atual = null;
        loteOperacao = null;
        origemLote = null;
        renderLote();
      }
      renderRecovery();
      message("Correção não gravada: " + (error.details?.mensagem || error.message) +
        (cleanupFailed ? " A pendência local não pôde ser removida." : ""), true);
    } else {
      recoveryStates.set(id, "situação desconhecida");
      renderRecovery();
      message("Reenvio inconclusivo. Consulte novamente. " + error.message, true);
    }
  } finally { setBusy(false); }
}
let students,
  visual,
  visualOfficial = null;

function showResult(data) {
  result = data;
  renderResult(data);
}

function message(text, error = false) {
  $("message").textContent = text;
  $("message").hidden = !text;
  $("message").classList.toggle("error", error);
}
function invalidateResult() {
  result = null;
  resultContext = null;
  $("result-content").hidden = true;
  $("result-empty").hidden = false;
  $("confirm-result").checked = false;
  $("allow-provisional").checked = false;
  $("result-state").textContent = "Aguardando leitura";
  $("saved-result").hidden = true;
  $("visual-panel").hidden = true;
  visual?.clear();
  visualOfficial = null;
  updateButtons();
}
function invalidateOfficial() {
  $("confirm-official").checked = false;
  $("official-review").hidden = true;
  $("official-empty").hidden = false;
  $("answer-grid").replaceChildren();
  $("review-count").textContent = "Aguardando leitura";
  updateButtons();
}
function updateButtons() {
  document
    .querySelectorAll(
      '[data-question], [data-student-question], input[type="checkbox"]',
    )
    .forEach((input) => {
      input.disabled = busy;
    });
  $("process-button").disabled = busy || namePending || !source || !photoConfirmed;
  $("save-evaluation").disabled =
    busy ||
    !$("confirm-official").checked ||
    !$("evaluation-name").value.trim() ||
    !$("answer-grid").children.length;
  $("save-result").disabled =
    busy ||
    !result ||
    !$("confirm-result").checked ||
    (result.provisorio && !$("allow-provisional").checked) ||
    !$("student-name").value.trim();
  for (const element of [
    $("evaluation-select"),
    $("export-evaluation"),
    $("student-name"),
    $("evaluation-name"),
    $("file-input"),
    $("mobile-camera-input"),
    $("capture-button"),
    $("camera-select"),
    $("student-link-select"),
  ]) {
    element.disabled =
      busy || (element.id === "capture-button" &&
        (!camera.stream || !$("camera-video").videoWidth || !$("camera-video").videoHeight));
  }
  $("camera-start").disabled = busy || cameraStarting;
  $("export-results").disabled = busy;
  $("student-link-select").disabled = busy || $("student-new-homonym").checked;
  $("camera-stop").disabled = busy || (!camera.stream && !previewUrl && !cameraStarting);
  $("batch-file").disabled = busy || restaurandoLote || Boolean(loteRestauracaoPendente) ||
    Boolean(lote && !lote.cancelado);
  $("batch-next").disabled = busy || !lote || lote.pausado || lote.cancelado ||
    lote.atual !== null || !lote.imagens.some(item => item.estado === "pendente");
  $("batch-pause").disabled = busy || !lote || lote.cancelado;
  $("batch-cancel").disabled = busy || (!loteRestauracaoPendente && (!lote || lote.cancelado));
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.disabled = busy;
  });
}
function setBusy(value, label = "") {
  busy = value;
  $("process-button").textContent = value
    ? label || "Processando…"
    : tab === "avaliacoes"
      ? "Reconhecer as 50 respostas →"
      : "Reconhecer e corrigir →";
  updateButtons();
}

function showOverlay(visible) {
  // SVGElement não reflete a propriedade .hidden como um elemento HTML.
  $("camera-overlay").toggleAttribute("hidden", !visible);
}

function positionGuide() {
  const video = $("camera-video");
  const stage = $("camera-stage");
  const width = video.videoWidth || stage.clientWidth;
  const height = video.videoHeight || stage.clientHeight;
  if (!width || !height) return;
  // Margem em ambos os eixos, inclusive em câmeras em retrato.
  const guideHeight = Math.min(880, (((800 * 297) / 210) * width) / height);
  const guideWidth = (((guideHeight * 210) / 297) * height) / width;
  const x = (1000 - guideWidth) / 2,
    y = (1000 - guideHeight) / 2;
  const guide = $("camera-overlay").querySelector(".guide");
  for (const [name, value] of Object.entries({
    x,
    y,
    width: guideWidth,
    height: guideHeight,
  })) {
    guide.setAttribute(name, value);
  }
  const right = x + guideWidth,
    bottom = y + guideHeight;
  const dx = guideWidth * 0.1,
    dy = guideHeight * 0.07;
  $("camera-overlay")
    .querySelector(".guide-corners")
    .setAttribute(
      "d",
      `M${x},${y + dy}V${y}H${x + dx} M${right - dx},${y}H${right}V${y + dy} ` +
        `M${right},${bottom - dy}V${bottom}H${right - dx} M${x + dx},${bottom}H${x}V${bottom - dy}`,
    );
}

function showCameraState(data) {
  state = data.estado;
  if (data.mensagem?.startsWith("Câmera desconectada")) message(data.mensagem, true);
  $("camera-stage").dataset.state = state;
  $("frame-status").className = `frame-status ${state}`;
  $("frame-status").textContent = data.mensagem;
  // SVG segue exatamente a área de vídeo, sem deslocamento causado por letterbox.
  const points = data.cantos || [];
  $("detected-corners").setAttribute(
    "points",
    points.map(([x, y]) => `${x * 1000},${y * 1000}`).join(" "),
  );
  if (!camera?.stream) {
    $("capture-button").disabled = true;
    $("camera-stop").disabled = !previewUrl && !cameraStarting;
    $("camera-stop").textContent = cameraStarting ? "Cancelar ativação" : previewUrl ? "Nova captura" : "Desligar";
    $("camera-video").hidden = true;
    showOverlay(false);
    $("camera-empty").hidden = Boolean(previewUrl);
    $("capture-preview").hidden = !previewUrl;
    $("frame-status").hidden = true;
  } else {
    // A moldura fixa independe dos cantos retornados pela detecção.
    showOverlay(true);
  }
}
const camera = new Camera({
  video: $("camera-video"),
  onState: showCameraState,
  analyze: (blob, signal) => upload("/api/capturas/analisar", blob, {}, signal),
});
const nameReader = new StudentNameReader({
  field: $("student-name"),
  status: $("student-name-status"),
  recognize: (file, fields, signal) =>
    upload("/api/alunos/reconhecer-nome", file, fields, signal),
  onChange: () => {
    invalidateResult();
    students?.resetSelection();
    students?.refreshMatches();
  },
  onPending: (value) => {
    namePending = value;
    updateButtons();
  },
});
students = new Students({
  onSelect: () => {
    $("confirm-result").checked = false;
    $("allow-provisional").checked = false;
    updateButtons();
  },
  onMessage: message,
});
visual = new VisualCorrection({
  canvas: $("annotated-card"),
  grid: $("student-answer-grid"),
  status: $("visual-status"),
  onReview: async (respostas) => {
    const session = sessionGeneration;
    const process = processGeneration;
    const visualGeneration = visual.generation;
    const review = ++reviewRequest;
    const current = () => sessionCurrent(session) && process === processGeneration &&
      visualGeneration === visual.generation && review === reviewRequest;
    const previous = result;
    result = null;
    $("confirm-result").checked = false;
    $("allow-provisional").checked = false;
    setBusy(true, "Recalculando conferência…");
    try {
      const reviewed = await jsonPost("/api/correcoes/recalcular", {
        respostas,
        gabarito: visualOfficial,
      });
      if (!current()) return null;
      showResult(reviewed.resultado);
      message(
        "Resposta revisada. Nota e marcações atualizadas. Confira e confirme novamente.",
      );
      return reviewed;
    } catch (error) {
      if (current()) {
        result = previous;
        message(error.message, true);
      }
      throw error;
    } finally {
      if (current()) setBusy(false);
    }
  },
});

function stopCamera() {
  cameraRequest += 1;
  cameraStarting = false;
  videoReadyCleanup?.();
  videoReadyCleanup = null;
  camera.stop();
  $("camera-video").hidden = true;
  showOverlay(false);
  $("camera-empty").hidden = Boolean(previewUrl);
  $("frame-status").hidden = true;
  $("capture-preview").hidden = !previewUrl;
  updateButtons();
}

function clearSource() {
  nameReader.clear();
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  source = null;
  sourceIsCapture = false;
  photoConfirmed = true;
  $("photo-review").hidden = true;
  $("capture-preview").removeAttribute("src");
  $("capture-preview").hidden = true;
  $("camera-empty").hidden = false;
  $("file-input").value = "";
  $("mobile-camera-input").value = "";
  $("file-name").textContent = "PDF, JPG ou PNG · até 10 MiB";
  $("source-badge").textContent = "Nenhum cartão";
}

function setSource(file, fromCamera = false, fromBatch = false) {
  if (lote && lote.atual !== null && !fromBatch)
    throw new Error("Conclua, repita ou cancele a imagem atual do lote antes de trocar a origem.");
  validateFile(file);
  clearSource();
  source = file;
  sourceIsCapture = fromCamera;
  photoConfirmed = !fromCamera;
  $("photo-review").hidden = !fromCamera;
  stopCamera();
  invalidateResult();
  invalidateOfficial();
  $("file-name").textContent = file.name;
  $("source-badge").textContent = fromCamera
    ? "Foto para conferir"
    : "Arquivo selecionado";
  if (file.type.startsWith("image/") || /\.(png|jpe?g)$/i.test(file.name)) {
    previewUrl = URL.createObjectURL(file);
    $("capture-preview").src = previewUrl;
    $("capture-preview").hidden = false;
    $("camera-empty").hidden = true;
  }
  $("camera-start").textContent = "Ativar câmera";
  // Nova captura permanece disponível mesmo com a prévia ocupando o palco.
  $("camera-stop").textContent = "Nova captura";
  $("camera-stop").disabled = false;
  updateButtons();
  if (tab === "correcao" && photoConfirmed)
    nameReader.read(file, { captura: fromCamera });
}

$("confirm-photo").addEventListener("click", () => {
  if (!source || !sourceIsCapture || busy) return;
  photoConfirmed = true;
  $("photo-review").hidden = true;
  $("source-badge").textContent = "Foto confirmada";
  updateButtons();
  if (tab === "correcao") nameReader.read(source, { captura: true });
  message("Foto confirmada. Reconheça e revise as 50 respostas antes de salvar.");
});
$("discard-photo").addEventListener("click", () => {
  if (busy) return;
  stopCamera();
  clearSource();
  invalidateResult();
  invalidateOfficial();
  updateButtons();
  message("Foto descartada. Capture novamente ou selecione um arquivo.");
});

async function startCamera() {
  if (busy || cameraStarting) return;
  if (lote && lote.atual !== null) {
    message("Conclua ou cancele a imagem atual do lote antes de usar a câmera.", true);
    return;
  }
  if (sourceIsCapture) {
    clearSource();
    updateButtons();
  }
  const requestId = ++cameraRequest;
  cameraStarting = true;
  videoReadyCleanup?.();
  videoReadyCleanup = null;
  message("");
  $("camera-start").disabled = true;
  try {
    const activation = camera.start($("camera-select").value);
    $("camera-empty").hidden = true;
    $("capture-preview").hidden = true;
    $("camera-video").hidden = false;
    positionGuide();
    showOverlay(true);
    $("frame-status").hidden = false;
    $("frame-status").textContent =
      "Inicializando câmera. Coloque a folha inteira dentro da moldura.";
    $("camera-stop").textContent = "Cancelar ativação";
    updateButtons();
    const active = await activation;
    if (!active || requestId !== cameraRequest) return;
    cameraStarting = false;
    $("camera-empty").hidden = true;
    $("capture-preview").hidden = true;
    $("camera-video").hidden = false;
    showOverlay(true);
    $("frame-status").hidden = false;
    const video = $("camera-video");
    const ready = () => {
      if (requestId !== cameraRequest || !camera.stream ||
          !video.videoWidth || !video.videoHeight) return;
      videoReadyCleanup?.();
      videoReadyCleanup = null;
      $("camera-stage").style.aspectRatio = `${video.videoWidth} / ${video.videoHeight}`;
      positionGuide();
      updateButtons();
    };
    video.addEventListener("loadedmetadata", ready);
    video.addEventListener("resize", ready);
    videoReadyCleanup = () => {
      video.removeEventListener("loadedmetadata", ready);
      video.removeEventListener("resize", ready);
    };
    ready();
    $("camera-stop").disabled = false;
    $("camera-stop").textContent = "Desligar";
    const selected = camera.stream
      .getVideoTracks()[0]
      ?.getSettings?.().deviceId;
    try {
      const devices = await camera.devices();
      if (requestId !== cameraRequest) return;
      $("camera-select").replaceChildren(
        ...devices.map(
          (device, index) =>
            new Option(device.label || `Câmera ${index + 1}`, device.deviceId),
        ),
      );
      if (selected) $("camera-select").value = selected;
    } catch {
      if (requestId === cameraRequest)
        message("Câmera ativa; a lista de dispositivos não está disponível.");
    }
  } catch (error) {
    if (requestId === cameraRequest) {
      stopCamera();
      message(cameraError(error), true);
    }
  } finally {
    if (requestId === cameraRequest) {
      cameraStarting = false;
      updateButtons();
    }
  }
}
$("camera-start").addEventListener("click", startCamera);
$("camera-stop").addEventListener("click", () =>
  camera.stream || cameraStarting ? stopCamera() : startCamera(),
);
$("camera-select").addEventListener("change", () => {
  if (camera.stream) startCamera();
});
$("capture-button").addEventListener("click", async () => {
  if (busy) return;
  const generation = camera.generation;
  const validated = state === "verde";
  try {
    const blob = await camera.capture();
    if (generation !== camera.generation) return;
    setSource(new File([blob], "captura.png", { type: "image/png" }), true);
    message(
      validated
        ? "Captura feita. Confira nitidez antes de reconhecer."
        : "Captura manual: o enquadramento não foi validado. Confira os quatro cantos e revise a leitura com atenção.",
    );
  } catch (error) {
    if (generation === camera.generation) message(error.message, true);
  }
});
$("file-input").addEventListener("change", (event) => {
  if (!event.target.files[0]) return;
  try {
    setSource(event.target.files[0]);
    message("Arquivo selecionado. Nada foi salvo.");
  } catch (error) {
    event.target.value = "";
    message(error.message, true);
  }
});
$("mobile-camera-input").addEventListener("change", (event) => {
  if (!event.target.files[0]) return;
  try {
    setSource(event.target.files[0], true);
    message("Foto recebida. Confira nitidez e enquadramento antes de confirmar.");
  } catch (error) {
    event.target.value = "";
    message(error.message, true);
  }
});

function switchTab(next) {
  if (busy) {
    history.replaceState(null, "", `#${tab}`);
    return;
  }
  if (tab === "correcao" && next !== "correcao" && lote && lote.atual !== null) {
    history.replaceState(null, "", `#${tab}`);
    message("Conclua ou cancele a imagem atual do lote antes de sair da Correção.", true);
    return;
  }
  stopCamera();
  clearSource();
  processGeneration += 1;
  invalidateResult();
  invalidateOfficial();
  tab = next;
  history.replaceState(null, "", `#${tab}`);
  const isEvaluation = tab === "avaliacoes";
  const isCorrection = tab === "correcao";
  $("evaluation-fields").hidden = !isEvaluation;
  $("correction-fields").hidden = !isCorrection;
  $("student-link-panel").hidden = !isCorrection;
  $("capture-workspace").hidden = tab === "alunos";
  $("students-panel").hidden = tab !== "alunos";
  $("official-panel").hidden = !isEvaluation;
  $("result-panel").hidden = !isCorrection;
  $("evaluation-list-panel").hidden = !isEvaluation;
  $("page-title").textContent = {
    avaliacoes: "Avaliações",
    correcao: "Correção",
    alunos: "Alunos",
  }[tab];
  $("page-description").textContent = isEvaluation
    ? "Cadastre uma avaliação e confira o gabarito antes de começar."
    : isCorrection
      ? "Capture o cartão do aluno, confira o resultado e salve quando estiver pronto."
      : "Pesquise alunos e consulte as avaliações e correções salvas.";
  $("breadcrumb").textContent = $("page-title").textContent;
  if (tab === "alunos") students.load();
  if (isCorrection) students.refreshMatches();
  document.title = `Corretor de Gabaritos · ${$("breadcrumb").textContent}`;
  document.querySelectorAll("[data-tab]").forEach((button) => {
    button.classList.toggle("active", button.dataset.tab === tab);
    if (button.dataset.tab === tab) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  message("");
  setBusy(false);
}
document
  .querySelectorAll("[data-tab]")
  .forEach((button) =>
    button.addEventListener("click", () => switchTab(button.dataset.tab)),
  );

async function loadEvaluations() {
  const session = sessionGeneration;
  $("refresh-evaluations").disabled = true;
  try {
    const loaded = await request("/api/avaliacoes");
    if (!sessionCurrent(session)) return;
    evaluations = loaded;
    const selected = $("evaluation-select").value;
    $("evaluation-select").replaceChildren(
      new Option("Selecione uma avaliação", ""),
      ...evaluations.map((prova) => new Option(prova.titulo, prova.id)),
    );
    const exportSelected = $("export-evaluation").value;
    $("export-evaluation").replaceChildren(
      new Option("Todas as avaliações", ""),
      ...evaluations.map((prova) => new Option(prova.titulo, prova.id)),
    );
    if (evaluations.some((prova) => prova.id === exportSelected))
      $("export-evaluation").value = exportSelected;
    if (evaluations.some((prova) => prova.id === selected))
      $("evaluation-select").value = selected;
    else if (selected) invalidateResult();
    $("evaluation-list").replaceChildren();
    if (!evaluations.length) {
      const empty = document.createElement("p");
      empty.className = "helper";
      empty.textContent =
        "Nenhuma avaliação cadastrada. Crie a primeira acima.";
      $("evaluation-list").append(empty);
    }
    for (const prova of evaluations) {
      const item = document.createElement("article");
      item.className = "evaluation-item";
      const text = document.createElement("div");
      const title = document.createElement("h3");
      title.textContent = prova.titulo;
      const detail = document.createElement("small");
      detail.textContent = `Criada em ${new Date(prova.criada_em).toLocaleDateString("pt-BR")} · 50 questões`;
      const button = document.createElement("button");
      button.textContent = "Corrigir cartões →";
      button.addEventListener("click", () => {
        if (busy) return;
        switchTab("correcao");
        $("evaluation-select").value = prova.id;
      });
      text.append(title, detail);
      item.append(text, button);
      $("evaluation-list").append(item);
    }
  } catch (error) {
    if (sessionCurrent(session)) {
      $("evaluation-list").textContent = error.message;
      message(error.message, true);
    }
  } finally {
    if (sessionCurrent(session)) $("refresh-evaluations").disabled = false;
  }
}
$("refresh-evaluations").addEventListener("click", loadEvaluations);

$("process-button").addEventListener("click", async () => {
  if (!source || busy || !photoConfirmed) return;
  if (lote && lote.atual !== null && lote.imagens[lote.atual].estado === "revisao") {
    lote.imagens[lote.atual].estado = "pronta";
    renderLote();
  }
  const session = sessionGeneration;
  const generation = ++processGeneration;
  const context = {
    prova_id: $("evaluation-select").value,
    aluno: $("student-name").value.trim(),
  };
  if (tab === "correcao" && (!context.prova_id || !context.aluno)) {
    message(
      "Selecione a avaliação e informe ou confira o nome do aluno.",
      true,
    );
    return;
  }
  stopCamera();
  invalidateResult();
  invalidateOfficial();
  setBusy(true, "Lendo o cartão…");
  message("");
  try {
    if (tab === "avaliacoes") {
      const recognized = await upload("/api/gabaritos/reconhecer", source, {
        captura: sourceIsCapture,
      });
      if (generation === processGeneration && sessionCurrent(session)) {
        renderOfficial(recognized, updateButtons);
        message(
          "Leitura concluída. Confira as 50 alternativas antes de confirmar o gabarito.",
        );
      }
    } else {
      const official = await request(
        `/api/avaliacoes/${encodeURIComponent(context.prova_id)}/gabarito`,
      );
      if (!sessionCurrent(session)) return;
      const data = await upload("/api/correcoes/processar", source, {
        gabarito: JSON.stringify(official.alternativas),
        captura: sourceIsCapture,
        visual: true,
      });
      if (generation === processGeneration && sessionCurrent(session)) {
        showResult(data.resultado);
        resultContext = context;
        visualOfficial = official.alternativas;
        $("visual-panel").hidden = false;
        await visual.load(data);
        if (generation === processGeneration && lote && lote.atual !== null) {
          lote.processada();
          renderLote();
        }
        if (generation === processGeneration && sessionCurrent(session))
          message("Correção concluída. O resultado ainda não foi salvo.");
      }
    }
  } catch (error) {
    if (generation === processGeneration && lote && lote.atual !== null) {
      lote.falha(error.message);
      origemLote = null;
      clearSource();
      invalidateResult();
      renderLote();
    }
    if (generation === processGeneration && sessionCurrent(session)) message(error.message, true);
  } finally {
    if (generation === processGeneration && sessionCurrent(session)) setBusy(false);
  }
});

$("save-evaluation").addEventListener("click", async () => {
  if (busy) return;
  const session = sessionGeneration;
  try {
    const selects = [...document.querySelectorAll("[data-question]")].sort(
      (a, b) => Number(a.dataset.question) - Number(b.dataset.question),
    );
    const alternativas = officialFromSelections(
      selects.map((select) => select.value),
    );
    if (!$("confirm-official").checked)
      throw new Error("Confirme o gabarito oficial antes de salvar.");
    setBusy(true, "Salvando avaliação…");
    const payload = {
      titulo: $("evaluation-name").value.trim(),
      alternativas,
      confirmado: true,
    };
    await jsonPost("/api/avaliacoes", { ...payload, operacao_id: operationId("avaliacao", payload) });
    if (!sessionCurrent(session)) return;
    pendingOperations.delete("avaliacao");
    invalidateOfficial();
    clearSource();
    $("evaluation-name").value = "";
    await loadEvaluations();
    if (!sessionCurrent(session)) return;
    message(
      "Avaliação e gabarito oficial salvos. Você já pode corrigir os cartões.",
    );
  } catch (error) {
    if (sessionCurrent(session)) message(error.message, true);
  } finally {
    if (sessionCurrent(session)) setBusy(false);
  }
});

$("save-result").addEventListener("click", async () => {
  if (busy || !result || !resultContext || !$("confirm-result").checked) return;
  const session = sessionGeneration;
  let savingId = null, sent = false;
  try {
    setBusy(true, "Salvando correção…");
    const payload = {
      ...resultContext,
      ...students.saveOptions(),
      resultado: result,
      respostas: visual.responses,
      comprovante: visual.comprovante,
      confirmado: true,
      permitir_provisorio: $("allow-provisional").checked,
      ...(origemLote ? { origem_lote: origemLote } : {}),
    };
    const operacao_id = operationId("correcao", payload);
    savingId = operacao_id;
    if (origemLote) loteOperacao = operacao_id;
    const requisicao = { ...payload, operacao_id };
    recovery.preserve(requisicao);
    renderRecovery();
    renderLote();
    sent = true;
    const saved = await jsonPost("/api/correcoes/salvar", requisicao);
    if (!sessionCurrent(session)) return;
    pendingOperations.delete("correcao");
    if (loteOperacao === operacao_id) {
      lote?.confirmada(operacao_id);
      loteOperacao = null;
      origemLote = null;
      renderLote();
    }
    let cleanupFailed = false;
    try { recovery.confirm(operacao_id); }
    catch { cleanupFailed = true; }
    renderRecovery();
    $("saved-result").textContent =
      `Correção salva para ${saved.aluno}. Registro: ${saved.id}`;
    $("saved-result").hidden = false;
    message(cleanupFailed
      ? "Correção salva no banco; a pendência local não pôde ser removida. Consulte-a depois."
      : "Correção salva com sucesso.", cleanupFailed);
    // Mantém a exibição, mas impede repetir o salvamento acidentalmente.
    result = null;
    students.saved(saved);
  } catch (error) {
    if (!sessionCurrent(session)) return;
    if (error.details?.codigo === "aluno_ambiguo") {
      if (savingId) { try { recovery.confirm(savingId); } catch { /* manter pendência */ } }
      pendingOperations.delete("correcao");
      renderRecovery();
      students.showAmbiguity(error.details.alunos);
      message("Correção não gravada: confirme o aluno e tente novamente.", true);
    } else if (sent && (!error.status || error.status >= 500)) {
      recoveryStates.set(savingId, "situação desconhecida");
      renderRecovery();
      message("Situação desconhecida: consulte a operação pendente antes de continuar. " + error.message, true);
    } else if (!sent || error.status === 422) {
      if (sent && savingId && error.status === 422) {
        try { recovery.confirm(savingId); } catch { /* manter pendência */ }
      }
      renderRecovery();
      message("Correção não gravada: " + error.message, true);
    } else message(error.message, true);
  } finally {
    if (sessionCurrent(session)) setBusy(false);
  }
});
for (const id of [
  "confirm-official",
  "confirm-result",
  "allow-provisional",
  "evaluation-name",
])
  $("" + id).addEventListener("input", updateButtons);
for (const id of ["evaluation-select", "student-name"])
  $(id).addEventListener("input", () => {
    if (!busy) invalidateResult();
  });
document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    const ativa = Boolean(camera.stream || cameraStarting);
    stopCamera();
    if (ativa) message("Câmera pausada ao sair da aba. Reative-a para continuar ou envie um arquivo.");
  }
});
window.addEventListener("corretor:session-ended", () => {
  sessionGeneration++;
  lote = null;
  origemLote = null;
  loteOperacao = null;
  try { localStorage.removeItem(LOTE_KEY); } catch { /* sem armazenamento */ }
  stopCamera();
  clearSource();
  processGeneration++;
  setBusy(false);
  $("refresh-evaluations").disabled = false;
  evaluations = [];
  latestExport = null;
  $("export-summary-download").disabled = true;
  $("export-status").textContent = "";
  pendingOperations.clear();
  students?.clear();
  invalidateResult();
  invalidateOfficial();
  $("evaluation-list").replaceChildren();
  $("evaluation-select").replaceChildren();
  $("evaluation-name").value = "";
  $("student-name").value = "";
  $("total-score").textContent = "";
  $("total-percent").textContent = "";
  $("result-counts").replaceChildren();
  $("discipline-results").replaceChildren();
  $("pending-list").textContent = "";
  $("visual-status").textContent = "";
  $("saved-result").textContent = "";
  message("");
  renderLote();
});
window.addEventListener("corretor:session-paused", () => {
  sessionGeneration++;
  stopCamera();
  processGeneration++;
  setBusy(false);
  $("refresh-evaluations").disabled = false;
});
window.addEventListener("pagehide", () => {
  sessionGeneration++;
  processGeneration++;
  stopCamera();
  clearSource();
  invalidateResult();
  setBusy(false);
});
window.addEventListener("hashchange", () => switchTab(tabFromHash(location.hash)));
switchTab(tabFromHash(location.hash));
loadEvaluations();
renderRecovery();
renderLote();
updateButtons();
void restaurarLote();
