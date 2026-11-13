// Usa a API local quando o site está rodando no computador.
// Na Vercel, continua utilizando a API da Render.

const API_PUBLICA = "https://corretor-gabaritos-8yal.onrender.com";

const ambienteLocal = ["localhost", "127.0.0.1"].includes(
  globalThis.location?.hostname
);

export const API_BASE_URL = ambienteLocal ? "" : API_PUBLICA;

// Valores públicos do aplicativo Web cadastrados no Firebase Console.
// Preencher antes de publicar o frontend; nunca colocar conta de serviço aqui.
export const FIREBASE_API_KEY = "";
export const FIREBASE_AUTH_DOMAIN = "";
export const FIREBASE_PROJECT_ID = "";
export const FIREBASE_APP_ID = "";
export const AUTH_REQUIRED = !ambienteLocal;
