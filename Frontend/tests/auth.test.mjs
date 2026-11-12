import test from "node:test";
import assert from "node:assert/strict";
import { createAuth, authSession } from "../js/auth.mjs";
import { request, upload, setApiAccess } from "../js/api.mjs";

test("configuração ausente não carrega o Firebase", async () => {
  const auth = createAuth({ sdkLoader: () => { throw new Error("Não deve carregar SDK"); } });
  await assert.rejects(() => auth.login("a", "b"), /Configure/);
  assert.equal(await auth.getToken(), null);
});

test("Bearer acompanha JSON e multipart, sem alterar boundary", async (t) => {
  const calls = [];
  t.mock.method(authSession, "getToken", async () => "token-simulado");
  t.mock.method(globalThis, "fetch", async (url, options) => {
    calls.push(options);
    return { ok: true, status: 200, json: async () => ({}) };
  });
  await request("/api/alunos");
  await upload("/api/correcoes/processar", new File(["imagem"], "cartao.png"));
  for (const options of calls) {
    assert.equal(options.headers.get("Authorization"), "Bearer token-simulado");
    assert.equal(options.redirect, "error");
  }
  assert.equal(calls[1].headers.has("Content-Type"), false);
  assert.ok(calls[1].body instanceof FormData);
});

test("401 e 403 encerram sessão sem repetir operações", async (t) => {
  let ended = 0, calls = 0;
  t.mock.method(authSession, "getToken", async () => "token-simulado");
  t.mock.method(authSession, "logout", () => ended++);
  t.mock.method(globalThis, "fetch", async () => ({ ok: false, status: ++calls === 1 ? 401 : 403,
    json: async () => ({ detail: "Acesso negado" }) }));
  await assert.rejects(() => request("/api/avaliacoes"), /negado/);
  await assert.rejects(() => request("/api/avaliacoes"), /negado/);
  assert.equal(ended, 2);
  assert.equal(calls, 2);
});

for (const status of [401, 403]) {
  for (const [scenario, reopen] of [
    ["logout", false],
    ["troca de usuário", true],
    ["revalidação", false],
    ["nova sessão autorizada", true],
  ]) {
    test(`resposta ${status} antiga após ${scenario} não encerra a sessão atual`, async (t) => {
      let release, started;
      const pending = new Promise(resolve => { release = resolve; });
      const requested = new Promise(resolve => { started = resolve; });
      let logouts = 0;
      t.mock.method(authSession, "getToken", async () => "token-simulado");
      t.mock.method(authSession, "logout", async () => { logouts++; });
      t.mock.method(globalThis, "fetch", async () => {
        started();
        await pending;
        return { ok: false, status, json: async () => ({ detail: "Erro da sessão anterior" }) };
      });
      setApiAccess(true);
      const oldRequest = request("/api/avaliacoes");
      await requested;
      setApiAccess(false);
      if (reopen) setApiAccess(true);
      release();
      await assert.rejects(oldRequest, /sessão precisa ser validada/);
      assert.equal(logouts, 0);
    });
  }
}

test("falha de rede antiga não exibe erro da requisição anterior", async (t) => {
  let rejectFetch, started;
  const requested = new Promise(resolve => { started = resolve; });
  t.mock.method(authSession, "getToken", async () => "token-simulado");
  t.mock.method(globalThis, "fetch", () => {
    started();
    return new Promise((_, reject) => { rejectFetch = reject; });
  });
  setApiAccess(true);
  const oldRequest = request("/api/avaliacoes");
  await requested;
  setApiAccess(false);
  setApiAccess(true);
  rejectFetch(new Error("Detalhe antigo"));
  await assert.rejects(oldRequest, /sessão precisa ser validada/);
});
