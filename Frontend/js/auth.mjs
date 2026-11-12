import { FIREBASE_API_KEY, FIREBASE_AUTH_DOMAIN, FIREBASE_PROJECT_ID, FIREBASE_APP_ID } from "./config.mjs";

// Módulos oficiais fixados em uma versão; o frontend continua estático, sem build.
async function carregarSdk() {
  const [app, auth] = await Promise.all([
    import("https://www.gstatic.com/firebasejs/13.2.0/firebase-app.js"),
    import("https://www.gstatic.com/firebasejs/13.2.0/firebase-auth.js"),
  ]);
  return { ...app, ...auth };
}

export class AuthSessionError extends Error {
  constructor(reason, message) {
    super(message);
    this.name = "AuthSessionError";
    this.reason = reason;
  }
}

function erroSeguro(error) {
  if (error instanceof AuthSessionError) return error;
  const code = error?.code;
  if (["auth/user-token-expired", "auth/invalid-user-token", "auth/user-disabled",
    "auth/user-not-found", "auth/invalid-refresh-token"].includes(code))
    return new AuthSessionError("invalid-session", "Sessão expirada ou revogada. Entre novamente.");
  if (["auth/invalid-credential", "auth/invalid-login-credentials", "auth/wrong-password",
    "auth/invalid-email"].includes(code))
    return new AuthSessionError("credentials", "Não foi possível autenticar. Confira os dados e tente novamente.");
  if (code === "auth/network-request-failed")
    return new AuthSessionError("network", "Não foi possível conectar ao serviço de login. Tente novamente.");
  return new AuthSessionError("unavailable", "Serviço de login temporariamente indisponível. Tente novamente.");
}

export function createAuth({ apiKey = FIREBASE_API_KEY, authDomain = FIREBASE_AUTH_DOMAIN,
  projectId = FIREBASE_PROJECT_ID, appId = FIREBASE_APP_ID, sdkLoader = carregarSdk } = {}) {
  let clientPromise = null, pendingLogin = null, generation = 0, signedOut = false;
  const listeners = new Set();
  const blockedListeners = new Set(), failureListeners = new Set();

  async function client() {
    if (!apiKey || !authDomain || !projectId || !appId)
      throw new AuthSessionError("configuration", "Configure o Firebase Authentication para entrar.");
    if (!clientPromise) {
      clientPromise = (async () => {
        const sdk = await sdkLoader();
        const app = sdk.initializeApp({ apiKey, authDomain, projectId, appId });
        const auth = sdk.initializeAuth(app, { persistence: sdk.browserLocalPersistence });
        await auth.authStateReady();
        return { sdk, auth };
      })().catch(error => {
        clientPromise = null;
        throw erroSeguro(error);
      });
    }
    return clientPromise;
  }

  async function logout() {
    generation++;
    signedOut = true;
    for (const listener of blockedListeners) listener();
    try {
      const { sdk, auth } = await client();
      if (pendingLogin) await pendingLogin.catch(() => {});
      await sdk.signOut(auth);
      for (const listener of listeners) listener();
      return true;
    } catch {
      // Nunca anunciar logout concluído antes de limpar a persistência do SDK.
      for (const listener of failureListeners) listener();
      return false;
    }
  }

  async function tokenDoUsuario(user, forceRefresh = false) {
    try {
      const { sdk } = await client();
      return await sdk.getIdToken(user, forceRefresh);
    } catch (error) {
      const safe = erroSeguro(error);
      if (safe.reason === "invalid-session") await logout();
      throw safe;
    }
  }

  return {
    logout,
    onLogout(listener) { listeners.add(listener); return () => listeners.delete(listener); },
    onBlocked(listener) { blockedListeners.add(listener); return () => blockedListeners.delete(listener); },
    onLogoutFailure(listener) { failureListeners.add(listener); return () => failureListeners.delete(listener); },
    async getUid() {
      const { auth } = await client();
      return signedOut ? null : auth.currentUser?.uid || null;
    },
    async observeIdentity(listener) {
      const { sdk, auth } = await client();
      return sdk.onAuthStateChanged(auth, user => listener(user?.uid || null));
    },
    async login(email, password) {
      const current = ++generation;
      signedOut = true;
      try {
        const { sdk, auth } = await client();
        await sdk.signOut(auth);
        if (current !== generation) throw new AuthSessionError("cancelled", "Login cancelado.");
        pendingLogin = sdk.signInWithEmailAndPassword(auth, email, password);
        const { user } = await pendingLogin;
        if (current !== generation) {
          await sdk.signOut(auth);
          throw new AuthSessionError("cancelled", "Login cancelado.");
        }
        const token = await tokenDoUsuario(user);
        if (current !== generation) throw new AuthSessionError("cancelled", "Login cancelado.");
        signedOut = false;
        return token;
      } catch (error) {
        throw erroSeguro(error);
      } finally {
        pendingLogin = null;
      }
    },
    // Apenas recupera identidade Firebase. A interface ainda deve validar /api/auth/me.
    async restore() {
      const current = generation;
      const { auth } = await client();
      if (signedOut || !auth.currentUser) return null;
      const token = await tokenDoUsuario(auth.currentUser, true);
      return current === generation && !signedOut ? token : null;
    },
    async getToken() {
      if (!apiKey || signedOut) return null;
      const current = generation;
      const { auth } = await client();
      if (!auth.currentUser || signedOut) return null;
      const token = await tokenDoUsuario(auth.currentUser);
      return current === generation && !signedOut ? token : null;
    },
  };
}

export const authSession = createAuth();
