import test from "node:test";
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { apiUrl, request } from "../js/api.mjs";
import { loadPages, tabFromHash } from "../js/paginas.mjs";
import { authSession, createAuth } from "../js/auth.mjs";

const root = fileURLToPath(new URL("../", import.meta.url));
const read = relative => readFile(path.join(root, relative), "utf8");

async function exactFile(relative) {
  const parts = relative.split(/[\\/]/);
  let current = root;
  for (const part of parts) {
    assert.ok((await readdir(current)).includes(part), `Caminho/capitalização incorreto: ${relative}`);
    current = path.join(current, part);
  }
  await readFile(current);
}

test("HTML, CSS, fontes e imports usam arquivos existentes com capitalização Linux", async () => {
  const html = await read("index.html");
  for (const [, asset] of html.matchAll(/(?:src|href)="([^"]+)"/g)) {
    if (asset === "./" || asset.startsWith("#")) continue;
    assert.ok(!asset.startsWith("/"), "Shell deve funcionar na raiz e em /interface/");
    await exactFile(asset);
  }
  const css = await read("css/style.css");
  for (const [, asset] of css.matchAll(/url\("([^"]+)"\)/g))
    await exactFile(path.posix.normalize("css/" + asset));
  for (const name of (await readdir(path.join(root, "js"))).filter(n => n.endsWith(".mjs"))) {
    for (const [, asset] of (await read("js/" + name)).matchAll(/(?:from\s+|import\s*\()"(\.\.?\/[^"\n]+)"/g))
      await exactFile(path.posix.normalize("js/" + asset));
  }
});

test("fragmentos das três telas carregam todos os slots do shell", async () => {
  const html = await read("index.html");
  const slots = new Map([...html.matchAll(/data-page-slot="([^"]+)"/g)].map(([, name]) => [name, 0]));
  const document = {
    createElement() {
      let source = "";
      return {
        set innerHTML(value) { source = value; },
        content: { querySelectorAll() {
          return [...source.matchAll(/<template data-slot="([^"]+)"/g)].map(([, name]) =>
            ({ dataset: { slot: name }, content: name }));
        } },
      };
    },
    querySelector(selector) {
      const name = selector.match(/="([^"]+)"/)[1];
      return slots.has(name) ? { replaceWith: () => slots.set(name, slots.get(name) + 1) } : null;
    },
    querySelectorAll: () => [...slots.keys()],
  };
  const loaded = [];
  await loadPages({ root: document, fetcher: async url => {
    loaded.push(url);
    return { ok: true, text: () => readFile(url, "utf8") };
  } });
  assert.equal(loaded.length, 4);
  assert.ok([...slots.values()].every(count => count === 1));
  await assert.rejects(() => loadPages({ root: document, fetcher: async () => ({ ok: false }) }), /carregar/);
});

test("links diretos e atualização usam hashes sem exigir fallback de servidor", () => {
  for (const page of ["avaliacoes", "correcao", "alunos"])
    for (const base of ["https://site.example/", "https://site.example/index.html", "http://localhost:8000/interface/"]) {
      const url = new URL(`#${page}`, base);
      assert.equal(tabFromHash(url.hash), page);
      assert.equal(url.pathname, new URL(base).pathname);
    }
  assert.equal(tabFromHash(""), "avaliacoes");
  assert.equal(tabFromHash("#inexistente"), "avaliacoes");
});

test("hospedagem exige API configurada e HTTPS sem mudar o modo local", () => {
  assert.throws(() => apiUrl("/api/alunos", "", "https://site.example/"), /Configure/);
  assert.throws(() => apiUrl("/api/alunos", "http://api.example", "https://site.example/"), /HTTPS/);
  assert.throws(() => apiUrl("/api/alunos", "http://localhost:8000", "https://site.example/"), /HTTPS/);
  assert.equal(apiUrl("/api/alunos", "https://api.example", "https://site.example/"), "https://api.example/api/alunos");
  assert.equal(apiUrl("/api/alunos", "", "http://127.0.0.1:8000/interface/"), "/api/alunos");
  assert.throws(() => apiUrl("/api/../privado", ""), /inválido/);
});

test("falha de rede explica recuperação sem repetir operações", async (t) => {
  let calls = 0;
  t.mock.method(globalThis, "fetch", async () => { calls++; throw new TypeError("Failed to fetch"); });
  await assert.rejects(() => request("/api/correcoes/salvar", { method: "POST" }), /mesma operação/);
  assert.equal(calls, 1);
});

test("cancelamento de captura permanece AbortError", async (t) => {
  const abort = new DOMException("cancelado", "AbortError");
  t.mock.method(globalThis, "fetch", async () => { throw abort; });
  await assert.rejects(() => request("/api/capturas/analisar"), error => error === abort);
});

test("indisponibilidade temporária HTML não desloga nem repete gravação", async (t) => {
  let calls = 0, logouts = 0;
  t.mock.method(authSession, "logout", () => logouts++);
  t.mock.method(globalThis, "fetch", async () => {
    calls++;
    return { ok: false, status: 503, json: async () => { throw new SyntaxError("HTML do proxy"); } };
  });
  await assert.rejects(() => request("/api/avaliacoes"), error => error.status === 503 && /temporariamente/.test(error.message));
  assert.equal(logouts, 0);
  assert.equal(calls, 1);
});

test("401 e 403 sem JSON retornam mensagem explícita e encerram sessão", async (t) => {
  let status = 401, logouts = 0;
  t.mock.method(authSession, "logout", () => logouts++);
  t.mock.method(globalThis, "fetch", async () => ({ ok: false, status, json: async () => null }));
  await assert.rejects(() => request("/api/alunos"), /Entre novamente/);
  status = 403;
  await assert.rejects(() => request("/api/alunos"), /não autorizado/);
  assert.equal(logouts, 2);
});

test("falha de rede no Firebase exibe mensagem sem autenticar", async () => {
  const auth = createAuth({ apiKey: "publica-ficticia", authDomain: "demo.example.test",
    projectId: "demo-corretor", appId: "1:000:web:teste", sdkLoader: async () => ({
      browserLocalPersistence: { type: "LOCAL" }, initializeApp: () => ({}),
      initializeAuth: () => ({ currentUser: null, authStateReady: async () => {} }),
      signOut: async () => {}, signInWithEmailAndPassword: async () => {
        throw { code: "auth/network-request-failed" };
      },
    }) });
  await assert.rejects(() => auth.login("teste@example.test", "ficticia"), /serviço de login/);
  assert.equal(await auth.getToken(), null);
});

test("Vercel usa saída estática, preserva câmera e não encaminha API", async () => {
  const config = JSON.parse(await read("vercel.json"));
  assert.equal(config.framework, null);
  assert.equal(config.outputDirectory, ".");
  assert.equal(config.buildCommand, "");
  assert.equal(config.installCommand, "");
  assert.equal(config.rewrites, undefined);
  const headers = Object.fromEntries(config.headers[0].headers.map(item => [item.key, item.value]));
  assert.equal(headers["Permissions-Policy"], "camera=(self), microphone=()");
  assert.match(headers["Cache-Control"], /must-revalidate/);
  const ignores = await read(".vercelignore");
  for (const name of ["tests/", ".env", ".secrets/", "js/script.js"]) assert.ok(ignores.split(/\r?\n/).includes(name));
  const publicConfig = await read("js/config.mjs");
  assert.deepEqual([...publicConfig.matchAll(/export const (\w+)/g)].map(([, name]) => name),
    ["API_BASE_URL", "FIREBASE_API_KEY", "FIREBASE_AUTH_DOMAIN", "FIREBASE_PROJECT_ID", "FIREBASE_APP_ID"]);
  assert.doesNotMatch(publicConfig, /BEGIN PRIVATE KEY|private_key\s*[:=]|refreshToken\s*[:=]/);
});
