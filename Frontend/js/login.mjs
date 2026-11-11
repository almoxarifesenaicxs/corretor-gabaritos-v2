import { authSession } from "./auth.mjs";
import { request } from "./api.mjs";

export function requireLogin() {
  const panel = document.getElementById("login-panel");
  const form = document.getElementById("login-form");
  const message = document.getElementById("login-message");
  document.body.inert = false;
  return new Promise((resolve) => {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = form.querySelector("button");
      button.disabled = true;
      message.textContent = "Entrando…";
      try {
        await authSession.login(form.elements.email.value.trim(), form.elements.password.value);
        await request("/api/auth/me");
        panel.hidden = true;
        document.body.classList.remove("login-required");
        document.body.inert = true;
        document.getElementById("logout").hidden = false;
        authSession.onLogout(() => location.reload());
        document.getElementById("logout").addEventListener("click", () => authSession.logout());
        resolve();
      } catch (error) {
        authSession.logout();
        message.textContent = error.message || "Não foi possível entrar.";
      } finally {
        form.elements.password.value = "";
        button.disabled = false;
      }
    });
  });
}
