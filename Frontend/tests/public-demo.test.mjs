import test from "node:test";
import assert from "node:assert/strict";

test("configuração pública compartilha registros sem Firebase e preserva loopback local", async () => {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "location");
  try {
    for (const [host, expected] of [
      ["corretor-gabaritos-v2-frontend.vercel.app", true],
      ["127.0.0.1", false], ["localhost", false],
    ]) {
      Object.defineProperty(globalThis, "location", { value: { hostname: host }, configurable: true });
      const module = new URL("../js/config.mjs", import.meta.url);
      module.searchParams.set("host", host);
      const config = await import(module.href);
      assert.equal(config.PUBLIC_OPEN, false);
      assert.equal(config.PUBLIC_SHARED, expected);
      assert.equal(config.PUBLIC_DEMO, false);
      assert.equal(config.AUTH_REQUIRED, false);
      assert.equal(config.API_BASE_URL, expected ? "https://corretor-gabaritos-8yal.onrender.com" : "");
    }
  } finally {
    if (previous) Object.defineProperty(globalThis, "location", previous);
    else delete globalThis.location;
  }
});
