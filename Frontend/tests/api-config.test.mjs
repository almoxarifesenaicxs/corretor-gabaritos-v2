import test from "node:test";
import assert from "node:assert/strict";
import { apiUrl, request, jsonPost, upload } from "../js/api.mjs";

test("API usa mesma origem por padrão e origem explícita em outros ambientes", () => {
  const path = "/api/alunos?busca=Ana%20Silva";
  assert.equal(apiUrl(path), path);
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
  assert.equal(calls[0][0], "/api/alunos");
  assert.equal(calls[0][1].signal, signal);
  assert.equal(calls[1][1].headers.get("Content-Type"), "application/json");
  assert.deepEqual(JSON.parse(calls[1][1].body), { titulo: "Teste" });
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
    assert.equal(url, "/api/correcoes/processar");
    assert.equal(options.method, "POST");
    assert.equal(options.headers.has("Content-Type"), false);
    assert.equal(options.signal, signal);
    assert.ok(options.body instanceof FormData);
    assert.equal(options.body.get("arquivo").name, `cartao.${["pdf", "jpg", "png"][i]}`);
    assert.equal(options.body.get("gabarito"), '{"1":"A"}');
    assert.equal(options.body.get("captura"), "false");
  }
});
