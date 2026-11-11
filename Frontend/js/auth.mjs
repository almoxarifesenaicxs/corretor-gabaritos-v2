import { FIREBASE_API_KEY } from "./config.mjs";

export function createAuth({ apiKey = FIREBASE_API_KEY, fetcher = (...args) => fetch(...args),
  now = () => Date.now() } = {}) {
  let session = null, refreshing = null, generation = 0;
  const listeners = new Set();
  function logout() {
    generation++;
    session = null;
    refreshing = null;
    for (const listener of listeners) listener();
  }
  function save(data, refresh = false) {
    const token = refresh ? data.id_token : data.idToken;
    const refreshToken = refresh ? data.refresh_token : data.refreshToken;
    const seconds = Number(refresh ? data.expires_in : data.expiresIn);
    if (!token || !refreshToken || !Number.isFinite(seconds) || seconds <= 0)
      throw new Error("Resposta de autenticação inválida.");
    session = { token, refreshToken, expires: now() + seconds * 1000 };
    return token;
  }
  async function send(url, options) {
    let response;
    try {
      response = await fetcher(url, { ...options, credentials: "omit", cache: "no-store" });
    } catch {
      throw new Error("Não foi possível conectar ao serviço de login. Confira sua conexão e tente novamente.");
    }
    if (!response.ok) throw new Error("Não foi possível autenticar. Confira os dados e tente novamente.");
    return response.json();
  }
  return {
    logout,
    onLogout(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    async login(email, password) {
      if (!apiKey) throw new Error("Configure o Firebase Authentication para entrar.");
      logout();
      const current = generation;
      const data = await send(`https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=${encodeURIComponent(apiKey)}`,
        { method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email, password, returnSecureToken: true }) });
      if (current !== generation) throw new Error("Login cancelado.");
      return save(data);
    },
    async getToken() {
      if (!session) return null;
      if (session.expires > now() + 60000) return session.token;
      if (!refreshing) {
        const current = generation;
        const refreshToken = session.refreshToken;
        refreshing = (async () => {
          try {
            const data = await send(`https://securetoken.googleapis.com/v1/token?key=${encodeURIComponent(apiKey)}`,
              { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" },
                body: new URLSearchParams({ grant_type: "refresh_token", refresh_token: refreshToken }) });
            if (current !== generation) throw new Error("Sessão encerrada.");
            return save(data, true);
          } catch (error) {
            if (current === generation) logout();
            throw error;
          } finally { if (current === generation) refreshing = null; }
        })();
      }
      return refreshing;
    },
  };
}

export const authSession = createAuth();
