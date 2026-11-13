import { API_BASE_URL, AUTH_REQUIRED } from "./config.mjs";
import { authSession } from "./auth.mjs";

let gateEnabled = false, gateOpen = false, gateEpoch = 0;

// Mantém a possibilidade de invalidar operações assíncronas da interface.
export function setApiAccess(open) {
  gateEnabled = true;
  gateOpen = Boolean(open);
  gateEpoch++;
}

export function isApiAccessAllowed() { return !gateEnabled || gateOpen; }

function checkAccess(path, epoch) {
  if (AUTH_REQUIRED && path === "/api/auth/me") return;
  if (gateEnabled && (!gateOpen || epoch !== gateEpoch))
    throw new Error("A sessão precisa ser validada antes de continuar.");
}

export function apiUrl(path, base = API_BASE_URL, pageUrl = globalThis.location?.href) {
  if (typeof path !== "string" || !path.startsWith("/api/") || path.includes("\\"))
    throw new Error("Caminho da API inválido.");
  const page = pageUrl ? new URL(pageUrl) : null;
  const locais = new Set(["localhost", "127.0.0.1", "[::1]"]);
  if (base === "") {
    if (page && !locais.has(page.hostname))
      throw new Error("Configure a URL HTTPS da API em js/config.mjs.");
    if (!new URL(path, "http://localhost").pathname.startsWith("/api/"))
      throw new Error("Caminho da API inválido.");
    return path;
  }
  const origin = new URL(base);
  if (!["http:", "https:"].includes(origin.protocol) || origin.username || origin.password ||
      origin.pathname !== "/" || origin.search || origin.hash)
    throw new Error("Configure somente a origem HTTP(S) do backend.");
  if (origin.protocol !== "https:" && (page?.protocol === "https:" || !locais.has(origin.hostname)))
    throw new Error("A conexão com a API hospedada exige HTTPS.");
  const target = new URL(path, origin);
  if (!target.pathname.startsWith("/api/")) throw new Error("Caminho da API inválido.");
  return target.href;
}

export async function request(url, options = {}) {
  const target = apiUrl(url);
  const epoch = gateEpoch;
  checkAccess(url, epoch);
  const headers = new Headers(options.headers);
  headers.delete("Authorization");
  let generation;
  if (AUTH_REQUIRED) {
    const token = await authSession.getToken();
    generation = authSession.getGeneration();
    checkAccess(url, epoch);
    if (!token) {
      const error = new Error("Sessão ausente ou expirada. Entre novamente.");
      error.status = 401;
      throw error;
    }
    headers.set("Authorization", `Bearer ${token}`);
  }
  const checkCurrent = () => {
    checkAccess(url, epoch);
    if (AUTH_REQUIRED && generation !== authSession.getGeneration())
      throw new Error("A operação pertence a uma sessão anterior.");
  };
  let response;
  try {
    response = await fetch(target, { ...options, headers, cache: "no-store", redirect: "error" });
  } catch (error) {
    checkCurrent();
    if (error.name === "AbortError") throw error;
    throw new Error("Não foi possível conectar à API. Confira a conexão e tente novamente. Se estava salvando, confira o histórico ou reenvie a mesma operação.");
  }
  checkCurrent();
  const data = await response.json().catch(() => null);
  checkCurrent();
  if (!response.ok) {
    if (AUTH_REQUIRED && (response.status === 401 || response.status === 403))
      await authSession.logout();
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : response.status === 401 ? "A API exige autenticação; confira a configuração do backend."
        : response.status === 403 ? "Acesso bloqueado pela configuração do backend."
        : response.status === 429 || response.status >= 500
          ? "Serviço temporariamente indisponível. Aguarde e tente novamente. Se estava salvando, confira o histórico ou reenvie a mesma operação."
          : "Confira os campos e tente novamente.";
    const error = new Error(data?.detail?.mensagem || detail);
    error.details = data?.detail;
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) return null;
  if (data === null)
    throw new Error("Resposta incompleta do servidor. Confira o histórico ou reenvie a mesma operação.");
  return data;
}

export async function requestBinary(url) {
  const target = apiUrl(url);
  const epoch = gateEpoch;
  checkAccess(url, epoch);
  const headers = new Headers();
  let generation;
  if (AUTH_REQUIRED) {
    const token = await authSession.getToken();
    generation = authSession.getGeneration();
    checkAccess(url, epoch);
    if (!token) throw new Error("Sessão ausente ou expirada. Entre novamente.");
    headers.set("Authorization", `Bearer ${token}`);
  }
  const response = await fetch(target, { headers, cache: "no-store", redirect: "error" });
  checkAccess(url, epoch);
  if (AUTH_REQUIRED && generation !== authSession.getGeneration())
    throw new Error("A operação pertence a uma sessão anterior.");
  if (!response.ok) {
    if (AUTH_REQUIRED && (response.status === 401 || response.status === 403))
      await authSession.logout();
    throw new Error(`Não foi possível carregar a imagem do lote (${response.status}).`);
  }
  return response;
}

export function jsonPost(url, data) {
  return request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function upload(url, file, fields = {}, signal) {
  const body = new FormData();
  body.append("arquivo", file, file.name || "captura.png");
  for (const [name, value] of Object.entries(fields))
    body.append(name, String(value));
  return request(url, { method: "POST", body, signal });
}

export function validateFile(file) {
  if (!file || !/\.(pdf|png|jpe?g)$/i.test(file.name))
    throw new Error("Selecione PDF, JPG ou PNG.");
  if (file.size === 0) throw new Error("O arquivo está vazio.");
  if (file.size > 10 * 1024 * 1024)
    throw new Error("O limite é de 10 MiB por arquivo.");
  return file;
}

export function officialFromSelections(values) {
  if (values.length !== 50 || values.some((value) => !/^[A-E]$/.test(value))) {
    throw new Error(
      "Confira e preencha uma alternativa válida em cada uma das 50 questões.",
    );
  }
  return Object.fromEntries(
    values.map((value, index) => [String(index + 1), value]),
  );
}
