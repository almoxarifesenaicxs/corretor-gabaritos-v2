
const API_PUBLICA = "https://corretor-gabaritos-8yal.onrender.com";

const ambienteLocal = ["localhost", "127.0.0.1"].includes(
  globalThis.location?.hostname
);

export const API_BASE_URL = ambienteLocal ? "" : API_PUBLICA;

// A versão pública não usa Firebase no navegador.
export const FIREBASE_API_KEY = "";
export const FIREBASE_AUTH_DOMAIN = "";
export const FIREBASE_PROJECT_ID = "";
export const FIREBASE_APP_ID = "";

// A hospedagem pública atual compartilha registros e não usa Firebase Authentication.
const DEMO_PUBLICADO = false;
const SESSOES_PUBLICADAS = false;
export const PUBLIC_DEMO = DEMO_PUBLICADO && Boolean(globalThis.location?.hostname) && !ambienteLocal;
export const PUBLIC_OPEN = SESSOES_PUBLICADAS && Boolean(globalThis.location?.hostname) && !ambienteLocal && !PUBLIC_DEMO;
export const PUBLIC_SHARED = Boolean(globalThis.location?.hostname) && !ambienteLocal && !PUBLIC_DEMO && !PUBLIC_OPEN;
export const AUTH_REQUIRED = !ambienteLocal && !PUBLIC_DEMO && !PUBLIC_OPEN && !PUBLIC_SHARED;
