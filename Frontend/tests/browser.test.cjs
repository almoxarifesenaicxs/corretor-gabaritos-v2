/* QA opcional: Playwright instalado separadamente, Chrome local e backend ativo. */
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require("playwright");

const baseURL = process.env.QA_BASE_URL || "http://127.0.0.1:8766";
const artifacts = process.env.QA_ARTIFACT_DIR;

test("OCR da mesma captura sugere nome editável e só salva após confirmação", async () => {
  const browser = await chromium.launch({executablePath: process.env.QA_CHROME_PATH, headless: true});
  try {
    const page = await browser.newPage();
    const oficial = Object.fromEntries(Array.from({length: 50}, (_, i) => [String(i+1), 'A']));
    await page.route('**/api/avaliacoes', route => route.fulfill({json: [{id: 'ocr-teste', titulo: 'Teste OCR', criada_em: '2026-10-31T12:00:00Z'}]}));
    await page.route('**/api/avaliacoes/*/gabarito', route => route.fulfill({json: {alternativas: oficial}}));
    let saved = null;
    await page.route('**/api/correcoes/salvar', route => {
      saved = route.request().postDataJSON();
      return route.fulfill({status: 201, json: {id: 'correcao-ocr', aluno: saved.aluno}});
    });
    // Cartão de referência com nome IMPRESSO sintético inserido; não é manuscrito real.
    const image = fs.readFileSync(path.join(artifacts, 'nome-impresso.png')).toString('base64');
    await page.addInitScript(image => {
      navigator.mediaDevices.getUserMedia = async () => {
        const photo = new Image(); photo.src = 'data:image/png;base64,' + image;
        await photo.decode();
        const canvas = document.createElement('canvas');
        canvas.width = photo.width; canvas.height = photo.height;
        canvas.getContext('2d').drawImage(photo, 0, 0);
        return canvas.captureStream(2);
      };
    }, image);
    const files = {};
    page.on('request', request => {
      if (!['/api/alunos/reconhecer-nome', '/api/correcoes/processar'].some(url => request.url().endsWith(url))) return;
      const boundary = request.headers()['content-type'].split('boundary=')[1];
      const body = request.postDataBuffer();
      const start = body.indexOf(Buffer.from('\r\n\r\n')) + 4;
      const end = body.indexOf(Buffer.from('\r\n--' + boundary), start);
      files[new URL(request.url()).pathname] = body.subarray(start, end);
    });
    await page.goto(baseURL + '/interface/');
    await page.getByRole('button', {name: 'Correção', exact: true}).click();
    await page.locator('#evaluation-select').selectOption('ocr-teste');
    await page.locator('#camera-start').click();
    await page.waitForFunction(() => document.getElementById('camera-video').videoWidth > 0);
    await page.locator('#capture-button').click();
    await page.waitForFunction(() => document.getElementById('student-name').value === 'MARIA DA SILVA');
    assert.equal(saved, null);
    await page.locator('#student-name').fill('Maria da Silva');
    await page.locator('#process-button').click();
    await page.locator('#result-content').waitFor({state: 'visible'});
    assert.deepEqual(files['/api/alunos/reconhecer-nome'], files['/api/correcoes/processar']);
    assert.equal(await page.locator('#student-name').inputValue(), 'Maria da Silva');
    assert.equal(saved, null);
    assert.equal(await page.locator('#save-result').isDisabled(), true);
    await page.locator('#confirm-result').check();
    await page.locator('#save-result').click();
    await page.locator('#saved-result').waitFor({state: 'visible'});
    assert.equal(saved.aluno, 'Maria da Silva');
    assert.equal(saved.confirmado, true);
  } finally {await browser.close();}
});

test("moldura fixa visível na inicialização e quando nenhuma folha é detectada", async () => {
  const browser = await chromium.launch({
    executablePath: process.env.QA_CHROME_PATH,
    headless: true,
    args: ["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream"],
  });
  try {
    const page = await browser.newPage({viewport: {width: 1280, height: 960}});
    let analysis = {estado: "vermelho", mensagem: "Folha não detectada.", cantos: [], folha_visivel: false};
    await page.route("**/api/avaliacoes", route => route.fulfill({json: []}));
    await page.route("**/api/capturas/analisar", route => route.fulfill({json: analysis}));
    // Mantém a permissão pendente para verificar a moldura antes do primeiro frame.
    await page.addInitScript(() => {
      const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = async constraints => {
        await new Promise(resolve => { window.releaseCamera = resolve; });
        return original(constraints);
      };
    });
    await page.goto(baseURL + "/interface/");
    await page.locator("#camera-start").click();
    await page.waitForFunction(() => typeof window.releaseCamera === "function");
    assert.equal(await page.locator("#camera-overlay").isVisible(), true);
    assert.equal(await page.locator(".guide").isVisible(), true);
    await page.evaluate(() => window.releaseCamera());
    await page.getByText("Folha não detectada.", {exact: true}).waitFor();
    assert.equal(await page.locator("#camera-overlay").getAttribute("hidden"), null);
    assert.equal(await page.locator(".guide").isVisible(), true);
    assert.equal(await page.locator(".guide-corners").isVisible(), true);
    assert.equal(await page.locator("#detected-corners").getAttribute("points"), "");
    const geometry = await page.evaluate(() => {
      const overlay = document.getElementById("camera-overlay");
      const video = document.getElementById("camera-video");
      const area = overlay.getBoundingClientRect();
      const guide = document.querySelector(".guide").getBoundingClientRect();
      const status = document.getElementById("frame-status").getBoundingClientRect();
      return {inside: guide.x > area.x && guide.y > area.y && guide.right < area.right && guide.bottom < area.bottom,
        statusOutside: status.top >= area.bottom,
        centered: Math.abs(guide.x+guide.width/2-area.x-area.width/2) < 1 && Math.abs(guide.y+guide.height/2-area.y-area.height/2) < 1,
        ratio: guide.width/guide.height,
        above: Number(getComputedStyle(overlay).zIndex) > Number(getComputedStyle(video).zIndex),
        stroke: getComputedStyle(document.querySelector(".guide")).stroke};
    });
    assert.equal(geometry.inside, true);
    assert.equal(geometry.centered, true);
    assert.equal(geometry.above, true);
    assert.equal(geometry.statusOutside, true);
    assert.ok(Math.abs(geometry.ratio - 210/297) < 0.01);
    assert.equal(geometry.stroke, "rgb(255, 119, 129)");
    const fixed = await page.locator(".guide").getAttribute("x");
    if (artifacts) await page.screenshot({path: path.join(artifacts, "moldura-sem-folha.png"), fullPage: true});
    for (const [estado, cor] of [["amarelo", "rgb(246, 198, 91)"], ["verde", "rgb(95, 219, 171)"], ["vermelho", "rgb(255, 119, 129)"]]) {
      analysis = {estado, mensagem: estado, cantos: estado === "vermelho" ? [] : [[.1,.1],[.8,.1],[.8,.9],[.1,.9]], folha_visivel: estado !== "vermelho"};
      await page.waitForFunction(expected => getComputedStyle(document.querySelector(".guide")).stroke === expected, cor);
      assert.equal(await page.locator(".guide").isVisible(), true);
      assert.equal(await page.locator(".guide").getAttribute("x"), fixed);
    }
    await page.locator("#camera-stop").click();
    assert.equal(await page.locator("#camera-overlay").isHidden(), true);
  } finally { await browser.close(); }
});

test("fluxos de avaliações e correções com câmera simulada e backend real", async () => {
  assert.ok(
    artifacts,
    "Defina QA_ARTIFACT_DIR com cartao.png e multipla.png sintéticos.",
  );
  const browser = await chromium.launch({
    executablePath: process.env.QA_CHROME_PATH,
    headless: true,
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
    ],
  });
  try {
    const context = await browser.newContext({
      viewport: { width: 1440, height: 1100 },
    });
    const page = await context.newPage();
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const evaluations = [],
      saved = [];
    let candidateRequests = 0;
    // Somente persistência simulada. Reconhecimento, análise e correção usam HTTP real.
    await page.route("**/api/avaliacoes", async (route) => {
      if (route.request().method() === "GET")
        return route.fulfill({ json: evaluations });
      const input = route.request().postDataJSON();
      assert.equal(input.confirmado, true);
      candidateRequests++;
      evaluations.push({
        id: "avaliacao-teste",
        titulo: input.titulo,
        criada_em: "2026-10-31T12:00:00Z",
        alternativas: input.alternativas,
      });
      return route.fulfill({ status: 201, json: evaluations[0] });
    });
    await page.route("**/api/avaliacoes/*/gabarito", (route) =>
      route.fulfill({ json: { alternativas: evaluations[0].alternativas } }),
    );
    await page.route("**/api/correcoes/salvar", async (route) => {
      const input = route.request().postDataJSON();
      saved.push(input);
      return route.fulfill({
        status: 201,
        json: { id: `correcao-${saved.length}`, aluno: input.aluno },
      });
    });
    await page.goto(baseURL + "/interface/");
    await page
      .getByText("Nenhuma avaliação cadastrada.", { exact: false })
      .waitFor();
    await page.evaluate(() => document.fonts.ready);
    assert.equal(await page.evaluate(() => document.fonts.check('500 14px Manrope')), true);
    assert.equal(await page.locator("#sidebar-toggle").getAttribute("aria-expanded"), "true");
    await page.locator("#sidebar-toggle").click();
    assert.equal(await page.locator("#sidebar-toggle").getAttribute("aria-expanded"), "false");
    assert.equal(await page.locator(".sidebar").evaluate(element => element.getBoundingClientRect().width), 80);
    await page.getByRole("button", {name: "Correção", exact: true}).click();
    assert.equal(await page.locator("#page-title").textContent(), "Correção");
    await page.getByRole("button", {name: "Avaliações", exact: true}).click();
    assert.equal(await page.locator("#page-title").textContent(), "Avaliações");
    await page.locator("#sidebar-toggle").click();
    await page.locator("#camera-start").click();
    await page.waitForFunction(
      () => document.getElementById("camera-video").srcObject !== null,
    );
    await page.locator("#capture-button").waitFor({ state: "visible" });
    await page.waitForTimeout(1200);
    await page.locator("#capture-button").click();
    await page.locator("#capture-preview").waitFor({ state: "visible" });
    assert.equal(
      await page.locator("#camera-video").evaluate((video) => video.srcObject),
      null,
    );
    assert.match(await page.locator("#message").textContent(), /Captura/);
    await page
      .locator("#file-input")
      .setInputFiles(path.join(artifacts, "cartao.png"));
    await page
      .locator("#evaluation-name")
      .fill("Avaliação de teste do navegador");
    await page.locator("#process-button").click();
    await page.locator('[data-question="50"]').waitFor();
    assert.equal(await page.locator("[data-question]").count(), 50);
    assert.equal(candidateRequests, 0);
    assert.equal(await page.locator("#save-evaluation").isDisabled(), true);
    await page.locator('[data-question="1"]').selectOption("B");
    await page.locator('[data-question="1"]').selectOption("A");
    await page.locator("#confirm-official").check();
    await page.screenshot({
      path: path.join(artifacts, "avaliacoes.png"),
      fullPage: true,
    });
    await page.locator("#save-evaluation").click();
    await page
      .getByText("Avaliação e gabarito oficial salvos.", { exact: false })
      .waitFor();
    assert.equal(candidateRequests, 1);
    await page.locator(".evaluation-item button").click();
    assert.equal(
      await page.locator("#evaluation-select").inputValue(),
      "avaliacao-teste",
    );
    await page.locator("#student-name").fill("Aluno de teste");
    await page
      .locator("#file-input")
      .setInputFiles(path.join(artifacts, "cartao.png"));
    await page.locator("#process-button").click();
    await page.locator("#result-content").waitFor({ state: "visible" });
    assert.equal(await page.locator("#total-score").textContent(), "50");
    assert.equal(saved.length, 0);
    await page.locator("#confirm-result").check();
    // Mudar aluno invalida o resultado para impedir associação ao aluno errado.
    await page.locator("#student-name").fill("Outro aluno");
    assert.equal(await page.locator("#result-content").isHidden(), true);
    await page
      .locator("#file-input")
      .setInputFiles(path.join(artifacts, "multipla.png"));
    await page.locator("#process-button").click();
    await page.locator("#result-content").waitFor({ state: "visible" });
    assert.match(await page.locator("#pending-list").textContent(), /27/);
    await page.locator("#confirm-result").check();
    assert.equal(await page.locator("#save-result").isDisabled(), true);
    await page.locator("#allow-provisional").check();
    await page.screenshot({
      path: path.join(artifacts, "correcao.png"),
      fullPage: true,
    });
    await page.locator("#save-result").click();
    await page.locator("#saved-result").waitFor({ state: "visible" });
    assert.equal(saved.length, 1);
    assert.equal(saved[0].aluno, "Outro aluno");
    assert.equal(saved[0].permitir_provisorio, true);
    assert.equal(saved[0].resultado.provisorio, true);
    assert.equal(await page.locator("#save-result").isDisabled(), true);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.waitForFunction(() => document.body.classList.contains("sidebar-collapsed"));
    assert.equal(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      true,
    );
    await page.screenshot({
      path: path.join(artifacts, "mobile.png"),
      fullPage: true,
    });
    await page.locator("#sidebar-toggle").click();
    await page.getByRole("button", {name: "Avaliações", exact: true}).click();
    assert.equal(await page.locator("#page-title").textContent(), "Avaliações");
    assert.equal(await page.locator("#sidebar-toggle").getAttribute("aria-expanded"), "false");
    await page.locator("#sidebar-toggle").click();
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#sidebar-toggle").getAttribute("aria-expanded"), "false");
    assert.deepEqual(errors, []);
    await context.close();

    const denied = await browser.newPage();
    await denied.route("**/api/avaliacoes", (route) =>
      route.fulfill({ json: [] }),
    );
    await denied.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = async () => {
        throw new DOMException("negada", "NotAllowedError");
      };
    });
    await denied.goto(baseURL + "/interface/");
    await denied.locator("#camera-start").click();
    await denied
      .getByText("Permissão da câmera negada.", { exact: false })
      .waitFor();
    assert.equal(await denied.locator("#capture-button").isDisabled(), true);
    await denied.close();
  } finally {
    await browser.close();
  }
});
