import * as runtimeConfig from "./config.mjs";
const { API_BASE_URL, AUTH_REQUIRED, PUBLIC_OPEN } = runtimeConfig;
const PUBLIC_SHARED = runtimeConfig.PUBLIC_SHARED === true;
import { getPublicSessionId } from "./public-session.mjs";

const KEY = "corretor:correcoes-pendentes:v1";
const storageKey = () => PUBLIC_OPEN ? `${KEY}:${getPublicSessionId()}` : KEY;
const MAX = 20;
const FIELDS = ["prova_id", "aluno", "aluno_id", "novo_homonimo", "resultado",
  "respostas", "comprovante", "confirmado", "permitir_provisorio", "origem_lote"];

export function recoveryAvailable(base = API_BASE_URL, location = globalThis.location) {
  return (base === "" && ["127.0.0.1", "localhost", "[::1]"].includes(location?.hostname)) ||
    ((AUTH_REQUIRED || PUBLIC_OPEN || PUBLIC_SHARED) && location?.protocol === "https:" && base.startsWith("https://"));
}

export function createRecovery({ storage = globalThis.localStorage,
  enabled = recoveryAvailable() } = {}) {
  const data = (payload) => Object.fromEntries(FIELDS.map(field => [field, payload[field]]));
  const fingerprint = (payload) => JSON.stringify(data(payload));
  function read() {
    if (!enabled) return [];
    let entries;
    try { entries = JSON.parse(storage.getItem(storageKey()) || "[]"); }
    catch { throw new Error("Registro local de recuperação ilegível. Não envie outra correção antes de conferir o histórico."); }
    if (!Array.isArray(entries) || entries.length > MAX || entries.some(entry =>
      !/^[0-9a-f-]{36}$/i.test(entry?.id) || !entry.payload ||
      entry.payload.operacao_id !== entry.id || typeof entry.createdAt !== "number"))
      throw new Error("Registro local de recuperação inválido. Confira o histórico antes de continuar.");
    return entries;
  }
  function write(entries) {
    try { storage.setItem(storageKey(), JSON.stringify(entries)); }
    catch { throw new Error("Não foi possível preservar a correção neste navegador. O envio foi bloqueado."); }
  }
  return {
    enabled,
    list: () => read().map(({ id, createdAt }) => ({ id, createdAt })),
    get: id => read().find(entry => entry.id === id)?.payload || null,
    matching: payload => read().find(entry => fingerprint(entry.payload) === fingerprint(payload))?.id || null,
    preserve(payload) {
      if (!enabled) return;
      const entries = read();
      const previous = entries.find(entry => entry.id === payload.operacao_id);
      if (previous) {
        if (fingerprint(previous.payload) !== fingerprint(payload))
          throw new Error("Identificador já vinculado a outra correção. Confira o histórico.");
        return;
      }
      if (entries.length >= MAX)
        throw new Error("Limite de operações pendentes. Resolva as anteriores antes de salvar.");
      const minimal = { ...data(payload), operacao_id: payload.operacao_id };
      write([...entries, { id: payload.operacao_id, createdAt: Date.now(), payload: minimal }]);
    },
    confirm(id) {
      if (enabled) write(read().filter(entry => entry.id !== id));
    },
  };
}
