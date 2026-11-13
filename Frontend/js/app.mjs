import { loadPages } from "./paginas.mjs";
import { requireLogin } from "./login.mjs";
import * as runtimeConfig from "./config.mjs";
const { PUBLIC_DEMO, PUBLIC_OPEN } = runtimeConfig;
const PUBLIC_SHARED = runtimeConfig.PUBLIC_SHARED === true;
import { initializePublicSession, clearPublicSession } from "./public-session.mjs";

const navigation = [...document.querySelectorAll("[data-tab]")];
navigation.forEach((button) => {
  button.disabled = true;
});
try {
  if (PUBLIC_OPEN) {
    document.getElementById("session-status").textContent = "Preparando seu espaço de resultados…";
    await initializePublicSession();
  }
  document.body.inert = false;
  await requireLogin();
  await loadPages();
  if (PUBLIC_DEMO) {
    document.body.classList.add("public-demo");
    document.getElementById("demo-banner").hidden = false;
  }
  if (PUBLIC_OPEN || PUBLIC_SHARED) {
    if (PUBLIC_OPEN) document.getElementById("public-banner").textContent =
      "Sessão anônima: seus resultados ficam separados por navegador. Exporte o CSV regularmente; perder a sessão impede recuperá-los.";
    document.getElementById("public-banner").hidden = false;
  }
  await import("./layout.mjs");
  await import("./fluxo-captura.mjs");
} catch (error) {
  if (PUBLIC_OPEN) {
    const retry = document.getElementById("session-retry");
    document.getElementById("session-status").textContent = error.message || "Sessão indisponível.";
    retry.textContent = error.reason === "expired" ? "Iniciar nova sessão" : "Tentar novamente";
    retry.hidden = false;
    retry.addEventListener("click", () => {
      if (error.reason === "expired") clearPublicSession();
      location.reload();
    }, { once: true });
    document.getElementById("login-panel").hidden = false;
    document.getElementById("login-form").hidden = true;
    document.body.classList.add("login-required");
  }
  const message = document.getElementById("message");
  message.textContent =
    "N\u00e3o foi poss\u00edvel iniciar a interface. Recarregue a p\u00e1gina para tentar novamente.";
  message.hidden = false;
  message.classList.add("error");
} finally {
  document.body.inert = false;
}
