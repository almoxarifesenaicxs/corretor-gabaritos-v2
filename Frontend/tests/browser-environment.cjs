// Harness exclusivo de testes: nenhum servidor FastAPI ou Firebase é iniciado.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const http = require('node:http');
const { chromium: realChromium } = require('playwright');
const env = { baseURL: '', artifacts: '', blocked: [], unexpected: [] };
const root = path.resolve(__dirname, '..');
let server, picture;
const binaries = [process.env.QA_CHROME_PATH,
  'C:/Program Files/Google/Chrome/Application/chrome.exe',
  'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'];
const executablePath = binaries.find(p => p && fs.existsSync(p));
function options(extra = {}) {
  return { ...extra, executablePath: extra.executablePath || executablePath, headless: true };
}
const answers = () => Object.fromEntries(Array.from({ length: 50 }, (_, i) =>
  [String(i + 1), { estado: 'marcada', resposta: 'A', alternativas: ['A'] }]));

// Apenas contrato sintético da API; não mede nem substitui o motor Python.
function result(respostas) {
  const marcacoes = {}, pendentes = [];
  const summary = entries => {
    const s = { acertos: 0, erros: 0, brancos: 0, multiplas: 0, duvidosas: 0, pendentes: 0 };
    for (const [, item] of entries) {
      const k = item.estado === 'marcada' ? (item.resposta === 'A' ? 'acertos' : 'erros') :
        { branco: 'brancos', multipla: 'multiplas', duvidosa: 'duvidosas' }[item.estado];
      s[k]++;
    }
    s.pendentes = s.multiplas + s.duvidosas;
    return { ...s, pontuacao: s.acertos, pontuacao_maxima: entries.length,
      percentual_acertos: s.acertos / entries.length * 100 };
  };
  for (const [n, item] of Object.entries(respostas)) {
    const estado = item.estado === 'marcada' ? (item.resposta === 'A' ? 'correta' : 'incorreta') :
      item.estado === 'branco' ? 'branco' : 'pendente';
    marcacoes[n] = { estado, alternativas: item.alternativas };
    if (estado === 'pendente') pendentes.push(n);
  }
  const entries = Object.entries(respostas);
  return { respostas, comprovante: 'a'.repeat(64), marcacoes,
    resultado: { resumo: summary(entries), provisorio: pendentes.length > 0,
      questoes_pendentes: pendentes, disciplinas: {
        portugues: summary(entries.slice(0, 25)), matematica: summary(entries.slice(25)) } },
    visualizacao: { imagem: picture, mensagem: 'Imagem sintética de teste',
      posicoes: Object.fromEntries(entries.map(([n]) => [n, Object.fromEntries(
        [...'ABCDE'].map((letter, i) => [letter, { x: 80 + i * 55,
          y: 10 + (Number(n) - 1) * 20, largura: 30, altura: 14 }]))])) } };
}

async function intercept(context) {
  await context.route('**/*', async route => {
    const request = route.request(), url = new URL(request.url());
    if (url.origin !== env.baseURL) {
      env.blocked.push(url.origin);
      return route.abort('blockedbyclient');
    }
    if (url.pathname === '/interface/js/config.mjs') return route.fulfill({
      contentType: 'text/javascript', body: 'export const API_BASE_URL=""; export const AUTH_REQUIRED=false; export const FIREBASE_API_KEY=""; export const FIREBASE_AUTH_DOMAIN=""; export const FIREBASE_PROJECT_ID=""; export const FIREBASE_APP_ID="";' });
    if (!url.pathname.startsWith('/api/')) return route.continue();
    assert.equal(request.headers().authorization, undefined);
    let payload;
    switch (url.pathname) {
      case '/api/avaliacoes': case '/api/alunos': payload = []; break;
      case '/api/alunos/correspondencias': payload = { exato: null, exatos: [], semelhantes: [] }; break;
      case '/api/capturas/analisar': payload = { estado: 'vermelho', mensagem: 'Folha não detectada.', cantos: [], folha_visivel: false }; break;
      case '/api/alunos/reconhecer-nome': payload = { estado: 'sugerido', nome: 'MARIA DA SILVA', mensagem: 'Nome simulado; confira.' }; break;
      case '/api/gabaritos/reconhecer': payload = answers(); break;
      case '/api/correcoes/recalcular': payload = result(request.postDataJSON().respostas); break;
      case '/api/correcoes/processar': {
        assert.match(request.headers()['content-type'], /^multipart\/form-data; boundary=/);
        const body = request.postDataBuffer().toString('latin1');
        assert.match(body, /name="arquivo"; filename=/);
        const a = answers();
        if (body.includes('visual-mista.png')) {
          for (const n of Object.keys(a)) a[n] = { estado: 'branco', resposta: null, alternativas: [] };
          a['1'] = answers()['1'];
          a['2'] = { estado: 'marcada', resposta: 'B', alternativas: ['B'] };
          a['4'] = { estado: 'multipla', resposta: null, alternativas: ['A', 'B'] };
        } else if (body.includes('multipla.png')) a['27'] = { estado: 'multipla', resposta: null, alternativas: ['A', 'B'] };
        payload = result(a); break;
      }
      default:
        env.unexpected.push(url.pathname);
        return route.fulfill({ status: 501, json: { detail: 'Endpoint sem mock.' } });
    }
    return route.fulfill({ json: payload });
  });
}

env.chromium = { async launch(extra) {
  const browser = await realChromium.launch(options(extra));
  const createContext = browser.newContext.bind(browser);
  browser.newContext = async settings => {
    const context = await createContext({ ...settings, serviceWorkers: 'block' });
    context.setDefaultTimeout(10000);
    await intercept(context);
    return context;
  };
  browser.newPage = async settings => (await browser.newContext(settings)).newPage();
  return browser;
} };

env.start = async () => {
  assert.equal(process.env.QA_BASE_URL, undefined, 'Servidor externo não permitido nesta suíte isolada.');
  assert.equal(process.env.QA_ARTIFACT_DIR, undefined, 'Artefatos são criados em pasta temporária própria.');
  env.artifacts = fs.mkdtempSync(path.join(os.tmpdir(), 'corretor-browser-'));
  server = http.createServer((req, res) => {
    const pathname = new URL(req.url, 'http://localhost').pathname;
    const relative = pathname === '/interface/' ? 'index.html' : pathname.replace(/^\/interface\//, '');
    if (!pathname.startsWith('/interface/') || !/^(index\.html|(?:js|css|pages|components|assets\/fonts)\/[\w./-]+)$/.test(relative)) {
      res.writeHead(404).end(); return;
    }
    const file = path.resolve(root, relative);
    if (!file.startsWith(root + path.sep) || !fs.existsSync(file) || !fs.statSync(file).isFile()) {
      res.writeHead(404).end(); return;
    }
    const mime = { '.html': 'text/html', '.mjs': 'text/javascript', '.css': 'text/css', '.ttf': 'font/ttf' };
    res.writeHead(200, { 'Content-Type': (mime[path.extname(file)] || 'application/octet-stream') + '; charset=utf-8' });
    fs.createReadStream(file).pipe(res);
  });
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  env.baseURL = `http://127.0.0.1:${server.address().port}`;
  const browser = await realChromium.launch(options());
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => route.abort());
    picture = await page.evaluate(() => {
      const c = document.createElement('canvas'); c.width = 800; c.height = 1100;
      const ctx = c.getContext('2d'); ctx.fillStyle = 'white'; ctx.fillRect(0, 0, 800, 1100);
      return c.toDataURL('image/png');
    });
    for (const name of ['cartao.png', 'multipla.png', 'visual-mista.png', 'nome-impresso.png'])
      fs.writeFileSync(path.join(env.artifacts, name), Buffer.from(picture.split(',')[1], 'base64'));
  } finally { await browser.close(); }
};
env.stop = async () => {
  if (server) { server.closeAllConnections(); await new Promise(resolve => server.close(resolve)); }
  // Remove somente o diretório criado por mkdtemp, nunca um caminho fornecido pelo usuário.
  if (env.artifacts && path.dirname(env.artifacts) === path.resolve(os.tmpdir()) &&
      path.basename(env.artifacts).startsWith('corretor-browser-')) fs.rmSync(env.artifacts, { recursive: true });
  assert.deepEqual(env.unexpected, [], 'Toda chamada de API deve ter mock explícito.');
  assert.deepEqual(env.blocked, [], 'Nenhuma tentativa inesperada de rede externa.');
};
module.exports = env;
