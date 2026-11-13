/* QA isolado: login e API simulados, servidor estático local e dados sintéticos. */
const test = require("node:test");
const assert = require("node:assert/strict");
const path = require("node:path");
const fs = require("node:fs");
const { createHash } = require("node:crypto");
const environment = require("./browser-environment.cjs");
const { chromium } = environment;
let baseURL, artifacts;
test.before(async () => {
  await environment.start();
  ({ baseURL, artifacts } = environment);
});
test.after(() => environment.stop());

test("dashboard abre diretamente sem login e preserva navega??o", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.goto(baseURL + "/interface/#alunos");
    await page.locator("#students-panel").waitFor();
    assert.equal(await page.locator("#login-panel").isHidden(), true);
    assert.equal(await page.locator("#login-form").isHidden(), true);
    assert.equal(await page.locator("#logout").isHidden(), true);
    for (const tab of ["avaliacoes", "correcao", "alunos"]) {
      await page.locator(`[data-tab="${tab}"]`).click();
      assert.equal(new URL(page.url()).hash, `#${tab}`);
    }
    await page.reload();
    await page.locator("#students-panel").waitFor();
    assert.equal(await page.locator("#login-form").isHidden(), true);
  } finally { await browser.close(); }
});

test("demonstração pública abre sem login, mostra aviso e não oferece salvamento", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route("**/interface/js/config.mjs", route => route.fulfill({
      contentType: "text/javascript",
      body: `export const API_BASE_URL="https://corretor-gabaritos-8yal.onrender.com";
        export const PUBLIC_DEMO=true; export const PUBLIC_OPEN=false; export const AUTH_REQUIRED=false;
        export const FIREBASE_API_KEY=""; export const FIREBASE_AUTH_DOMAIN="";
        export const FIREBASE_PROJECT_ID=""; export const FIREBASE_APP_ID="";`,
    }));
    const paths = [];
    await page.route("https://corretor-gabaritos-8yal.onrender.com/api/**", route => {
      const request = route.request();
      const endpoint = new URL(request.url()).pathname;
      paths.push(endpoint);
      assert.equal(request.headers().authorization, undefined);
      const headers = { "Access-Control-Allow-Origin": baseURL };
      const json = endpoint === "/api/avaliacoes"
        ? [{ id: "demonstracao-50", titulo: "Avaliação fictícia", criada_em: "2026-11-01T00:00:00Z" }]
        : endpoint === "/api/alunos/correspondencias"
          ? { exato: null, exatos: [], semelhantes: [] }
          : endpoint === "/api/alunos" ? { alunos: [], proximo_cursor: null } : {};
      return route.fulfill({ json, headers });
    });
    await page.goto(baseURL + "/interface/");
    await page.locator("#demo-banner").waitFor({ state: "visible" });
    await page.locator("#capture-workspace").waitFor({ state: "hidden" });
    assert.equal(await page.locator("#login-panel").isHidden(), true);
    await page.locator('[data-tab="correcao"]').click();
    assert.equal(await page.locator("#save-result").isHidden(), true);
    assert.equal(await page.locator("#batch-panel").isHidden(), true);
    assert.equal(await page.locator("#export-panel").isHidden(), true);
    await page.locator('[data-tab="alunos"]').click();
    assert.equal(await page.locator("#students-panel").isVisible(), true);
    assert.ok(paths.includes("/api/avaliacoes"));
    assert.ok(paths.includes("/api/alunos"));
    assert.ok(!paths.includes("/api/auth/me"));
  } finally { await browser.close(); }
});

test("sessão pública anônima abre sem login e é reutilizada após atualização", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route("**/interface/js/config.mjs", route => route.fulfill({
      contentType: "text/javascript",
      body: `export const API_BASE_URL="https://corretor-gabaritos-8yal.onrender.com";
        export const PUBLIC_DEMO=false; export const PUBLIC_OPEN=true; export const AUTH_REQUIRED=false;
        export const FIREBASE_API_KEY=""; export const FIREBASE_AUTH_DOMAIN="";
        export const FIREBASE_PROJECT_ID=""; export const FIREBASE_APP_ID="";`,
    }));
    const token = `${"a".repeat(32)}.1790000000.${"b".repeat(43)}`;
    let issued = 0, validated = 0, business = 0;
    await page.route("https://corretor-gabaritos-8yal.onrender.com/api/**", route => {
      const request = route.request(), endpoint = new URL(request.url()).pathname;
      const headers = { "Access-Control-Allow-Origin": baseURL,
        "Access-Control-Allow-Headers": "authorization,content-type",
        "Access-Control-Allow-Methods": "GET,POST,DELETE" };
      if (request.method() === "OPTIONS") return route.fulfill({ status: 200, headers });
      if (endpoint === "/api/public/session" && request.method() === "POST") {
        issued++;
        assert.equal(request.headers().authorization, undefined);
        return route.fulfill({ headers, json: { token, expires_in: 2592000 } });
      }
      assert.equal(request.headers().authorization, `Bearer ${token}`);
      if (endpoint === "/api/public/session") {
        validated++;
        return route.fulfill({ headers, json: { status: "ok" } });
      }
      business++;
      const json = endpoint === "/api/avaliacoes" ? []
        : endpoint === "/api/alunos/correspondencias"
          ? { exato: null, exatos: [], semelhantes: [] }
          : endpoint === "/api/alunos" ? { alunos: [], proximo_cursor: null } : {};
      return route.fulfill({ headers, json });
    });
    await page.goto(baseURL + "/interface/");
    await page.locator("#public-banner").waitFor({ state: "visible" });
    await page.locator("#evaluation-list").getByText("Nenhuma avaliação cadastrada").waitFor();
    assert.equal(await page.locator("#login-panel").isHidden(), true);
    assert.equal(issued, 1);
    await page.reload();
    await page.locator("#public-banner").waitFor({ state: "visible" });
    await page.locator("#evaluation-list").getByText("Nenhuma avaliação cadastrada").waitFor();
    assert.equal(issued, 1);
    assert.equal(validated, 1);
    assert.ok(business >= 2);
  } finally { await browser.close(); }
});

test("site público compartilhado abre em dois navegadores sem criar sessão ou usar Firebase", async () => {
  const browser = await chromium.launch();
  try {
    const seen = [];
    for (const page of [await browser.newPage(), await browser.newPage()]) {
      await page.route("**/interface/js/config.mjs", route => route.fulfill({
        contentType: "text/javascript",
        body: `export const API_BASE_URL="https://corretor-gabaritos-8yal.onrender.com";
          export const PUBLIC_DEMO=false; export const PUBLIC_OPEN=false;
          export const PUBLIC_SHARED=true; export const AUTH_REQUIRED=false;
          export const FIREBASE_API_KEY=""; export const FIREBASE_AUTH_DOMAIN="";
          export const FIREBASE_PROJECT_ID=""; export const FIREBASE_APP_ID="";`,
      }));
      await page.route("https://corretor-gabaritos-8yal.onrender.com/api/**", route => {
        const endpoint = new URL(route.request().url()).pathname;
        seen.push(endpoint);
        assert.equal(route.request().headers().authorization, undefined);
        assert.notEqual(endpoint, "/api/public/session");
        const headers = { "Access-Control-Allow-Origin": baseURL,
          "Access-Control-Allow-Headers": "content-type,x-lote-token",
          "Access-Control-Allow-Methods": "GET,POST,DELETE" };
        if (route.request().method() === "OPTIONS") return route.fulfill({ status: 200, headers });
        const json = endpoint === "/api/avaliacoes"
          ? [{ id: "prova-ficticia", titulo: "Avaliação compartilhada", criada_em: "2026-11-13T00:00:00Z" }]
          : endpoint === "/api/alunos/correspondencias"
            ? { exato: null, exatos: [], semelhantes: [] }
            : endpoint === "/api/alunos" ? [] : {};
        return route.fulfill({ json, headers });
      });
      await page.goto(baseURL + "/interface/");
      await page.locator("#public-banner").waitFor({ state: "visible" });
      await page.locator("#evaluation-list").getByText("Avaliação compartilhada").waitFor();
      assert.equal(await page.locator("#login-panel").isHidden(), true);
      await page.locator('[data-tab="correcao"]').click();
      assert.equal(await page.locator("#correction-fields").isVisible(), true);
    }
    assert.equal(seen.filter(path => path === "/api/avaliacoes").length, 2);
  } finally { await browser.close(); }
});

test("Vercel simulada exige login, restaura sessão autorizada e faz logout", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route("**/interface/js/config.mjs", route => route.fulfill({
      contentType: "text/javascript", body: `export const API_BASE_URL="https://corretor-gabaritos-8yal.onrender.com";
        export const PUBLIC_DEMO=false; export const PUBLIC_OPEN=false; export const AUTH_REQUIRED=true; export const FIREBASE_API_KEY="chave-publica-ficticia";
        export const FIREBASE_AUTH_DOMAIN="projeto-ficticio.firebaseapp.com";
        export const FIREBASE_PROJECT_ID="projeto-ficticio"; export const FIREBASE_APP_ID="app-ficticio";`,
    }));
    await page.route("**/firebase-app.js", route => route.fulfill({
      contentType: "text/javascript", headers: { "Access-Control-Allow-Origin": "*" },
      body: "export const initializeApp = config => config;",
    }));
    await page.route("**/firebase-auth.js", route => route.fulfill({
      contentType: "text/javascript", headers: { "Access-Control-Allow-Origin": "*" },
      body: `export const browserLocalPersistence={};
        let listeners=[];
        export function initializeAuth() {
          const auth={currentUser: localStorage.getItem("fake-admin") ? {uid:"admin-ficticio"} : null,
            authStateReady: async()=>{}}; return auth;
        }
        export function onAuthStateChanged(auth, cb) { listeners.push(cb); queueMicrotask(()=>cb(auth.currentUser)); return ()=>{ listeners=listeners.filter(x=>x!==cb); }; }
        export async function getIdToken(user) { return user ? "token-ficticio" : null; }
        export async function signInWithEmailAndPassword(auth) { auth.currentUser={uid:"admin-ficticio"}; localStorage.setItem("fake-admin","1"); listeners.forEach(cb=>cb(auth.currentUser)); return {user:auth.currentUser}; }
        export async function signOut(auth) { auth.currentUser=null; localStorage.removeItem("fake-admin"); listeners.forEach(cb=>cb(null)); }`,
    }));
    let authorizedCalls = 0;
    await page.route("https://corretor-gabaritos-8yal.onrender.com/api/**", route => {
      const req = route.request();
      const headers = { "Access-Control-Allow-Origin": baseURL,
        "Access-Control-Allow-Headers": "authorization,content-type",
        "Access-Control-Allow-Methods": "GET,POST,DELETE" };
      if (req.method() === "OPTIONS") return route.fulfill({ status: 200, headers });
      assert.equal(req.headers().authorization, "Bearer token-ficticio");
      authorizedCalls++;
      const path = new URL(req.url()).pathname;
      return route.fulfill({ headers, json: path === "/api/auth/me" ? {uid:"admin-ficticio"} : [] });
    });
    await page.goto(baseURL + "/interface/#alunos");
    await page.locator("#login-form").waitFor({ state: "visible" });
    assert.equal(await page.locator("#sidebar").isVisible(), false);
    assert.equal(authorizedCalls, 0);
    await page.locator("#login-email").fill("admin@example.test");
    await page.locator("#login-password").fill("senha-ficticia");
    await page.locator("#login-form button[type=submit]").click();
    await page.locator("#students-panel").waitFor({ state: "visible" });
    assert.ok(authorizedCalls > 0);
    await page.reload();
    await page.locator("#students-panel").waitFor({ state: "visible" });
    assert.equal(await page.locator("#login-form").isHidden(), true);
    await page.locator("#logout").click();
    await page.locator("#login-form").waitFor({ state: "visible" });
    assert.equal(await page.locator("#sidebar").isVisible(), false);
  } finally { await browser.close(); }
});

test("captura móvel exige conferência, suporta orientação e descarta foto", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({
      viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true,
    });
    await page.goto(baseURL + "/interface/");
    const input = page.locator("#mobile-camera-input");
    await input.waitFor();
    assert.equal(await input.getAttribute("capture"), "environment");
    assert.equal(await page.locator(".mobile-photo-choice").isVisible(), true);
    await input.setInputFiles(path.join(artifacts, "cartao.png"));
    assert.equal(await page.locator("#photo-review").isVisible(), true);
    assert.equal(await page.locator("#process-button").isDisabled(), true);
    await page.locator("#manual-corners .corner-handle").first().waitFor({ state: "visible" });
    const before = await page.locator("#manual-corners-outline polygon").getAttribute("points");
    await page.locator("#manual-corners .corner-handle").first().press("ArrowRight");
    const after = await page.locator("#manual-corners-outline polygon").getAttribute("points");
    assert.notEqual(after, before);
    await page.locator("#confirm-photo").click();
    assert.equal(await page.locator("#photo-review").isHidden(), true);
    assert.equal(await page.locator("#process-button").isEnabled(), true);
    await page.locator("#edit-corners").click();
    assert.equal(await page.locator("#process-button").isDisabled(), true);
    await page.locator("#confirm-photo").click();
    assert.equal(await page.locator("#process-button").isEnabled(), true);
    let submittedCorners = false;
    await page.route("**/api/gabaritos/reconhecer", route => {
      const body = route.request().postDataBuffer().toString("latin1");
      submittedCorners = /name="cantos"/.test(body) && /name="captura"/.test(body);
      return route.fulfill({ json: Object.fromEntries(
        Array.from({ length: 50 }, (_, i) => [String(i + 1),
          { estado: "marcada", resposta: "A", alternativas: ["A"] }])) });
    });
    const uploaded = page.waitForResponse(response =>
      response.url().includes("/api/gabaritos/reconhecer"));
    await page.locator("#process-button").click();
    await uploaded;
    assert.equal(submittedCorners, true);
    await page.setViewportSize({ width: 844, height: 390 });
    assert.equal(await page.locator("#capture-preview").isVisible(), true);
    assert.equal(await page.locator("#camera-stage").evaluate(el =>
      el.getBoundingClientRect().width <= document.documentElement.clientWidth), true);
    await page.setViewportSize({ width: 390, height: 844 });
    await input.setInputFiles(path.join(artifacts, "cartao.png"));
    await page.locator("#discard-photo").click();
    assert.equal(await page.locator("#capture-preview").isHidden(), true);
    assert.equal(await page.locator("#process-button").isDisabled(), true);
  } finally { await browser.close(); }
});

test("lote ZIP usa revisão e salvamento individual sem gravação automática", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const students = await mockStudents(page);
    const official = Object.fromEntries(Array.from({ length: 50 }, (_, i) => [String(i + 1), "A"]));
    const image = fs.readFileSync(path.join(artifacts, "cartao.png"));
    const digest = createHash("sha256").update(image).digest("hex");
    const id = "a".repeat(32);
    let saves = 0;
    await page.route("**/api/avaliacoes", route => route.fulfill({ json: [
      { id: "prova-lote", titulo: "Prova de lote" },
    ] }));
    await page.route("**/api/avaliacoes/*/gabarito", route =>
      route.fulfill({ json: { alternativas: official } }));
    const manifesto = { lote_id: id, total: 3, imagens: [
      { indice: 0, nome: "01.png", estado: "pendente" },
      { indice: 1, nome: "invalido.txt", estado: "falha", erro: "Formato não suportado." },
      { indice: 2, nome: "03.png", estado: "pendente" },
    ] };
    await page.route("**/api/lotes/zip", route => route.fulfill({ json: manifesto }));
    await page.route(`**/api/lotes/${id}`, route => route.fulfill({ json: manifesto }));
    await page.route("**/api/operacoes/correcao/*", route =>
      route.fulfill({ json: { estado: saves ? "confirmada" : "nao_encontrada",
        registro: { id: "confirmada-simulada" } } }));
    await page.route(`**/api/lotes/${id}/imagens/0`, route => route.fulfill({
      body: image, contentType: "image/png", headers: { "X-Image-SHA256": digest },
    }));
    await page.route(`**/api/lotes/${id}/imagens/2`, route => route.fulfill({
      body: image, contentType: "image/png", headers: { "X-Image-SHA256": digest },
    }));
    await page.route("**/api/correcoes/salvar", route => {
      saves++;
      const payload = route.request().postDataJSON();
      assert.deepEqual(payload.origem_lote, { lote_id: id, indice: 0, imagem_sha256: digest });
      return route.fulfill({ status: 201, json: students.commit(payload) });
    });
    await page.goto(baseURL + "/interface/");
    await page.locator('[data-tab="correcao"]').click();
    await page.locator("#evaluation-select").selectOption("prova-lote");
    await page.locator("#batch-file").setInputFiles({ name: "lote.zip", mimeType: "application/zip", buffer: Buffer.from("zip simulado") });
    await page.getByText("Imagens identificadas: 2", { exact: false }).waitFor();
    assert.equal(saves, 0);
    await page.locator("#batch-next").click();
    await page.getByText("Imagem 1/3", { exact: false }).waitFor();
    await page.locator("#student-name").fill("Aluno fictício");
    await page.locator("#process-button").click();
    await page.locator("#result-content").waitFor({ state: "visible" });
    assert.equal(saves, 0);
    assert.equal(await page.locator("#batch-next").isDisabled(), true);
    await page.locator("#confirm-result").check();
    await page.locator("#save-result").click();
    await page.getByText("Confirmadas: 1", { exact: false }).waitFor();
    assert.equal(saves, 1);
    assert.match(await page.locator("#batch-summary").textContent(), /Falhas: 1/);
    await page.locator("#batch-next").click();
    await page.waitForFunction(() => document.getElementById("student-name").value === "MARIA DA SILVA");
    assert.equal(await page.locator("#student-name").inputValue(), "MARIA DA SILVA");
    await page.reload();
    await page.locator('[data-tab="correcao"]').click();
    await page.getByText("Confirmadas: 1", { exact: false }).waitFor();
    assert.equal(await page.locator("#batch-pause").textContent(), "Continuar");
    assert.equal(saves, 1);
  } finally { await browser.close(); }
});

test("páginas PDF no ZIP mantêm nome, página e revisão individual", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const students = await mockStudents(page);
    const image = fs.readFileSync(path.join(artifacts, "cartao.png"));
    const digest = createHash("sha256").update(image).digest("hex");
    const id = "e".repeat(32);
    const official = Object.fromEntries(Array.from({ length: 50 }, (_, i) => [String(i + 1), "A"]));
    const manifesto = { lote_id: id, total: 2, imagens: [
      { indice: 0, nome: "digitalizados/cartoes.pdf", pagina: 1, estado: "pendente" },
      { indice: 1, nome: "digitalizados/cartoes.pdf", pagina: 2, estado: "pendente" },
    ] };
    let saves = 0;
    await page.route("**/api/avaliacoes", route => route.fulfill({ json: [
      { id: "prova-pdf", titulo: "Prova PDF" },
    ] }));
    await page.route("**/api/avaliacoes/*/gabarito", route =>
      route.fulfill({ json: { alternativas: official } }));
    await page.route("**/api/lotes/zip", route => route.fulfill({ json: manifesto }));
    await page.route(`**/api/lotes/${id}/imagens/*`, route => route.fulfill({
      body: image, contentType: "image/jpeg", headers: { "X-Image-SHA256": digest },
    }));
    await page.route("**/api/correcoes/salvar", route => {
      saves++;
      const payload = route.request().postDataJSON();
      assert.deepEqual(payload.origem_lote, { lote_id: id, indice: 0,
        imagem_sha256: digest, arquivo: "digitalizados/cartoes.pdf", pagina: 1 });
      return route.fulfill({ status: 201, json: students.commit(payload) });
    });
    await page.goto(baseURL + "/interface/#correcao");
    await page.locator("#evaluation-select").selectOption("prova-pdf");
    await page.locator("#batch-file").setInputFiles({ name: "lote.zip", mimeType: "application/zip",
      buffer: Buffer.from("zip simulado") });
    await page.getByText("Imagens identificadas: 2", { exact: false }).waitFor();
    assert.equal(saves, 0);
    await page.locator("#batch-next").click();
    await page.getByText("Imagem 1/2", { exact: false }).waitFor();
    assert.match(await page.locator("#batch-current").textContent(), /cartoes\.pdf, página 1/);
    await page.locator("#student-name").fill("Aluno fictício");
    await page.locator("#process-button").click();
    await page.locator("#result-content").waitFor({ state: "visible" });
    assert.equal(saves, 0);
    await page.locator("#confirm-result").check();
    await page.locator("#save-result").click();
    await page.getByText("Confirmadas: 1", { exact: false }).waitFor();
    await page.locator("#batch-next").click();
    await page.getByText("Imagem 2/2", { exact: false }).waitFor();
    assert.match(await page.locator("#batch-current").textContent(), /cartoes\.pdf, página 2/);
    assert.equal(saves, 1);
  } finally { await browser.close(); }
});

test("interface identifica resposta antiga que rejeita PDF em subpasta", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route("**/api/lotes/zip", route => route.fulfill({ json: {
      lote_id: "f".repeat(32), total: 1, imagens: [{
        indice: 0, nome: "Nova pasta/Grade_de_respostas_com_linhas (1).pdf",
        estado: "falha", erro: "Formato não suportado. Use JPG ou PNG.",
      }],
    } }));
    await page.goto(baseURL + "/interface/#correcao");
    await page.locator("#batch-panel").waitFor({ state: "visible" });
    await page.locator("#batch-file").setInputFiles({ name: "gabaritos.zip",
      mimeType: "application/zip", buffer: Buffer.from("zip simulado") });
    await page.getByText("Falhas: 1", { exact: false }).waitFor();
    assert.match(await page.locator("#batch-errors").textContent(),
      /Grade_de_respostas_com_linhas \(1\)\.pdf.*Reinicie o backend local/);
  } finally { await browser.close(); }
});

test("lote pausa, isola falha individual e cancela sem salvar", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const id = "b".repeat(32);
    let cancelar = 0;
    await page.route("**/api/lotes/zip", route => route.fulfill({ json: {
      lote_id: id, total: 2, imagens: [
        { indice: 0, nome: "01.png", estado: "pendente" },
        { indice: 1, nome: "02.png", estado: "pendente" },
      ],
    } }));
    await page.route(`**/api/lotes/${id}/imagens/0`, route =>
      route.fulfill({ status: 422, json: { detail: "Imagem ilegível." } }));
    await page.route(`**/api/lotes/${id}`, route => {
      cancelar++;
      return route.fulfill({ status: 204, body: "" });
    });
    await page.goto(baseURL + "/interface/");
    await page.locator('[data-tab="correcao"]').click();
    await page.locator("#batch-file").setInputFiles({ name: "lote.zip", mimeType: "application/zip", buffer: Buffer.from("zip simulado") });
    await page.getByText("Imagens identificadas: 2", { exact: false }).waitFor();
    await page.locator("#batch-pause").click();
    assert.equal(await page.locator("#batch-next").isDisabled(), true);
    await page.locator("#batch-pause").click();
    await page.locator("#batch-next").click();
    await page.getByText("Falhas: 1", { exact: false }).waitFor();
    assert.equal(await page.locator("#batch-next").isEnabled(), true);
    await page.locator("#batch-cancel").click();
    await page.getByText("Canceladas: 1", { exact: false }).waitFor();
    assert.equal(cancelar, 1);
    assert.equal(await page.locator("#save-result").isDisabled(), true);
  } finally { await browser.close(); }
});

test("lote recupera resposta perdida com o mesmo ID após atualizar a página", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const students = await mockStudents(page);
    const id = "c".repeat(32);
    const image = fs.readFileSync(path.join(artifacts, "cartao.png"));
    const digest = createHash("sha256").update(image).digest("hex");
    const manifesto = { lote_id: id, total: 1, imagens: [
      { indice: 0, nome: "01.png", estado: "pendente" },
    ] };
    const official = Object.fromEntries(Array.from({ length: 50 }, (_, i) => [String(i + 1), "A"]));
    const enviados = [];
    await page.route("**/api/avaliacoes", route => route.fulfill({ json: [
      { id: "prova-lote", titulo: "Prova de lote" },
    ] }));
    await page.route("**/api/avaliacoes/*/gabarito", route =>
      route.fulfill({ json: { alternativas: official } }));
    await page.route("**/api/lotes/zip", route => route.fulfill({ json: manifesto }));
    await page.route(`**/api/lotes/${id}`, route => route.fulfill({ json: manifesto }));
    await page.route(`**/api/lotes/${id}/imagens/0`, route => route.fulfill({
      body: image, contentType: "image/png", headers: { "X-Image-SHA256": digest },
    }));
    await page.route("**/api/operacoes/correcao/*", route =>
      route.fulfill({ json: { estado: "nao_encontrada" } }));
    await page.route("**/api/correcoes/salvar", route => {
      const payload = route.request().postDataJSON();
      enviados.push(payload);
      if (enviados.length === 1) return route.abort("failed");
      return route.fulfill({ status: 201, json: students.commit(payload) });
    });
    await page.goto(baseURL + "/interface/");
    await page.locator('[data-tab="correcao"]').click();
    await page.locator("#evaluation-select").selectOption("prova-lote");
    await page.locator("#batch-file").setInputFiles({ name: "lote.zip", mimeType: "application/zip", buffer: Buffer.from("zip simulado") });
    await page.locator("#batch-next").click();
    await page.getByText("Imagem 1/1", { exact: false }).waitFor();
    await page.locator("#student-name").fill("Aluno fictício");
    await page.locator("#process-button").click();
    await page.locator("#result-content").waitFor({ state: "visible" });
    await page.locator("#confirm-result").check();
    await page.locator("#save-result").click();
    await page.locator("#recovery-panel").waitFor({ state: "visible" });
    assert.equal(await page.locator("#batch-next").isDisabled(), true);
    await page.reload();
    await page.locator('[data-tab="correcao"]').click();
    await page.locator("#recovery-panel").waitFor({ state: "visible" });
    await page.getByRole("button", { name: "Consultar estado" }).click();
    await page.getByRole("button", { name: "Reenviar mesma operação" }).click();
    await page.getByText("Confirmadas: 1", { exact: false }).waitFor();
    assert.equal(enviados.length, 2);
    assert.equal(enviados[0].operacao_id, enviados[1].operacao_id);
    assert.deepEqual(enviados[1].origem_lote,
      { lote_id: id, indice: 0, imagem_sha256: digest });
    assert.equal(students.corrections.length, 1);
  } finally { await browser.close(); }
});

test("lote não aceita confirmação local sem validação pelo backend", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const id = "d".repeat(32);
    const operacao = "11111111-1111-4111-8111-111111111111";
    await page.route(`**/api/lotes/${id}`, route => route.request().method() === "DELETE"
      ? route.fulfill({ status: 204, body: "" })
      : route.fulfill({ json: { lote_id: id, total: 1, imagens: [
          { indice: 0, nome: "01.png", estado: "pendente" },
        ] } }));
    await page.route("**/api/operacoes/correcao/*", route =>
      route.fulfill({ json: { estado: "nao_encontrada" } }));
    await page.goto(baseURL + "/interface/");
    await page.locator("#batch-file").waitFor({ state: "attached" });
    await page.evaluate(({ id, operacao }) => localStorage.setItem("corretor:lote-operacional:v1", JSON.stringify({
      id, atual: null, operacao: null,
      estados: [{ estado: "confirmada", tentada: true, operacaoId: operacao }],
    })), { id, operacao });
    await page.reload();
    await page.getByText("Não foi possível restaurar o lote", { exact: false }).waitFor();
    await page.locator('[data-tab="correcao"]').click();
    assert.equal(await page.locator("#batch-file").isDisabled(), true);
    assert.equal(await page.locator("#batch-cancel").isEnabled(), true);
    await page.locator("#batch-cancel").click();
    await page.waitForFunction(() => !document.getElementById("batch-file").disabled);
  } finally { await browser.close(); }
});

test("API bloqueada mostra erro sem pedir login", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route("**/api/avaliacoes", route =>
      route.fulfill({ status: 403, json: { detail: "Acesso bloqueado pelo backend." } }));
    await page.goto(baseURL + "/interface/");
    await page.getByText("Acesso bloqueado pelo backend.").first().waitFor();
    assert.equal(await page.locator("#evaluation-fields").isVisible(), true);
    assert.equal(await page.locator("#login-form").isHidden(), true);
  } finally { await browser.close(); }
});

test("exportação local baixa CSV e resumo somente após resposta completa", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage({ acceptDownloads: true });
    await page.route("**/api/avaliacoes", route => route.fulfill({ json: [
      { id: "prova-ficticia", titulo: "Evento fictício" },
    ] }));
    let falhar = false;
    await page.route("**/api/correcoes/exportar*", route => falhar
      ? route.fulfill({ status: 503, json: { detail: "Leitura incompleta." } })
      : route.fulfill({ json: {
        csv: "\ufeffcorrecao_id;operacao_id;aluno_nome\r\nc1;o1;Aluno fictício\r\n",
        resumo: { total_correcoes: 1, alunos_distintos: 1, operacoes_sem_id: 0,
          identificadores: [{ correcao_id: "c1", operacao_id: "o1" }] },
      } }));
    await page.goto(baseURL + "/interface/#correcao");
    await page.locator("#export-panel").waitFor({ state: "visible" });
    await page.locator("#export-evaluation").selectOption("prova-ficticia");
    const [csv] = await Promise.all([
      page.waitForEvent("download"), page.locator("#export-results").click(),
    ]);
    assert.match(csv.suggestedFilename(), /^correcoes-prova-ficticia-/);
    assert.match(fs.readFileSync(await csv.path(), "utf8"), /c1;o1;Aluno fictício/);
    await page.getByText("1 correções confirmadas", { exact: false }).waitFor();
    const [resumo] = await Promise.all([
      page.waitForEvent("download"), page.locator("#export-summary-download").click(),
    ]);
    const manifesto = JSON.parse(fs.readFileSync(await resumo.path(), "utf8"));
    assert.equal(manifesto.total_correcoes, 1);
    assert.deepEqual(manifesto.identificadores, [{ correcao_id: "c1", operacao_id: "o1" }]);
    assert.deepEqual(manifesto.operacoes_pendentes_no_navegador, []);
    falhar = true;
    await page.locator("#export-results").click();
    await page.getByText("Exportação não concluída: Leitura incompleta.", { exact: true }).waitFor();
    assert.equal(await page.locator("#export-summary-download").isDisabled(), true);
  } finally { await browser.close(); }
});

async function mockStudents(page) {
  const students = [];
  students.listRequests = 0;
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
    students.listRequests++;
    const params = new URL(route.request().url()).searchParams;
    const term = normalize(params.get("busca") || "");
    const limit = Number(params.get("limite") || 30);
    const cursor = params.get("cursor");
    const matches = students
      .filter((a) => normalize(a.nome).startsWith(term))
      .sort((a, b) => a.nome.localeCompare(b.nome, "pt-BR"));
    const offset = cursor ? matches.findIndex((a) => a.id === cursor) + 1 : 0;
    const page = matches.slice(offset, offset + limit);
    return route.fulfill({
      json: { alunos: page, proximo_cursor: matches.length > offset + limit ? page.at(-1).id : null },
    });
  });
  students.corrections = [];
  const operations = new Map();
  students.commit = (input) => {
    assert.match(input.operacao_id, /^[0-9a-f-]{36}$/);
    assert.match(input.comprovante, /^[0-9a-f]{64}$/);
    assert.equal(Object.keys(input.respostas).length, 50);
    if (operations.has(input.operacao_id)) return operations.get(input.operacao_id);
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
    operations.set(input.operacao_id, record);
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
  await page.route("**/api/alunos/*/correcoes?*", (route) => {
    const params = new URL(route.request().url()).searchParams;
    const limit = Number(params.get("limite") || 30);
    const cursor = params.get("cursor");
    const legacy = params.get("legadas") === "true";
    const matches = students.corrections.filter((c) =>
      route.request().url().includes("/" + c.aluno_id + "/"));
    const offset = cursor ? matches.findIndex((c) => c.id === cursor) + 1 : 0;
    const records = legacy ? [] : matches.slice(offset, offset + limit);
    return route.fulfill({
      json: {
        aluno: students.find((a) =>
          route
            .request()
            .url()
            .includes("/" + a.id + "/"),
        ),
        correcoes: records,
        legadas_por_nome: legacy ? [
          {
            id: "legada",
            avaliacao: "Avaliação antiga",
            resultado: { resumo: { pontuacao: 30, percentual_acertos: 60 } },
            processada_em: "2026-10-30T12:00:00Z",
            situacao: "provisoria",
          },
        ] : [],
        proximo_cursor: !legacy && matches.length > offset + limit ? records.at(-1).id : null,
      },
    });
  });
  return students;
}

test("alunos e histórico carregam páginas sem recarregar coleções", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const students = await mockStudents(page);
    for (let i = 0; i < 65; i++) students.push({
      id: `aluno-${String(i).padStart(4, "0")}`,
      nome: `Aluno ${String(i).padStart(4, "0")}`,
    });
    for (let i = 0; i < 65; i++) students.corrections.push({
      id: `correcao-${i}`, aluno_id: students[0].id,
      avaliacao: "Evento", resultado: { resumo: { pontuacao: 40, percentual_acertos: 80 } },
      processada_em: "2026-11-14T12:00:00Z", situacao: "sem_pendencias",
    });
    await page.route("**/api/avaliacoes", route => route.fulfill({ json: [] }));
    await page.goto(baseURL + "/interface/");
    await page.locator('[data-tab="alunos"]').click();
    await page.waitForFunction(() => document.querySelectorAll("#students-list .evaluation-item").length === 30);
    assert.equal(await page.locator("#students-more").isVisible(), true);
    await page.locator("#students-more").click();
    await page.waitForFunction(() => document.querySelectorAll("#students-list .evaluation-item").length === 60);
    await page.locator("#students-more").click();
    await page.waitForFunction(() => document.querySelectorAll("#students-list .evaluation-item").length === 65);
    assert.equal(await page.locator("#students-more").isHidden(), true);
    await page.locator("#students-list button").first().click();
    await page.waitForFunction(() => document.querySelectorAll("#student-history .history-table tbody tr").length === 30);
    await page.locator("#student-history-more").click();
    await page.waitForFunction(() => document.querySelectorAll("#student-history .history-table tbody tr").length === 60);
    await page.locator("#student-history-more").click();
    await page.waitForFunction(() => document.querySelectorAll("#student-history .history-table tbody tr").length === 65);
    assert.equal(await page.locator("#student-history-more").isHidden(), true);
    await page.locator("#student-history-legacy").click();
    await page.waitForFunction(() => document.querySelectorAll("#student-history .history-table tbody tr").length === 66);
    assert.equal(students.listRequests, 3);
  } finally { await browser.close(); }
});

test("resposta perdida e reinício da página recuperam a mesma operação", async () => {
  const browser = await chromium.launch();
  try {
    for (const commitBeforeAbort of [true, false]) {
      const page = await browser.newPage();
      const students = await mockStudents(page);
      const official = Object.fromEntries(Array.from({ length: 50 }, (_, i) => [String(i + 1), "A"]));
      await page.route("**/api/avaliacoes", route => route.fulfill({ json: [
        { id: "prova-evento", titulo: "Evento", criada_em: "2026-11-14T12:00:00Z" },
      ] }));
      await page.route("**/api/avaliacoes/*/gabarito", route => route.fulfill({ json: { alternativas: official } }));
      const calls = [];
      let committed = null;
      await page.route("**/api/correcoes/salvar", route => {
        const body = route.request().postDataJSON();
        calls.push(body.operacao_id);
        if (calls.length === 1) {
          if (commitBeforeAbort) committed = students.commit(body);
          return route.abort("failed");
        }
        committed = students.commit(body);
        return route.fulfill({ status: 201, json: committed });
      });
      await page.route("**/api/operacoes/correcao/*", route => route.fulfill({ json:
        committed ? { estado: "confirmada", registro: { id: committed.id } } : { estado: "nao_encontrada" },
      }));
      await page.goto(baseURL + "/interface/");
      await page.locator('[data-tab="correcao"]').click();
      await page.locator("#evaluation-select").selectOption("prova-evento");
      await page.locator("#student-name").fill("Aluno fictício");
      await page.locator("#file-input").setInputFiles(path.join(artifacts, "cartao.png"));
      await page.locator("#process-button").click();
      await page.locator("#result-content").waitFor({ state: "visible" });
      await page.locator("#confirm-result").check();
      await page.locator("#save-result").click();
      await page.locator("#recovery-panel").waitFor({ state: "visible" });
      await page.reload();
      await page.locator('[data-tab="correcao"]').click();
      await page.locator("#recovery-panel").waitFor({ state: "visible" });
      await page.getByRole("button", { name: "Consultar estado" }).click();
      if (!commitBeforeAbort) {
        await page.getByRole("button", { name: "Reenviar mesma operação" }).click();
        await page.getByText("Correção confirmada no banco.", { exact: false }).waitFor();
        assert.deepEqual(calls, [calls[0], calls[0]]);
      } else assert.equal(calls.length, 1);
      await page.locator("#recovery-panel").waitFor({ state: "hidden" });
      assert.equal(students.corrections.length, 1);
      await page.close();
    }
  } finally { await browser.close(); }
});

test("revisão tardia não restaura dados após o encerramento da sessão", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    const official = Object.fromEntries(
      Array.from({ length: 50 }, (_, i) => [String(i + 1), "A"]),
    );
    await page.route("**/api/avaliacoes", route => route.fulfill({ json: [
      { id: "avaliacao-visual", titulo: "Teste visual", criada_em: "2026-10-31T12:00:00Z" },
    ] }));
    await page.route("**/api/avaliacoes/*/gabarito", route =>
      route.fulfill({ json: { alternativas: official } }));
    await page.goto(baseURL + "/interface/");
    await page.locator('[data-tab="correcao"]').click();
    await page.locator("#evaluation-select").selectOption("avaliacao-visual");
    await page.locator("#student-name").fill("Aluno Simulado");
    await page.locator("#file-input").setInputFiles(path.join(artifacts, "visual-mista.png"));
    await page.locator("#process-button").click();
    await page.locator('[data-student-question="2"]').waitFor();
    let release, started;
    const pending = new Promise(resolve => { release = resolve; });
    const requested = new Promise(resolve => { started = resolve; });
    let reviewCalls = 0;
    await page.route("**/api/correcoes/recalcular", async route => {
      reviewCalls++;
      if (reviewCalls === 2) {
        started();
        await pending;
      }
      await route.fulfill({ status: 503, json: { detail: "Falha de revisão simulada" } });
    });
    await page.locator('[data-student-question="2"]').selectOption("A");
    await page.getByText("Falha de revisão simulada").waitFor();
    assert.equal(await page.locator("#total-score").textContent(), "1");
    assert.equal(await page.locator('[data-student-question="2"]').inputValue(), "original");
    await page.locator('[data-student-question="2"]').selectOption("A");
    await requested;
    await page.evaluate(async () => {
      const { setApiAccess } = await import("./js/api.mjs");
      setApiAccess(false);
      window.dispatchEvent(new Event("corretor:session-ended"));
    });
    release();
    await page.waitForResponse(response => response.url().endsWith("/api/correcoes/recalcular"));
    assert.equal(await page.locator("#result-content").isVisible(), false);
    assert.equal(await page.locator("#student-answer-grid").count(), 1);
    assert.equal(await page.locator("#student-answer-grid").textContent(), "");
    assert.equal(await page.locator("#total-score").textContent(), "");
    assert.equal(await page.locator("#message").textContent(), "");
    assert.equal(await page.locator("#save-result").isDisabled(), true);
  } finally { await browser.close(); }
});

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
    assert.equal(students.listRequests, 0);

    assert.equal(students.length, 1);
    await page.locator('[data-tab="alunos"]').click();
    await page.waitForFunction(() =>
      document.querySelectorAll("#students-list .evaluation-item").length === 1);
    assert.equal(students.listRequests, 1);
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
      .getByText("Correção não gravada: confirme o aluno e tente novamente.", { exact: true })
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
    // Imagem gerada pelo harness; o nome vem da resposta OCR simulada.
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
    await page.locator("#confirm-photo").click();
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
      navigator.mediaDevices.getUserMedia = async () => {
        await new Promise((resolve) => {
          window.releaseCamera = resolve;
        });
        const canvas = document.createElement('canvas');
        canvas.width = 640;
        canvas.height = 480;
        const context = canvas.getContext('2d');
        context.fillStyle = 'white';
        context.fillRect(0, 0, 640, 480);
        return canvas.captureStream(2);
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
        { polling: 100 },
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

test("permissão lenta pode ser cancelada e retorno à aba exige nova câmera", async () => {
  const browser = await chromium.launch();
  try {
    const page = await browser.newPage();
    await page.route("**/api/avaliacoes", route => route.fulfill({ json: [] }));
    await page.addInitScript(() => {
      window.cameraStops = 0;
      let calls = 0;
      const stream = () => {
        const canvas = document.createElement("canvas");
        canvas.width = 640; canvas.height = 480;
        canvas.getContext("2d").fillRect(0, 0, 640, 480);
        const video = canvas.captureStream(2);
        const track = video.getVideoTracks()[0];
        const original = track.stop.bind(track);
        track.stop = () => { window.cameraStops++; original(); };
        return video;
      };
      navigator.mediaDevices.getUserMedia = () => {
        calls++;
        if (calls === 1) return new Promise(resolve => { window.releaseCamera = () => resolve(stream()); });
        return Promise.resolve(stream());
      };
    });
    await page.goto(baseURL + "/interface/");
    await page.locator("#camera-start").click();
    await page.waitForFunction(() => typeof window.releaseCamera === "function");
    assert.equal(await page.locator("#camera-start").isDisabled(), true);
    assert.equal(await page.locator("#camera-stop").isDisabled(), false);
    await page.locator("#camera-stop").click();
    await page.locator("#camera-start").click();
    await page.waitForFunction(() => !document.getElementById("capture-button").disabled);
    await page.evaluate(() => window.releaseCamera());
    await page.waitForFunction(() => window.cameraStops >= 1);
    assert.equal(await page.locator("#camera-video").evaluate(video =>
      video.srcObject.getVideoTracks()[0].readyState), "live");
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => true });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    assert.equal(await page.locator("#camera-video").evaluate(video => video.srcObject), null);
    await page.evaluate(() => {
      Object.defineProperty(document, "hidden", { configurable: true, get: () => false });
      document.dispatchEvent(new Event("visibilitychange"));
    });
    await page.locator("#camera-start").click();
    await page.waitForFunction(() => !document.getElementById("capture-button").disabled);
    await page.locator("#camera-video").evaluate(video =>
      video.srcObject.getVideoTracks()[0].dispatchEvent(new Event("ended")));
    await page.waitForFunction(() => document.getElementById("message").textContent.startsWith("Câmera desconectada."));
    assert.equal(await page.locator("#camera-video").evaluate(video => video.srcObject), null);
  } finally { await browser.close(); }
});

test("fluxos de avaliações e correções com câmera e API simuladas", async () => {
  assert.ok(
    artifacts,
    "O harness deve criar os arquivos sintéticos temporários.",
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
    // Stream sintético determinístico; o dispositivo virtual do Chromium é instável
    // quando muitos contextos de câmera são criados na mesma suíte.
    await page.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = async () => {
        const canvas = document.createElement("canvas");
        canvas.width = 800;
        canvas.height = 1100;
        const context = canvas.getContext("2d");
        context.fillStyle = "white";
        context.fillRect(0, 0, canvas.width, canvas.height);
        return canvas.captureStream(2);
      };
    });
    const students = await mockStudents(page);
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const evaluations = [],
      saved = [];
    let candidateRequests = 0;
    // Persistência, reconhecimento, análise e correção usam respostas simuladas.
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
    await page.locator("#capture-button").click();
    await page.locator("#capture-preview").waitFor({ state: "visible" });
    await page.locator("#manual-corners .corner-handle").first().waitFor({ state: "visible" });
    assert.equal(await page.locator("#process-button").isDisabled(), true);
    const desktopBefore = await page.locator("#manual-corners-outline polygon").getAttribute("points");
    const handleBox = await page.locator("#manual-corners .corner-handle").first().boundingBox();
    await page.mouse.move(handleBox.x + handleBox.width / 2, handleBox.y + handleBox.height / 2);
    await page.mouse.down();
    await page.mouse.move(handleBox.x + handleBox.width / 2 + 8,
      handleBox.y + handleBox.height / 2 + 8);
    await page.mouse.up();
    assert.notEqual(await page.locator("#manual-corners-outline polygon").getAttribute("points"), desktopBefore);
    await page.locator("#confirm-photo").click();
    assert.equal(await page.locator("#process-button").isEnabled(), true);
    assert.equal(
      await page.locator("#camera-video").evaluate((video) => video.srcObject),
      null,
    );
    assert.match(await page.locator("#message").textContent(), /Foto confirmada/);
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
      await page.evaluate(() => [...document.querySelectorAll('*')]
        .filter(el => el.getBoundingClientRect().right > innerWidth + 1)
        .slice(0, 8).map(el => `${el.tagName}#${el.id}.${el.className}`)),
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
    assert.deepEqual(apiCalls.map(url => new URL(url).pathname), []);
    await failed.close();
  } finally { await browser.close(); }
});

test("save retries reuse operation after response loss", async () => {
  const browser = await chromium.launch({executablePath: process.env.QA_CHROME_PATH, headless: true});
  try {
    const page = await browser.newPage();
    const students = await mockStudents(page);
    await page.route('**/api/avaliacoes', route => route.fulfill({json: [{id: 'retry', titulo: 'Retry', criada_em: '2026-11-01'}]}));
    const official = Object.fromEntries(Array.from({length: 50}, (_,i) => [String(i+1),'A']));
    await page.route('**/api/avaliacoes/*/gabarito', route => route.fulfill({json: {alternativas: official}}));
    const requests = [];
    await page.route('**/api/correcoes/salvar', async route => {
      const input = route.request().postDataJSON();
      requests.push(input);
      const saved = students.commit(input);
      if (requests.length === 1) return route.fulfill({status: 201, contentType: 'application/json', body: '{'});
      return route.fulfill({status: 201, json: saved});
    });
    await page.goto(baseURL + '/interface/');
    await page.locator('[data-tab="correcao"]').click();
    await page.locator('#evaluation-select').selectOption('retry');
    await page.locator('#student-name').fill('Aluno Retry');
    await page.locator('#file-input').setInputFiles(path.join(artifacts, 'cartao.png'));
    await page.locator('#process-button').click();
    await page.locator('#result-content').waitFor({state: 'visible'});
    await page.locator('#confirm-result').check();
    await page.locator('#save-result').click();
    await page.locator('#message.error').waitFor();
    await page.locator('#save-result').click();
    await page.locator('#saved-result').waitFor({state:'visible'});
    assert.equal(requests.length, 2);
    assert.equal(requests[0].operacao_id, requests[1].operacao_id);
    assert.equal(students.length, 1);
    assert.equal(students.corrections.length, 1);
    await browser.close();
  } finally { await browser.close(); }
});
