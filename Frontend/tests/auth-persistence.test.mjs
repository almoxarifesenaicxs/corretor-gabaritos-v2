import test from "node:test";
import assert from "node:assert/strict";
import { createAuth, AuthSessionError } from "../js/auth.mjs";

const config = { apiKey: "chave-publica-ficticia", authDomain: "demo.example.test",
  projectId: "demo-corretor", appId: "1:000:web:teste" };

function fixture(store = { user: null }) {
  const state = { tokenError: null, nextToken: null, signInError: null, pendingSignIn: null,
    loaderError: null, persistence: null, forceRefresh: [], signOuts: 0, signInStarted: false,
    listeners: new Set() };
  const sdk = {
    browserLocalPersistence: { type: "LOCAL" },
    initializeApp(options) { assert.deepEqual(options, config); return { options }; },
    initializeAuth(_app, { persistence }) {
      state.persistence = persistence;
      return { currentUser: store.user, authStateReady: async () => {} };
    },
    onAuthStateChanged(auth, callback) {
      state.listeners.add(callback);
      queueMicrotask(() => callback(auth.currentUser));
      return () => state.listeners.delete(callback);
    },
    async signInWithEmailAndPassword(auth) {
      state.signInStarted = true;
      if (state.pendingSignIn) await state.pendingSignIn;
      if (state.signInError) throw state.signInError;
      store.user = { uid: "admin-teste", token: "token-inicial" };
      auth.currentUser = store.user;
      for (const callback of state.listeners) callback(store.user);
      return { user: store.user };
    },
    async getIdToken(user, force = false) {
      state.forceRefresh.push(force);
      if (state.tokenError) throw state.tokenError;
      if (state.nextToken) user.token = state.nextToken;
      return user.token;
    },
    async signOut(auth) {
      state.signOuts++;
      store.user = null;
      auth.currentUser = null;
      for (const callback of state.listeners) callback(null);
    },
  };
  const sdkLoader = async () => {
    if (state.loaderError) throw state.loaderError;
    return sdk;
  };
  return { store, state, sdkLoader, create: () => createAuth({ ...config, sdkLoader }) };
}

test("login usa persistência LOCAL e sessão pode ser restaurada em nova instância", async () => {
  const mock = fixture();
  const first = mock.create();
  assert.equal(await first.restore(), null);
  assert.equal(await first.login("admin@example.test", "senha-ficticia"), "token-inicial");
  assert.equal(mock.state.persistence.type, "LOCAL");
  const nextVisit = mock.create();
  assert.equal(await nextVisit.restore(), "token-inicial");
  assert.equal(mock.state.forceRefresh.at(-1), true);
  assert.equal(await nextVisit.getToken(), "token-inicial");
  assert.equal(mock.state.forceRefresh.at(-1), false);
});

test("SDK renova token e logout limpa a sessão antes de avisar a interface", async () => {
  const mock = fixture();
  const auth = mock.create();
  await auth.login("admin@example.test", "senha-ficticia");
  mock.state.nextToken = "token-renovado";
  assert.equal(await auth.getToken(), "token-renovado");
  let notified = 0;
  auth.onLogout(() => { assert.equal(mock.store.user, null); notified++; });
  assert.equal(await auth.logout(), true);
  assert.equal(notified, 1);
  assert.equal(await auth.getToken(), null);
  assert.equal(await mock.create().restore(), null);
});

test("token inválido na restauração encerra sessão; falha de rede preserva tentativa futura", async () => {
  const mock = fixture({ user: { token: "token-antigo" } });
  const auth = mock.create();
  mock.state.tokenError = { code: "auth/network-request-failed" };
  await assert.rejects(() => auth.restore(), error => error.reason === "network");
  assert.ok(mock.store.user);
  mock.state.tokenError = { code: "auth/user-token-expired" };
  await assert.rejects(() => auth.restore(), error => error.reason === "invalid-session");
  assert.equal(mock.store.user, null);
  assert.equal(await mock.create().restore(), null);
});

test("credenciais incorretas, serviço indisponível e configuração ausente são distintos", async () => {
  const mock = fixture();
  const auth = mock.create();
  mock.state.loaderError = new TypeError("offline");
  await assert.rejects(() => auth.restore(), error => error.reason === "unavailable");
  mock.state.loaderError = null;
  assert.equal(await auth.restore(), null);
  mock.state.signInError = { code: "auth/invalid-credential" };
  await assert.rejects(() => auth.login("a", "b"), error => error.reason === "credentials");
  await assert.rejects(() => createAuth({ apiKey: "", authDomain: "", projectId: "", appId: "",
    sdkLoader: mock.sdkLoader }).restore(),
    error => error instanceof AuthSessionError && error.reason === "configuration");
});

test("logout durante login pendente não deixa sessão persistida", async () => {
  const mock = fixture();
  let finish;
  mock.state.pendingSignIn = new Promise(resolve => { finish = resolve; });
  const auth = mock.create();
  const pending = auth.login("admin@example.test", "senha-ficticia");
  for (let i = 0; i < 10 && !mock.state.signInStarted; i++) await Promise.resolve();
  assert.equal(mock.state.signInStarted, true);
  const logout = auth.logout();
  finish();
  await assert.rejects(() => pending, error => error.reason === "cancelled");
  assert.equal(await logout, true);
  assert.equal(mock.store.user, null);
  assert.equal(await mock.create().restore(), null);
});

test("observador do SDK informa identidade sem expor token", async () => {
  const mock = fixture();
  const auth = mock.create();
  const identities = [];
  const unsubscribe = await auth.observeIdentity(uid => identities.push(uid));
  await Promise.resolve();
  assert.deepEqual(identities, [null]);
  await auth.login("admin@example.test", "senha-ficticia");
  assert.equal(await auth.getUid(), "admin-teste");
  assert.equal(identities.at(-1), "admin-teste");
  await auth.logout();
  assert.equal(identities.at(-1), null);
  unsubscribe();
  assert.equal(mock.state.listeners.size, 0);
});
