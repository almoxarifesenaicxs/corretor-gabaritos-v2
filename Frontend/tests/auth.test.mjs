import test from "node:test";
import assert from "node:assert/strict";
import { createAuth, authSession } from "../js/auth.mjs";
import { request, upload } from "../js/api.mjs";

const loginData = { idToken: "token-simulado", refreshToken: "refresh-simulado", expiresIn: "3600" };
test("login usa Firebase REST e renova token apenas em memória", async () => {
  let clock = 0;
  const calls = [];
  const auth = createAuth({ apiKey: "chave-publica-teste", now: () => clock, fetcher: async (url, options) => {
    calls.push([url, options]);
    return { ok: true, json: async () => calls.length === 1 ? loginData :
      { id_token: "renovado", refresh_token: "refresh-novo", expires_in: "3600" } };
  } });
  assert.equal(await auth.getToken(), null);
  await auth.login("teste@example.test", "senha-ficticia");
  assert.equal(await auth.getToken(), "token-simulado");
  assert.match(calls[0][0], /^https:\/\/identitytoolkit.googleapis.com/);
  assert.equal(JSON.parse(calls[0][1].body).returnSecureToken, true);
  clock = 3600000;
  assert.deepEqual(await Promise.all([auth.getToken(), auth.getToken()]), ["renovado", "renovado"]);
  assert.equal(calls.length, 2);
  auth.logout();
  assert.equal(await auth.getToken(), null);
});

test("falha de login e renovação não preservam sessão", async () => {
  let fail = false;
  const auth = createAuth({ apiKey: "teste", fetcher: async () => ({ ok: !fail,
    json: async () => ({ ...loginData, expiresIn: "1" }) }) });
  await auth.login("teste@example.test", "ficticia");
  fail = true;
  await assert.rejects(() => auth.getToken());
  assert.equal(await auth.getToken(), null);
  await assert.rejects(() => auth.login("teste@example.test", "ficticia"));
  assert.equal(await auth.getToken(), null);
  await assert.rejects(() => createAuth({ apiKey: "" }).login("a", "b"), /Configure/);
});

test("logout durante login impede restaurar sessão", async () => {
  let finish;
  const auth = createAuth({ apiKey: "teste", fetcher: () => new Promise(resolve => { finish = resolve; }) });
  const pending = auth.login("teste@example.test", "ficticia");
  auth.logout();
  finish({ ok: true, json: async () => loginData });
  await assert.rejects(() => pending, /cancelado/);
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
