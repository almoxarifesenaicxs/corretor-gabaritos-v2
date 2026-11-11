import { renderOfficial, renderResult } from "./revisao.mjs";
import { tabFromHash } from "./paginas.mjs";

import {
  request,
  upload,
  jsonPost,
  validateFile,
  officialFromSelections,
} from "./api.mjs";
import { Camera, cameraError } from "./camera.mjs";
import { StudentNameReader } from "./nome-aluno.mjs";
import { Students } from "./alunos.mjs";
import { VisualCorrection } from "./correcao-visual.mjs";

const $ = (id) => document.getElementById(id);
let tab = "avaliacoes",
  source = null,
  sourceIsCapture = false,
  previewUrl = null;
let result = null,
  resultContext = null,
  evaluations = [],
  busy = false,
  state = "vermelho",
  cameraRequest = 0;
let processGeneration = 0;
let namePending = false;
const pendingOperations = new Map();
function operationId(kind, payload) {
  const fingerprint = JSON.stringify(payload);
  const pending = pendingOperations.get(kind);
  if (pending?.fingerprint === fingerprint) return pending.id;
  const id = crypto.randomUUID();
  pendingOperations.set(kind, { fingerprint, id });
  return id;
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
  $("process-button").disabled = busy || namePending || !source;
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
    $("student-name"),
    $("evaluation-name"),
    $("file-input"),
    $("capture-button"),
    $("camera-select"),
    $("student-link-select"),
  ]) {
    element.disabled =
      busy || (element.id === "capture-button" && !camera.stream);
  }
  $("camera-start").disabled = busy;
  $("student-link-select").disabled = busy || $("student-new-homonym").checked;
  $("camera-stop").disabled = busy || (!camera.stream && !previewUrl);
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
    $("camera-stop").disabled = !previewUrl;
    $("camera-stop").textContent = previewUrl ? "Nova captura" : "Desligar";
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
      showResult(reviewed.resultado);
      message(
        "Resposta revisada. Nota e marcações atualizadas. Confira e confirme novamente.",
      );
      return reviewed;
    } catch (error) {
      result = previous;
      message(error.message, true);
      throw error;
    } finally {
      setBusy(false);
    }
  },
});

function stopCamera() {
  cameraRequest += 1;
  camera.stop();
  $("camera-video").hidden = true;
  showOverlay(false);
  $("camera-empty").hidden = Boolean(previewUrl);
  $("frame-status").hidden = true;
  $("capture-preview").hidden = !previewUrl;
}

function clearSource() {
  nameReader.clear();
  if (previewUrl) URL.revokeObjectURL(previewUrl);
  previewUrl = null;
  source = null;
  sourceIsCapture = false;
  $("capture-preview").removeAttribute("src");
  $("capture-preview").hidden = true;
  $("camera-empty").hidden = false;
  $("file-input").value = "";
  $("file-name").textContent = "PDF, JPG ou PNG · até 10 MiB";
  $("source-badge").textContent = "Nenhum cartão";
}

function setSource(file, fromCamera = false) {
  validateFile(file);
  clearSource();
  source = file;
  sourceIsCapture = fromCamera;
  stopCamera();
  invalidateResult();
  invalidateOfficial();
  $("file-name").textContent = file.name;
  $("source-badge").textContent = fromCamera
    ? "Captura da webcam"
    : "Arquivo selecionado";
  if (file.type.startsWith("image/") || /\.(png|jpe?g)$/i.test(file.name)) {
    previewUrl = URL.createObjectURL(file);
    $("capture-preview").src = previewUrl;
    $("capture-preview").hidden = false;
    $("camera-empty").hidden = true;
  }
  $("camera-start").textContent = "Ativar webcam";
  // Nova captura permanece disponível mesmo com a prévia ocupando o palco.
  $("camera-stop").textContent = "Nova captura";
  $("camera-stop").disabled = false;
  updateButtons();
  if (tab === "correcao") nameReader.read(file, { captura: fromCamera });
}

async function startCamera() {
  if (busy) return;
  const requestId = ++cameraRequest;
  message("");
  $("camera-start").disabled = true;
  try {
    const activation = camera.start($("camera-select").value);
    positionGuide();
    showOverlay(true);
    $("frame-status").hidden = false;
    $("frame-status").textContent =
      "Inicializando câmera. Coloque a folha inteira dentro da moldura.";
    const active = await activation;
    if (!active || requestId !== cameraRequest) return;
    $("camera-empty").hidden = true;
    $("capture-preview").hidden = true;
    $("camera-video").hidden = false;
    showOverlay(true);
    $("frame-status").hidden = false;
    const ratio = `${$("camera-video").videoWidth} / ${$("camera-video").videoHeight}`;
    $("camera-stage").style.aspectRatio = ratio;
    positionGuide();
    $("capture-button").disabled = false;
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
      message("Câmera ativa; a lista de dispositivos não está disponível.");
    }
  } catch (error) {
    if (requestId === cameraRequest) {
      stopCamera();
      message(cameraError(error), true);
    }
  } finally {
    $("camera-start").disabled = false;
  }
}
$("camera-start").addEventListener("click", startCamera);
$("camera-stop").addEventListener("click", () =>
  camera.stream ? stopCamera() : startCamera(),
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
    message(error.message, true);
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

function switchTab(next) {
  if (busy) {
    history.replaceState(null, "", `#${tab}`);
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
  $("refresh-evaluations").disabled = true;
  try {
    evaluations = await request("/api/avaliacoes");
    const selected = $("evaluation-select").value;
    $("evaluation-select").replaceChildren(
      new Option("Selecione uma avaliação", ""),
      ...evaluations.map((prova) => new Option(prova.titulo, prova.id)),
    );
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
    $("evaluation-list").textContent = error.message;
    message(error.message, true);
  } finally {
    $("refresh-evaluations").disabled = false;
  }
}
$("refresh-evaluations").addEventListener("click", loadEvaluations);

$("process-button").addEventListener("click", async () => {
  if (!source || busy) return;
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
      if (generation === processGeneration) {
        renderOfficial(recognized, updateButtons);
        message(
          "Leitura concluída. Confira as 50 alternativas antes de confirmar o gabarito.",
        );
      }
    } else {
      const official = await request(
        `/api/avaliacoes/${encodeURIComponent(context.prova_id)}/gabarito`,
      );
      const data = await upload("/api/correcoes/processar", source, {
        gabarito: JSON.stringify(official.alternativas),
        captura: sourceIsCapture,
        visual: true,
      });
      if (generation === processGeneration) {
        showResult(data.resultado);
        resultContext = context;
        visualOfficial = official.alternativas;
        $("visual-panel").hidden = false;
        await visual.load(data);
        message("Correção concluída. O resultado ainda não foi salvo.");
      }
    }
  } catch (error) {
    message(error.message, true);
  } finally {
    setBusy(false);
  }
});

$("save-evaluation").addEventListener("click", async () => {
  if (busy) return;
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
    pendingOperations.delete("avaliacao");
    invalidateOfficial();
    clearSource();
    $("evaluation-name").value = "";
    await loadEvaluations();
    message(
      "Avaliação e gabarito oficial salvos. Você já pode corrigir os cartões.",
    );
  } catch (error) {
    message(error.message, true);
  } finally {
    setBusy(false);
  }
});

$("save-result").addEventListener("click", async () => {
  if (busy || !result || !resultContext || !$("confirm-result").checked) return;
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
    };
    const saved = await jsonPost("/api/correcoes/salvar", {
      ...payload, operacao_id: operationId("correcao", payload),
    });
    pendingOperations.delete("correcao");
    $("saved-result").textContent =
      `Correção salva para ${saved.aluno}. Registro: ${saved.id}`;
    $("saved-result").hidden = false;
    message("Correção salva com sucesso.");
    // Mantém a exibição, mas impede repetir o salvamento acidentalmente.
    result = null;
    await students.load();
    await students.refreshMatches();
  } catch (error) {
    if (error.details?.codigo === "aluno_ambiguo")
      students.showAmbiguity(error.details.alunos);
    message(error.message, true);
  } finally {
    setBusy(false);
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
  if (document.hidden) stopCamera();
});
window.addEventListener("pagehide", () => {
  stopCamera();
  if (previewUrl) URL.revokeObjectURL(previewUrl);
});
window.addEventListener("hashchange", () => switchTab(tabFromHash(location.hash)));
switchTab(tabFromHash(location.hash));
loadEvaluations();
updateButtons();
