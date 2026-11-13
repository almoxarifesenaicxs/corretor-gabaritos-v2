import test from "node:test";
import assert from "node:assert/strict";
import { apiUrl, request, requestBinary, jsonPost, upload } from "../js/api.mjs";
import { authSession } from "../js/auth.mjs";

test.beforeEach(t => t.mock.method(authSession, "getToken", async () => "token-simulado"));

const renderOrigin = "https://corretor-gabaritos-8yal.onrender.com";

test("configuração usa loopback no navegador e Render na Vercel ou no Node", async () => {
  const anterior = Object.getOwnPropertyDescriptor(globalThis, "location");
  try {
    for (const [hostname, esperado] of [
      ["localhost", ""], ["127.0.0.1", ""],
      ["corretor.vercel.app", renderOrigin], [undefined, renderOrigin],
    ]) {
      if (hostname === undefined) delete globalThis.location;
      else Object.defineProperty(globalThis, "location", {
        value: { hostname }, configurable: true,
      });
      const modulo = new URL("../js/config.mjs", import.meta.url);
      modulo.searchParams.set("ambiente", hostname ?? "node");
      assert.equal((await import(modulo.href)).API_BASE_URL, esperado);
    }
  } finally {
    if (anterior) Object.defineProperty(globalThis, "location", anterior);
    else delete globalThis.location;
  }
});

test("API usa a origem pública por padrão e permite base local explícita", () => {
  const path = "/api/alunos?busca=Ana%20Silva";
  assert.equal(apiUrl(path), renderOrigin + path);
  assert.equal(apiUrl("/api/health"), renderOrigin + "/api/health");
  assert.equal(apiUrl(path, ""), path);
  assert.equal(apiUrl(path, "http://127.0.0.1:8000/"), "http://127.0.0.1:8000" + path);
  assert.equal(apiUrl(path, "https://api.example"), "https://api.example" + path);
});

test("configuração rejeita credenciais, caminhos e protocolos inadequados", () => {
  for (const base of ["/backend", "ftp://api.example", "https://api.example/api",
    "https://user:secret@api.example", "https://api.example?token=x", "https://api.example#x"])
    assert.throws(() => apiUrl("/api/alunos", base));
  for (const path of ["https://outro.example/api/alunos", "//outro.example/api/alunos", "/interface/", "/api/\\outro"])
    assert.throws(() => apiUrl(path));
});

test("request e JSON mantêm o contrato e o cancelamento", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (...args) => {
    calls.push(args);
    return { ok: true, json: async () => ({ ok: true }) };
  });
  const signal = new AbortController().signal;
  await request("/api/alunos", { signal });
  await jsonPost("/api/avaliacoes", { titulo: "Teste" });
  assert.equal(calls[0][0], renderOrigin + "/api/alunos");
  assert.equal(calls[0][1].signal, signal);
  assert.equal(calls[1][1].headers.get("Content-Type"), "application/json");
  assert.equal(calls[1][0], renderOrigin + "/api/avaliacoes");
  assert.deepEqual(JSON.parse(calls[1][1].body), { titulo: "Teste" });
});

test("requisições protegidas substituem Authorization pelo token do Firebase", async (t) => {
  let headers;
  t.mock.method(globalThis, "fetch", async (_url, options) => {
    headers = options.headers;
    return { ok: true, json: async () => [] };
  });
  await request("/api/avaliacoes", { headers: { Authorization: "Bearer descartado" } });
  assert.equal(headers.get("Authorization"), "Bearer token-simulado");
});

test("uploads PDF JPG PNG preservam FormData sem fixar boundary", async (t) => {
  const calls = [];
  t.mock.method(globalThis, "fetch", async (...args) => {
    calls.push(args);
    return { ok: true, json: async () => ({}) };
  });
  const signal = new AbortController().signal;
  for (const ext of ["pdf", "jpg", "png"])
    await upload("/api/correcoes/processar", new File(["conteudo"], `cartao.${ext}`),
      { gabarito: '{"1":"A"}', captura: false }, signal);
  for (const [i, [url, options]] of calls.entries()) {
    assert.equal(url, renderOrigin + "/api/correcoes/processar");
    assert.equal(options.method, "POST");
    assert.equal(options.headers.has("Content-Type"), false);
    assert.equal(options.signal, signal);
    assert.ok(options.body instanceof FormData);
    assert.equal(options.body.get("arquivo").name, `cartao.${["pdf", "jpg", "png"][i]}`);
    assert.equal(options.body.get("gabarito"), '{"1":"A"}');
    assert.equal(options.body.get("captura"), "false");
  }
});

test("download de imagem ZIP envia a credencial temporária somente no cabeçalho", async (t) => {
  let url, headers;
  t.mock.method(globalThis, "fetch", async (target, options) => {
    url = target;
    headers = options.headers;
    return { ok: true, status: 200 };
  });
  const token = "x".repeat(43);
  await requestBinary("/api/lotes/" + "a".repeat(32) + "/imagens/0",
    { headers: { "X-Lote-Token": token } });
  assert.equal(headers.get("X-Lote-Token"), token);
  assert.equal(url.includes(token), false);
});
