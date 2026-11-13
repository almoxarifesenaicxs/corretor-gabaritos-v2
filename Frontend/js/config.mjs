
const API_PUBLICA = "https://corretor-gabaritos-8yal.onrender.com";

const ambienteLocal = ["localhost", "127.0.0.1"].includes(
  globalThis.location?.hostname
);

export const API_BASE_URL = ambienteLocal ? "" : API_PUBLICA;

// Configuração pública do Firebase Authentication
export const FIREBASE_API_KEY = "AIzaSyDG8PwUvZ9gVNL00y0cTI9OdZkTz9Zkrjw";
export const FIREBASE_AUTH_DOMAIN = "corretor-gabaritos-v2.firebaseapp.com";
export const FIREBASE_PROJECT_ID = "corretor-gabaritos-v2";
export const FIREBASE_APP_ID = "1:755495094535:web:3fd04433a5316c1f3e9da2";

// Exige login somente no site hospedado
export const AUTH_REQUIRED = !ambienteLocal;
