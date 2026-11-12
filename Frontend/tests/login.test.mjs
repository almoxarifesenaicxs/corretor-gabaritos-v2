import test from "node:test";
import assert from "node:assert/strict";
import { requireLogin } from "../js/login.mjs";
import { request } from "../js/api.mjs";
import { authSession } from "../js/auth.mjs";

function deferred() {
  let resolve;
  const promise = new Promise(yes => { resolve = yes; });
  return { promise, resolve };
}

function screen(t, restore = async () => null) {
  const events = {}, callbacks = {};
  const button = { disabled: false };
  const form = { hidden: true,
    elements: { email: { value: "teste@example.test" }, password: { value: "ficticia" } },
    querySelector: () => button, addEventListener: (name, fn) => { events[name] = fn; } };
  const elements = {
    "login-form": form, "login-panel": { hidden: false },
    "login-message": { textContent: "" }, "session-wait": { hidden: false },
    "session-status": { textContent: "" }, "session-retry": { hidden: true,
      addEventListener: (name, fn) => { events[`retry-${name}`] = fn; } },
    logout: { hidden: true, addEventListener: (name, fn) => { events[`logout-${name}`] = fn; } },
  };
  const classes = new Set(["login-required"]);
  const body = { inert: true, classList: {
    add: name => classes.add(name), remove: name => classes.delete(name),
    contains: name => classes.has(name),
  } };
  const previousDocument = globalThis.document;
  const previousLocation = globalThis.location;
  let reloads = 0;
  globalThis.document = { body, hidden: false, getElementById: id => elements[id],
    addEventListener: (name, fn) => { events[`document-${name}`] = fn; } };
  const previousWindow = globalThis.window;
  globalThis.window = { addEventListener: (name, fn) => { events[`window-${name}`] = fn; },
    dispatchEvent: event => { events[`window-${event.type}`]?.(event); } };
  globalThis.location = { reload: () => { reloads++; } };
  t.after(() => { globalThis.document = previousDocument; globalThis.location = previousLocation;
    globalThis.window = previousWindow; });
  t.mock.method(authSession, "restore", restore);
  t.mock.method(authSession, "login", async () => "token-simulado");
  t.mock.method(authSession, "getToken", async () => "token-simulado");
  t.mock.method(authSession, "getUid", async () => "admin-teste");
  t.mock.method(authSession, "observeIdentity", async fn => { callbacks.identity = fn; return () => {}; });
  t.mock.method(authSession, "onBlocked", fn => { callbacks.blocked = fn; });
  t.mock.method(authSession, "onLogout", fn => { callbacks.logout = fn; });
  t.mock.method(authSession, "onLogoutFailure", fn => { callbacks.failure = fn; });
  t.mock.method(authSession, "logout", async () => {
    callbacks.blocked?.(); callbacks.logout?.(); return true;
  });
  return { elements, form, button, body, callbacks,
    reloads: () => reloads,
    submit: () => events.submit({ preventDefault() {} }),
    retry: () => events["retry-click"](),
    logout: () => events["logout-click"](),
    hide: () => { document.hidden = true; events["document-visibilitychange"](); },
    show: () => { document.hidden = false; events["document-visibilitychange"](); },
  };
}

const ok = () => ({ ok: true, status: 200, json: async () => ({ uid: "admin-teste" }) });
const response = status => ({ ok: false, status, json: async () => ({ detail: "Acesso negado simulado." }) });

test("primeiro acesso mantém dashboard oculto e login só abre após autorização", async t => {
  const ui = screen(t);
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "https://corretor-gabaritos-8yal.onrender.com/api/auth/me");
    assert.equal(options.headers.get("Authorization"), "Bearer token-simulado");
    assert.equal(ui.body.classList.contains("login-required"), true);
    return ok();
  });
  const ready = requireLogin();
  await Promise.resolve();
  assert.equal(ui.form.hidden, false);
  assert.strictEqual(requireLogin(), ready);
  await ui.submit();
  await ready;
  assert.equal(ui.elements["login-panel"].hidden, true);
  assert.equal(ui.form.elements.password.value, "");
  assert.equal(ui.elements.logout.hidden, false);
});

test("restauração aguarda Firebase e autorização antes de expor dados", async t => {
  const identity = deferred(), authorization = deferred();
  const ui = screen(t, () => identity.promise);
  t.mock.method(globalThis, "fetch", async () => authorization.promise);
  const ready = requireLogin();
  assert.equal(ui.form.hidden, true);
  assert.equal(ui.body.classList.contains("login-required"), true);
  identity.resolve("token-simulado");
  await Promise.resolve(); await Promise.resolve();
  assert.equal(ui.elements["login-panel"].hidden, false);
  assert.equal(ui.body.classList.contains("login-required"), true);
  authorization.resolve(ok());
  await ready;
  assert.equal(ui.elements["login-panel"].hidden, true);
});

for (const status of [401, 403]) {
  test(`sessão restaurada rejeitada por ${status} volta ao login`, async t => {
    const ui = screen(t, async () => "token-simulado");
    t.mock.method(globalThis, "fetch", async () => response(status));
    let opened = false;
    requireLogin().then(() => { opened = true; });
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(opened, false);
    assert.equal(ui.form.hidden, false);
    assert.equal(ui.elements["login-panel"].hidden, false);
    assert.match(ui.elements["login-message"].textContent, status === 401 ? /expirada/ : /negado/);
    assert.equal(ui.body.classList.contains("login-required"), true);
  });
}

test("503 mantém a sessão bloqueada e permite nova tentativa", async t => {
  const ui = screen(t, async () => "token-simulado");
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => ++calls === 1 ? response(503) : ok());
  const ready = requireLogin();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.elements["session-retry"].hidden, false);
  assert.equal(ui.body.classList.contains("login-required"), true);
  assert.equal(authSession.logout.mock.callCount(), 0);
  ui.retry();
  await ready;
  assert.equal(calls, 2);
  assert.equal(ui.elements["login-panel"].hidden, true);
});

test("logout aguarda limpeza da persistência antes de recarregar", async t => {
  const ui = screen(t);
  t.mock.method(globalThis, "fetch", async () => ok());
  const done = deferred();
  t.mock.method(authSession, "logout", async () => {
    ui.callbacks.blocked();
    await done.promise;
    ui.callbacks.logout();
    return true;
  });
  const ready = requireLogin();
  await Promise.resolve();
  await ui.submit();
  await ready;
  const pending = ui.logout();
  assert.equal(ui.body.classList.contains("login-required"), true);
  assert.equal(ui.reloads(), 0);
  done.resolve();
  await pending;
  assert.equal(ui.reloads(), 1);
});

test("falha ao encerrar sessão mantém dashboard oculto e permite repetir", async t => {
  const ui = screen(t);
  t.mock.method(globalThis, "fetch", async () => ok());
  t.mock.method(authSession, "logout", async () => {
    ui.callbacks.blocked();
    ui.callbacks.failure();
    return false;
  });
  const ready = requireLogin();
  await Promise.resolve();
  await ui.submit();
  await ready;
  await ui.logout();
  assert.equal(ui.body.classList.contains("login-required"), true);
  assert.equal(ui.elements["login-panel"].hidden, false);
  assert.equal(ui.elements["session-retry"].hidden, false);
  assert.equal(ui.reloads(), 0);
});

test("retorno à aba bloqueia dados e operações até a revalidação terminar", async t => {
  const pending = deferred();
  const ui = screen(t, async () => "token-simulado");
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => ++calls === 1 ? ok() : pending.promise);
  await requireLogin();
  ui.hide(); ui.show();
  assert.equal(ui.body.classList.contains("login-required"), true);
  assert.equal(ui.elements["login-panel"].hidden, false);
  await assert.rejects(() => request("/api/avaliacoes"), /precisa ser validada/);
  pending.resolve(ok());
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.elements["login-panel"].hidden, true);
  assert.equal(ui.body.inert, false);
  assert.equal(calls, 2);
});

test("troca de conta e logout externo bloqueiam a aba sem expor dados", async t => {
  const ui = screen(t, async () => "token-simulado");
  t.mock.method(globalThis, "fetch", async () => ok());
  await requireLogin();
  ui.callbacks.identity("outro-uid");
  assert.equal(ui.body.classList.contains("login-required"), true);
  assert.equal(ui.reloads(), 1);
  await assert.rejects(() => request("/api/avaliacoes"), /precisa ser validada/);
  ui.callbacks.identity(null);
  assert.equal(ui.reloads(), 1);
});

for (const status of [401, 403]) {
  test(`revalidação ${status} encerra a sessão sem reabrir o dashboard`, async t => {
    const ui = screen(t, async () => "token-simulado");
    let calls = 0;
    t.mock.method(globalThis, "fetch", async () => ++calls === 1 ? ok() : response(status));
    await requireLogin();
    ui.hide(); ui.show();
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(ui.reloads(), 1);
    assert.equal(ui.body.classList.contains("login-required"), true);
    assert.equal(ui.elements["login-panel"].hidden, false);
  });
}

test("503 na revalidação preserva sessão e nova tentativa autoriza", async t => {
  const ui = screen(t, async () => "token-simulado");
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => ++calls === 2 ? response(503) : ok());
  await requireLogin();
  ui.hide(); ui.show();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.elements["session-retry"].hidden, false);
  assert.equal(ui.body.classList.contains("login-required"), true);
  assert.equal(authSession.logout.mock.callCount(), 0);
  ui.retry();
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.elements["login-panel"].hidden, true);
  assert.equal(calls, 3);
});

test("logout concorrente invalida resposta atrasada de revalidação", async t => {
  const pending = deferred();
  const ui = screen(t, async () => "token-simulado");
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => ++calls === 1 ? ok() : pending.promise);
  await requireLogin();
  ui.hide(); ui.show();
  ui.callbacks.blocked();
  ui.callbacks.logout();
  pending.resolve(ok());
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.reloads(), 1);
  assert.equal(ui.body.classList.contains("login-required"), true);
});

test("resposta administrativa iniciada antes do bloqueio é descartada", async t => {
  const pending = deferred();
  const ui = screen(t, async () => "token-simulado");
  t.mock.method(globalThis, "fetch", async url =>
    url.endsWith("/api/auth/me") ? ok() : pending.promise);
  await requireLogin();
  const operation = request("/api/avaliacoes");
  await new Promise(resolve => setImmediate(resolve));
  ui.hide(); ui.show();
  pending.resolve({ ok: true, status: 200, json: async () => [{ id: "antigo" }] });
  await assert.rejects(() => operation, /precisa ser validada/);
});

test("troca de conta durante revalidação não reaproveita resposta da conta anterior", async t => {
  const pending = deferred();
  const ui = screen(t, async () => "token-simulado");
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => ++calls === 1 ? ok() : pending.promise);
  await requireLogin();
  ui.hide(); ui.show();
  ui.callbacks.identity("outro-uid");
  pending.resolve(ok());
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(ui.reloads(), 1);
  assert.equal(ui.body.classList.contains("login-required"), true);
  assert.equal(ui.elements["login-panel"].hidden, false);
});

test("falha ao instalar observador não libera a interface", async t => {
  const ui = screen(t, async () => "token-simulado");
  t.mock.method(authSession, "observeIdentity", async () => { throw new Error("SDK indisponível"); });
  t.mock.method(globalThis, "fetch", async () => { throw new Error("Não deve consultar a API"); });
  let opened = false;
  requireLogin().then(() => { opened = true; });
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(opened, false);
  assert.equal(ui.body.classList.contains("login-required"), true);
  assert.equal(ui.elements["session-retry"].hidden, false);
  assert.equal(globalThis.fetch.mock.callCount(), 0);
});
