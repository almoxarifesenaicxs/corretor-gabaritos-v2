import { loadPages } from "./paginas.mjs";
import { requireLogin } from "./login.mjs";

const navigation = [...document.querySelectorAll("[data-tab]")];
navigation.forEach((button) => {
  button.disabled = true;
});
try {
  document.body.inert = false;
  await requireLogin();
  await loadPages();
  await import("./layout.mjs");
  await import("./fluxo-captura.mjs");
} catch {
  const message = document.getElementById("message");
  message.textContent =
    "N\u00e3o foi poss\u00edvel iniciar a interface. Recarregue a p\u00e1gina para tentar novamente.";
  message.hidden = false;
  message.classList.add("error");
} finally {
  document.body.inert = false;
}
