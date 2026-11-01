/* QA opcional: Playwright instalado separadamente, Chrome local e backend ativo. */
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const { chromium } = require("playwright");

const baseURL = process.env.QA_BASE_URL || "http://127.0.0.1:8766";
const artifacts = process.env.QA_ARTIFACT_DIR;

async function mockStudents(page) {
  const students = [];
  const normalize = (value) =>
    value.trim().replace(/\s+/g, " ").normalize("NFC").toLowerCase();
  await page.route("**/api/alunos/correspondencias?*", (route) => {
    const name = normalize(
      new URL(route.request().url()).searchParams.get("nome"),
    );
    return route.fulfill({
      json: {
        exato:
          students.filter((a) => normalize(a.nome) === name).length === 1
            ? students.find((a) => normalize(a.nome) === name)
            : null,
        exatos: students.filter((a) => normalize(a.nome) === name),
        semelhantes: students.filter(
          (a) =>
            normalize(a.nome) !== name &&
            normalize(a.nome).includes(name.slice(0, 2)),
        ),
      },
    });
  });
  await page.route("**/api/alunos?*", (route) => {
    const term = normalize(
      new URL(route.request().url()).searchParams.get("busca") || "",
    );
    return route.fulfill({
      json: students
        .filter((a) => normalize(a.nome).includes(term))
        .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR")),
    });
  });
  students.corrections = [];
  students.commit = (input) => {
    const exact = students.filter(
      (a) => normalize(a.nome) === normalize(input.aluno),
    );
    if (exact.length > 1 && !input.aluno_id && !input.novo_homonimo)
      throw {
        codigo: "aluno_ambiguo",
        mensagem: "Confirme o aluno correto.",
        alunos: exact,
      };
    let student = input.aluno_id
      ? students.find((a) => a.id === input.aluno_id)
      : !input.novo_homonimo && exact[0];
    if (!student) {
      student = {
        id: "aluno-" + students.length,
        nome: input.aluno,
        criado_em: "2026-10-31T12:00:00Z",
      };
      students.push(student);
    }
    const record = {
      ...input,
      id: "correcao-" + students.corrections.length,
      aluno_id: student.id,
      avaliacao: "Teste",
      processada_em: "2026-10-31T12:00:00Z",
      situacao: input.resultado.provisorio ? "provisoria" : "sem_pendencias",
    };
    students.corrections.push(record);
    return record;
  };
  await page.route("**/api/correcoes/salvar", (route) => {
    try {
      return route.fulfill({
        status: 201,
        json: students.commit(route.request().postDataJSON()),
      });
    } catch (detail) {
      return route.fulfill({ status: 409, json: { detail } });
    }
  });
  await page.route("**/api/alunos/*/correcoes", (route) =>
    route.fulfill({
      json: {
        aluno: students.find((a) =>
          route
            .request()
            .url()
            .includes("/" + a.id + "/"),
        ),
        correcoes: students.corrections.filter((c) =>
          route
            .request()
            .url()
            .includes("/" + c.aluno_id + "/"),
        ),
        legadas_por_nome: [
          {
            id: "legada",
            avaliacao: "Avaliação antiga",
            resultado: { resumo: { pontuacao: 30, percentual_acertos: 60 } },
            processada_em: "2026-10-30T12:00:00Z",
            situacao: "provisoria",
          },
        ],
      },
    }),
  );
  return students;
}

test("automatic student creation only on save and visual review", async () => {
  const browser = await chromium.launch({
    executablePath: process.env.QA_CHROME_PATH,
    headless: true,
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1100 },
    });
    const students = await mockStudents(page);
    const official = Object.fromEntries(
      Array.from({ length: 50 }, (_, i) => [String(i + 1), "A"]),
    );
    await page.route("**/api/avaliacoes", (route) =>
      route.fulfill({
        json: [
          {
            id: "avaliacao-visual",
            titulo: "Teste visual",
            criada_em: "2026-10-31T12:00:00Z",
          },
        ],
      }),
    );
    await page.route("**/api/avaliacoes/*/gabarito", (route) =>
      route.fulfill({ json: { alternativas: official } }),
    );
    await page.goto(baseURL + "/interface/");
    assert.equal(await page.locator("[data-tab]").count(), 3);
    assert.equal(await page.locator("#student-create-form").count(), 0);
    assert.equal(await page.locator("#student-register-current").count(), 0);
    await page.locator('[data-tab="correcao"]').click();
    await page.locator("#evaluation-select").selectOption("avaliacao-visual");
    await page.locator("#student-name").fill("Ana Silva");
    await page
      .locator("#file-input")
      .setInputFiles(path.join(artifacts, "visual-mista.png"));
    const response = page.waitForResponse(
      (r) => r.url().endsWith("/api/correcoes/processar") && r.status() === 200,
    );
    await page.locator("#process-button").click();
    const payload = await (await response).json();
    await page.locator("#annotated-card").waitFor({ state: "visible" });
    assert.equal(await page.locator("#total-score").textContent(), "1");
    const pixel = async (number, letter) =>
      page.locator("#annotated-card").evaluate((canvas, box) => {
        return [
          ...canvas
            .getContext("2d")
            .getImageData(
              Math.floor(box.x),
              Math.round(box.y + box.altura / 2),
              1,
              1,
            ).data,
        ];
      }, payload.visualizacao.posicoes[number][letter]);
    let rgb = await pixel("1", "A");
    assert.ok(rgb[1] > rgb[0] && rgb[1] > rgb[2]);
    rgb = await pixel("2", "B");
    assert.ok(rgb[0] > rgb[1] && rgb[0] > rgb[2]);
    rgb = await pixel("4", "A");
    assert.ok(rgb[0] > 150 && rgb[1] > 150 && rgb[2] < 130);
    rgb = await pixel("3", "A");
    assert.ok(rgb[0] > 80 && Math.abs(rgb[0] - rgb[2]) < 70);
    const png = await page
      .locator("#annotated-card")
      .evaluate((canvas) => canvas.toDataURL("image/png").split(",")[1]);
    fs.writeFileSync(
      path.join(artifacts, "exemplo-correcao-visual.png"),
      Buffer.from(png, "base64"),
    );
    await page.locator("#confirm-result").check();
    await page.locator("#allow-provisional").check();
    await page.locator('[data-student-question="2"]').selectOption("A");
    await page.waitForFunction(
      () => document.getElementById("total-score").textContent === "2",
    );
    assert.equal(await page.locator("#confirm-result").isChecked(), false);
    assert.equal(await page.locator("#allow-provisional").isChecked(), false);
    rgb = await pixel("2", "A");
    assert.ok(rgb[1] > rgb[0] && rgb[1] > rgb[2]);
    assert.equal(students.corrections.length, 0);
    await page.locator("#confirm-result").check();
    await page.locator("#allow-provisional").check();
    await page.locator("#save-result").click();
    await page.locator("#saved-result").waitFor({ state: "visible" });
    const saved = students.corrections[0];
    assert.equal(saved.aluno_id, "aluno-0");
    assert.equal(saved.resultado.resumo.pontuacao, 2);
    assert.equal("visualizacao" in saved, false);

    await page.waitForFunction(
      () =>
        document.querySelectorAll("#students-list .evaluation-item").length ===
        1,
    );
    assert.equal(students.length, 1);
    await page.locator('[data-tab="alunos"]').click();
    await page.locator("#students-list button").click();
    await page.locator(".history-table").first().waitFor();
    assert.match(await page.locator("#student-history").textContent(), /2\/50/);
    await page.screenshot({
      path: path.join(artifacts, "alunos.png"),
      fullPage: true,
    });
    await page.locator('[data-tab="correcao"]').click();
    await page
      .locator("#file-input")
      .setInputFiles(path.join(artifacts, "visual-mista.png"));
    await page.locator("#process-button").click();
    await page.locator("#result-content").waitFor({ state: "visible" });
    await page.locator("#confirm-result").check();
    await page.locator("#allow-provisional").check();
    await page.locator("#save-result").click();
    await page.locator("#saved-result").waitFor({ state: "visible" });
    assert.equal(students.length, 1);
    assert.equal(
      students.corrections[1].aluno_id,
      students.corrections[0].aluno_id,
    );
  } finally {
    await browser.close();
  }
});

test("homônimos exigem escolha sem perder a correção", async () => {
  const browser = await chromium.launch({
    executablePath: process.env.QA_CHROME_PATH,
    headless: true,
  });
  try {
    const page = await browser.newPage();
    const students = await mockStudents(page);
    students.push(
      { id: "pessoa-a", nome: "Ana Silva" },
      { id: "pessoa-b", nome: "Ana Silva" },
    );
    const official = Object.fromEntries(
      Array.from({ length: 50 }, (_, i) => [String(i + 1), "A"]),
    );
    await page.route("**/api/avaliacoes", (r) =>
      r.fulfill({
        json: [
          {
            id: "avaliacao",
            titulo: "Teste",
            criada_em: "2026-10-31T12:00:00Z",
          },
        ],
      }),
    );
    await page.route("**/api/avaliacoes/*/gabarito", (r) =>
      r.fulfill({ json: { alternativas: official } }),
    );
    await page.goto(baseURL + "/interface/");
    await page.locator('[data-tab="correcao"]').click();
    await page.locator("#evaluation-select").selectOption("avaliacao");
    await page.locator("#student-name").fill("Ana Silva");
    await page.locator("#student-link-select").waitFor({ state: "visible" });
    await page
      .locator("#file-input")
      .setInputFiles(path.join(artifacts, "cartao.png"));
    await page.locator("#process-button").click();
    await page.locator("#result-content").waitFor({ state: "visible" });
    await page.locator("#confirm-result").check();
    await page.locator("#save-result").click();
    await page
      .getByText("Confirme o aluno correto.", { exact: true })
      .waitFor();
    assert.equal(students.corrections.length, 0);
    assert.equal(await page.locator("#confirm-result").isChecked(), false);
    assert.equal(await page.locator("#total-score").textContent(), "50");
    await page.locator("#student-link-select").selectOption("pessoa-b");
    await page.locator("#confirm-result").check();
    await page.locator("#save-result").click();
    await page.locator("#saved-result").waitFor({ state: "visible" });
    assert.equal(students.corrections[0].aluno_id, "pessoa-b");
    assert.equal(students.length, 2);
  } finally {
    await browser.close();
  }
});

test("OCR da mesma captura sugere nome editável e só salva após confirmação", async () => {
  const browser = await chromium.launch({
    executablePath: process.env.QA_CHROME_PATH,
    headless: true,
  });
  try {
    const page = await browser.newPage();
    const students = await mockStudents(page);
    const oficial = Object.fromEntries(
      Array.from({ length: 50 }, (_, i) => [String(i + 1), "A"]),
    );
    await page.route("**/api/avaliacoes", (route) =>
      route.fulfill({
        json: [
          {
            id: "ocr-teste",
            titulo: "Teste OCR",
            criada_em: "2026-10-31T12:00:00Z",
          },
        ],
      }),
    );
    await page.route("**/api/avaliacoes/*/gabarito", (route) =>
      route.fulfill({ json: { alternativas: oficial } }),
    );
    let saved = null;
    await page.route("**/api/correcoes/salvar", (route) => {
      saved = students.commit(route.request().postDataJSON());
      return route.fulfill({
        status: 201,
        json: { id: "correcao-ocr", aluno: saved.aluno },
      });
    });
    // Cartão de referência com nome IMPRESSO sintético inserido; não é manuscrito real.
    const image = fs
      .readFileSync(path.join(artifacts, "nome-impresso.png"))
      .toString("base64");
    await page.addInitScript((image) => {
      navigator.mediaDevices.getUserMedia = async () => {
        const photo = new Image();
        photo.src = "data:image/png;base64," + image;
        await photo.decode();
        const canvas = document.createElement("canvas");
        canvas.width = photo.width;
        canvas.height = photo.height;
        canvas.getContext("2d").drawImage(photo, 0, 0);
        return canvas.captureStream(2);
      };
    }, image);
    const files = {};
    page.on("request", (request) => {
      if (
        !["/api/alunos/reconhecer-nome", "/api/correcoes/processar"].some(
          (url) => request.url().endsWith(url),
        )
      )
        return;
      const boundary = request.headers()["content-type"].split("boundary=")[1];
      const body = request.postDataBuffer();
      const start = body.indexOf(Buffer.from("\r\n\r\n")) + 4;
      const end = body.indexOf(Buffer.from("\r\n--" + boundary), start);
      files[new URL(request.url()).pathname] = body.subarray(start, end);
    });
    await page.goto(baseURL + "/interface/");
    await page.getByRole("button", { name: "Correção", exact: true }).click();
    await page.locator("#evaluation-select").selectOption("ocr-teste");
    await page.bringToFront();
    await page.locator("#camera-start").click();
    await page.waitForFunction(
      () => document.getElementById("camera-video").videoWidth > 0,
    );
    await page.locator("#capture-button").click();
    await page.waitForFunction(
      () => document.getElementById("student-name").value === "MARIA DA SILVA",
    );
    assert.equal(saved, null);
    assert.equal(students.length, 0);
    await page.locator("#student-name").fill("Maria da Silva");
    await page.locator("#process-button").click();
    await page.locator("#result-content").waitFor({ state: "visible" });
    assert.deepEqual(
      files["/api/alunos/reconhecer-nome"],
      files["/api/correcoes/processar"],
    );
    assert.equal(
      await page.locator("#student-name").inputValue(),
      "Maria da Silva",
    );
    assert.equal(saved, null);
    assert.equal(await page.locator("#save-result").isDisabled(), true);
    await page.locator("#confirm-result").check();
    await page.locator("#save-result").click();
    await page.locator("#saved-result").waitFor({ state: "visible" });
    assert.equal(saved.aluno, "Maria da Silva");
    assert.equal(saved.confirmado, true);
  } finally {
    await browser.close();
  }
});

test("moldura fixa visível na inicialização e quando nenhuma folha é detectada", async () => {
  const browser = await chromium.launch({
    executablePath: process.env.QA_CHROME_PATH,
    headless: true,
    args: [
      "--use-fake-ui-for-media-stream",
      "--use-fake-device-for-media-stream",
    ],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1280, height: 960 },
    });
    let analysis = {
      estado: "vermelho",
      mensagem: "Folha não detectada.",
      cantos: [],
      folha_visivel: false,
    };
    await page.route("**/api/avaliacoes", (route) =>
      route.fulfill({ json: [] }),
    );
    await page.route("**/api/capturas/analisar", (route) =>
      route.fulfill({ json: analysis }),
    );
    // Mantém a permissão pendente para verificar a moldura antes do primeiro frame.
    await page.addInitScript(() => {
      const original = navigator.mediaDevices.getUserMedia.bind(
        navigator.mediaDevices,
      );
      navigator.mediaDevices.getUserMedia = async (constraints) => {
        await new Promise((resolve) => {
          window.releaseCamera = resolve;
        });
        return original(constraints);
      };
    });
    await page.goto(baseURL + "/interface/");
    await page.bringToFront();
    await page.locator("#camera-start").click();
    await page.waitForFunction(
      () => typeof window.releaseCamera === "function",
    );
    assert.equal(await page.locator("#camera-overlay").isVisible(), true);
    assert.equal(await page.locator(".guide").isVisible(), true);
    await page.evaluate(() => window.releaseCamera());
    await page.getByText("Folha não detectada.", { exact: true }).waitFor();
    assert.equal(
      await page.locator("#camera-overlay").getAttribute("hidden"),
      null,
    );
    assert.equal(await page.locator(".guide").isVisible(), true);
    assert.equal(await page.locator(".guide-corners").isVisible(), true);
    assert.equal(
      await page.locator("#detected-corners").getAttribute("points"),
      "",
    );
    const geometry = await page.evaluate(() => {
      const overlay = document.getElementById("camera-overlay");
      const video = document.getElementById("camera-video");
      const area = overlay.getBoundingClientRect();
      const guide = document.querySelector(".guide").getBoundingClientRect();
      const status = document
        .getElementById("frame-status")
        .getBoundingClientRect();
      return {
        inside:
          guide.x > area.x &&
          guide.y > area.y &&
          guide.right < area.right &&
          guide.bottom < area.bottom,
        statusOutside: status.top >= area.bottom,
        centered:
          Math.abs(guide.x + guide.width / 2 - area.x - area.width / 2) < 1 &&
          Math.abs(guide.y + guide.height / 2 - area.y - area.height / 2) < 1,
        ratio: guide.width / guide.height,
        above:
          Number(getComputedStyle(overlay).zIndex) >
          Number(getComputedStyle(video).zIndex),
        stroke: getComputedStyle(document.querySelector(".guide")).stroke,
      };
    });
    assert.equal(geometry.inside, true);
    assert.equal(geometry.centered, true);
    assert.equal(geometry.above, true);
    assert.equal(geometry.statusOutside, true);
    assert.ok(Math.abs(geometry.ratio - 210 / 297) < 0.01);
    assert.equal(geometry.stroke, "rgb(255, 119, 129)");
    const fixed = await page.locator(".guide").getAttribute("x");
    if (artifacts)
      await page.screenshot({
        path: path.join(artifacts, "moldura-sem-folha.png"),
        fullPage: true,
      });
    for (const [estado, cor] of [
      ["amarelo", "rgb(246, 198, 91)"],
      ["verde", "rgb(95, 219, 171)"],
      ["vermelho", "rgb(255, 119, 129)"],
    ]) {
      analysis = {
        estado,
        mensagem: estado,
        cantos:
          estado === "vermelho"
            ? []
            : [
                [0.1, 0.1],
                [0.8, 0.1],
                [0.8, 0.9],
                [0.1, 0.9],
              ],
        folha_visivel: estado !== "vermelho",
      };
      await page.waitForFunction(
        (expected) =>
          getComputedStyle(document.querySelector(".guide")).stroke ===
          expected,
        cor,
      );
      assert.equal(await page.locator(".guide").isVisible(), true);
      assert.equal(await page.locator(".guide").getAttribute("x"), fixed);
    }
    await page.locator("#camera-stop").click();
    assert.equal(await page.locator("#camera-overlay").isHidden(), true);
  } finally {
    await browser.close();
  }
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
    const students = await mockStudents(page);
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
      const stored = students.commit(input);
      saved.push(stored);
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
    assert.equal(
      await page.evaluate(() => document.fonts.check("500 14px Manrope")),
      true,
    );
    assert.equal(
      await page.locator("#sidebar-toggle").getAttribute("aria-expanded"),
      "true",
    );
    await page.locator("#sidebar-toggle").click();
    assert.equal(
      await page.locator("#sidebar-toggle").getAttribute("aria-expanded"),
      "false",
    );
    assert.equal(
      await page
        .locator(".sidebar")
        .evaluate((element) => element.getBoundingClientRect().width),
      80,
    );
    await page.getByRole("button", { name: "Correção", exact: true }).click();
    assert.equal(await page.locator("#page-title").textContent(), "Correção");
    await page.getByRole("button", { name: "Avaliações", exact: true }).click();
    assert.equal(await page.locator("#page-title").textContent(), "Avaliações");
    await page.locator("#sidebar-toggle").click();
    await page.bringToFront();
    await page.locator("#camera-start").click();
    await page.waitForFunction(
      () => document.getElementById("camera-video").srcObject !== null,
    );
    await page.locator("#capture-button").waitFor({ state: "visible" });
    await page.waitForFunction(
      () => !document.getElementById("capture-button").disabled,
    );
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
    await page.waitForFunction(() =>
      document.body.classList.contains("sidebar-collapsed"),
    );
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
    await page.getByRole("button", { name: "Avaliações", exact: true }).click();
    assert.equal(await page.locator("#page-title").textContent(), "Avaliações");
    assert.equal(
      await page.locator("#sidebar-toggle").getAttribute("aria-expanded"),
      "false",
    );
    await page.locator("#sidebar-toggle").click();
    await page.keyboard.press("Escape");
    assert.equal(
      await page.locator("#sidebar-toggle").getAttribute("aria-expanded"),
      "false",
    );
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

test("page fragments load before initialization and failures keep navigation disabled", async () => {
  const browser = await chromium.launch({ executablePath: process.env.QA_CHROME_PATH, headless: true });
  try {
    const page = await browser.newPage();
    await page.route("**/api/avaliacoes", route => route.fulfill({ json: [] }));
    let requested;
    const loading = new Promise(resolve => { requested = resolve; });
    let release;
    const pending = new Promise(resolve => { release = resolve; });
    await page.route("**/pages/correcao.html", async route => {
      requested();
      await pending;
      await route.continue();
    });
    await page.goto(baseURL + "/interface/", { waitUntil: "commit" });
    await loading;
    await page.locator('[data-tab="alunos"]').waitFor();
    assert.equal(await page.locator('[data-tab="alunos"]').isDisabled(), true);
    assert.equal(await page.locator('#camera-start').count(), 0);
    release();
    await page.locator('#camera-start').waitFor();
    await page.locator('[data-tab="correcao"]').click();
    assert.equal(await page.locator('#correction-fields').isVisible(), true);
    await page.locator('[data-tab="alunos"]').click();
    assert.equal(await page.locator('#students-panel').isVisible(), true);
    await page.locator('[data-tab="avaliacoes"]').click();
    assert.equal(await page.locator('#evaluation-fields').isVisible(), true);
    assert.equal(await page.locator('#camera-video').count(), 1);
    await page.close();
    const failed = await browser.newPage();
    const apiCalls = [];
    failed.on('request', request => { if (request.url().includes('/api/')) apiCalls.push(request.url()); });
    await failed.route('**/pages/alunos.html', route => route.fulfill({ status: 404, body: '' }));
    await failed.goto(baseURL + '/interface/');
    await failed.locator('#message.error').waitFor();
    assert.equal(await failed.locator('[data-tab="avaliacoes"]').isDisabled(), true);
    assert.equal(await failed.locator('#camera-video').count(), 0);
    assert.deepEqual(apiCalls, []);
    await failed.close();
  } finally { await browser.close(); }
});
