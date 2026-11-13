import { authSession } from "./auth.mjs";
import { request, setApiAccess } from "./api.mjs";
import { AUTH_REQUIRED } from "./config.mjs";

const sessions = new WeakMap();
const REVALIDAR_EM_MS = 5 * 60 * 1000;

export function requireLogin() {
  if (!AUTH_REQUIRED) {
    document.getElementById("login-panel").hidden = true;
    document.body.classList.remove("login-required");
    return Promise.resolve();
  }
  const existing = sessions.get(document);
  if (existing) return existing;

  const panel = document.getElementById("login-panel");
  const form = document.getElementById("login-form");
  const message = document.getElementById("login-message");
  const wait = document.getElementById("session-wait");
  const status = document.getElementById("session-status");
  const retry = document.getElementById("session-retry");
  const logoutButton = document.getElementById("logout");
  const submitButton = form.querySelector('button[type="submit"]');

  let authorized = false, authorizedUid = null, checking = false, loggingIn = false;
  let terminal = false, logoutFailed = false, inactive = false, reloadRequested = false;
  let blurredAt = 0;
  let version = 0, revalidateQueued = false, observerPromise = null;
  setApiAccess(false);

  function blockDashboard() {
    document.body.classList.add("login-required");
    document.body.inert = false;
    panel.hidden = false;
    logoutButton.hidden = true;
  }

  function showWaiting(text, canRetry = false) {
    blockDashboard();
    form.hidden = true;
    wait.hidden = false;
    status.textContent = text;
    retry.hidden = !canRetry;
  }

  function showForm(text = "") {
    blockDashboard();
    wait.hidden = true;
    retry.hidden = true;
    form.hidden = false;
    message.textContent = text;
  }

  function reloadOnce() {
    if (reloadRequested) return;
    reloadRequested = true;
    location.reload();
  }

  function endAuthorizedSession() {
    if (terminal) return;
    terminal = true;
    version++;
    setApiAccess(false);
    showWaiting("Encerrando sessão…");
    // Os módulos de captura e alunos descartam dados em memória e no DOM.
    globalThis.window?.dispatchEvent?.(new Event("corretor:session-ended"));
  }

  const ready = new Promise(resolve => {
    function openDashboard(uid) {
      if (terminal) return;
      authorizedUid = uid;
      const firstOpen = !authorized;
      authorized = true;
      setApiAccess(true);
      panel.hidden = true;
      document.body.classList.remove("login-required");
      document.body.inert = firstOpen;
      logoutButton.hidden = false;
      if (firstOpen) resolve();
    }

    function handleError(error) {
      if (terminal) return;
      if (error?.status === 401 || error?.reason === "invalid-session") {
        if (authorized) endAuthorizedSession();
        else showForm("Sessão expirada ou inválida. Entre novamente.");
      } else if (error?.status === 403) {
        if (authorized) endAuthorizedSession();
        else showForm(error.message || "Usuário sem autorização administrativa.");
      } else if (error?.reason === "configuration" || error?.reason === "credentials") {
        showForm(error.message);
      } else {
        showWaiting("Não foi possível confirmar sua autorização. Tente novamente.", true);
      }
    }

    function ensureObserver() {
      if (!observerPromise) {
        observerPromise = authSession.observeIdentity(uid => {
          if (authorized && uid !== authorizedUid) {
            endAuthorizedSession();
            reloadOnce();
          }
        }).catch(error => { observerPromise = null; throw error; });
      }
      return observerPromise;
    }

    async function confirmAuthorization(sequence) {
      await ensureObserver();
      const data = await request("/api/auth/me");
      const uid = await authSession.getUid();
      if (sequence !== version || terminal || revalidateQueued) return;
      if (!uid || uid !== data?.uid || (authorizedUid && uid !== authorizedUid)) {
        if (authorized) { endAuthorizedSession(); reloadOnce(); }
        else showForm("A conta mudou. Entre novamente.");
        return;
      }
      openDashboard(uid);
    }

    async function verifySession() {
      if (checking || loggingIn || terminal) return;
      checking = true;
      const sequence = ++version;
      setApiAccess(false);
      if (authorized) globalThis.window?.dispatchEvent?.(new Event("corretor:session-paused"));
      showWaiting("Verificando sessão…");
      try {
        const token = await authSession.restore();
        if (sequence !== version || terminal) return;
        if (!token) {
          if (authorized) { endAuthorizedSession(); reloadOnce(); }
          else showForm();
          return;
        }
        await confirmAuthorization(sequence);
      } catch (error) {
        if (sequence === version) handleError(error);
      } finally {
        checking = false;
        if (revalidateQueued && authorized && !terminal) {
          revalidateQueued = false;
          void verifySession();
        }
      }
    }

    function revalidateOnReturn() {
      if (!authorized || terminal) return;
      if (checking || loggingIn) {
        revalidateQueued = true;
        setApiAccess(false);
        globalThis.window?.dispatchEvent?.(new Event("corretor:session-paused"));
        showWaiting("Verificando sessão…");
        return;
      }
      void verifySession();
    }

    form.addEventListener("submit", async event => {
      event.preventDefault();
      if (checking || loggingIn || authorized || terminal) return;
      loggingIn = true;
      const sequence = ++version;
      submitButton.disabled = true;
      message.textContent = "";
      try {
        await authSession.login(form.elements.email.value.trim(), form.elements.password.value);
        if (sequence !== version || terminal) return;
        await confirmAuthorization(sequence);
      } catch (error) {
        if (sequence === version) handleError(error);
      } finally {
        form.elements.password.value = "";
        submitButton.disabled = false;
        loggingIn = false;
      }
    });

    retry.addEventListener("click", () => {
      if (logoutFailed) {
        logoutFailed = false;
        void authSession.logout();
      } else {
        void verifySession();
      }
    });

    logoutButton.addEventListener("click", async () => {
      if (authorized && !terminal) await authSession.logout();
    });

    authSession.onBlocked(() => { if (authorized) endAuthorizedSession(); });
    authSession.onLogout(() => { if (authorized) reloadOnce(); });
    authSession.onLogoutFailure(() => {
      if (!authorized) return;
      logoutFailed = true;
      showWaiting("Não foi possível encerrar a sessão. Tente novamente.", true);
    });

    document.addEventListener("visibilitychange", () => {
      if (document.hidden) inactive = true;
      else if (inactive) { inactive = false; revalidateOnReturn(); }
    });
    globalThis.window?.addEventListener?.("blur", () => { blurredAt = Date.now(); });
    globalThis.window?.addEventListener?.("focus", () => {
      if (blurredAt && Date.now() - blurredAt >= 1000 && !document.hidden) {
        blurredAt = 0;
        revalidateOnReturn();
      }
    });
    const timer = setInterval(() => {
      if (authorized && !terminal && panel.hidden && !document.hidden)
        void verifySession();
    }, REVALIDAR_EM_MS);
    timer.unref?.();

    void verifySession();
  });

  sessions.set(document, ready);
  return ready;
}
