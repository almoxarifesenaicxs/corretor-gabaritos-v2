import test from "node:test";
import assert from "node:assert/strict";
import { requireLogin } from "../js/login.mjs";
import { authSession } from "../js/auth.mjs";

function screen(t) {
  const events = {};
  const button = { disabled: false };
  const form = { elements: { email: { value: "teste@example.test" }, password: { value: "ficticia" } },
    querySelector: () => button, addEventListener: (name, fn) => { events[name] = fn; } };
  const elements = { "login-form": form, "login-panel": { hidden: false },
    "login-message": { textContent: "" }, logout: { hidden: true, addEventListener() {} } };
  const body = { inert: true, classList: { remove() {} } };
  const before = globalThis.document;
  globalThis.document = { body, getElementById: id => elements[id] };
  t.after(() => { globalThis.document = before; });
  t.mock.method(authSession, "login", async () => "token-simulado");
  t.mock.method(authSession, "getToken", async () => "token-simulado");
  t.mock.method(authSession, "logout", () => {});
  t.mock.method(authSession, "onLogout", () => {});
  return { elements, form, button, body, submit: () => events.submit({ preventDefault() {} }) };
}

test("login só libera interface após autorização do backend", async (t) => {
  const ui = screen(t);
  t.mock.method(globalThis, "fetch", async (url, options) => {
    assert.equal(url, "/api/auth/me");
    assert.equal(options.headers.get("Authorization"), "Bearer token-simulado");
    assert.equal(ui.elements["login-panel"].hidden, false);
    return { ok: true, status: 200, json: async () => ({ uid: "admin-teste" }) };
  });
  const ready = requireLogin();
  assert.equal(ui.body.inert, false);
  await ui.submit();
  await ready;
  assert.equal(ui.elements["login-panel"].hidden, true);
  assert.equal(ui.form.elements.password.value, "");
  assert.equal(ui.elements.logout.hidden, false);
});

test("login sem autorização mantém painel e limpa senha", async (t) => {
  const ui = screen(t);
  t.mock.method(globalThis, "fetch", async () => ({ ok: false, status: 403,
    json: async () => ({ detail: "Usuário sem autorização administrativa." }) }));
  let ready = false;
  requireLogin().then(() => { ready = true; });
  await ui.submit();
  assert.equal(ready, false);
  assert.equal(ui.elements["login-panel"].hidden, false);
  assert.match(ui.elements["login-message"].textContent, /sem autorização/);
  assert.equal(ui.form.elements.password.value, "");
  assert.equal(ui.button.disabled, false);
});
