import { API_BASE_URL, PUBLIC_OPEN } from "./config.mjs";

const STORAGE_KEY = "corretor:sessao-publica:v1";
let current = null;
let pending = null;

export class PublicSessionError extends Error {
  constructor(reason, message) {
    super(message);
    this.reason = reason;
  }
}

export function getPublicSessionToken() {
  if (!PUBLIC_OPEN) return null;
  if (!current) throw new PublicSessionError("missing", "A sessão anônima ainda não está pronta.");
  return current;
}

export function getPublicSessionId() {
  return getPublicSessionToken()?.split(".", 1)[0] || null;
}

export function clearPublicSession() {
  current = null;
  localStorage.removeItem(STORAGE_KEY);
}

export function initializePublicSession() {
  if (!PUBLIC_OPEN) return Promise.resolve();
  if (current) return Promise.resolve();
  if (pending) return pending;
  pending = (async () => {
    let stored;
    try { stored = localStorage.getItem(STORAGE_KEY); }
    catch { throw new PublicSessionError("storage", "Armazenamento local indisponível; não é seguro iniciar uma sessão."); }
    const endpoint = API_BASE_URL + "/api/public/session";
    let response;
    try {
      response = await fetch(endpoint, {
        method: stored ? "GET" : "POST",
        headers: stored ? { Authorization: `Bearer ${stored}` } : {},
        cache: "no-store", redirect: "error",
      });
    } catch {
      throw new PublicSessionError("network", "API indisponível. Tente novamente sem apagar a sessão existente.");
    }
    if (stored) {
      if (response.status === 401)
        throw new PublicSessionError("expired", "Sessão expirada. Os resultados antigos não podem ser recuperados sem seu identificador válido.");
      if (!response.ok)
        throw new PublicSessionError("network", "Não foi possível validar a sessão. Tente novamente.");
      current = stored;
      return;
    }
    if (!response.ok)
      throw new PublicSessionError("network", "Não foi possível criar a sessão anônima. Tente novamente.");
    const data = await response.json().catch(() => null);
    if (typeof data?.token !== "string" || !/^[A-Za-z0-9_-]{32}\.[0-9]{10}\.[A-Za-z0-9_-]{43}$/.test(data.token))
      throw new PublicSessionError("network", "API retornou uma sessão inválida.");
    try { localStorage.setItem(STORAGE_KEY, data.token); }
    catch { throw new PublicSessionError("storage", "Não foi possível preservar a sessão neste navegador."); }
    current = data.token;
  })().finally(() => { pending = null; });
  return pending;
}
