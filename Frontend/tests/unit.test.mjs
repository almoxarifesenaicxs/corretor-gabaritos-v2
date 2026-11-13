import test from "node:test";
import assert from "node:assert/strict";
import { Camera, cameraError, frameBlob } from "../js/camera.mjs";
import { validateFile, officialFromSelections, request } from "../js/api.mjs";
import { authSession } from "../js/auth.mjs";

test.beforeEach(t => t.mock.method(authSession, "getToken", async () => "token-simulado"));

function fakeCamera(overrides = {}) {
  let stopped = 0;
  const track = {
    stop() {
      stopped++;
    },
  };
  const stream = { getTracks: () => [track] };
  const video = { srcObject: null, play: async () => {} };
  const scheduled = [], delays = [],
    states = [];
  const camera = new Camera({
    video,
    mediaDevices: {
      getUserMedia: async () => stream,
      enumerateDevices: async () => [
        { kind: "videoinput", deviceId: "usb" },
        { kind: "audioinput" },
      ],
    },
    snapshot: async () => new Blob(["frame"]),
    analyze: async () => ({ estado: "verde" }),
    onState: (state) => states.push(state),
    schedule: (fn, delay) => {
      scheduled.push(fn);
      delays.push(delay);
      return scheduled.length;
    },
    cancel() {},
    ...overrides,
  });
  return { camera, stream, video, states, scheduled, delays, stopped: () => stopped };
}

test("captura usa stream, permite selecionar dispositivo e encerra as trilhas", async () => {
  const fake = fakeCamera();
  assert.equal(await fake.camera.start("usb"), true);
  assert.equal(fake.video.srcObject, fake.stream);
  assert.equal((await fake.camera.devices()).length, 1);
  assert.ok((await fake.camera.capture()) instanceof Blob);
  fake.camera.stop();
  assert.equal(fake.stopped(), 1);
  assert.equal(fake.video.srcObject, null);
  await assert.rejects(() => fake.camera.capture());
});

test("prefere câmera traseira sem exigir que ela exista; dispositivo escolhido prevalece", async () => {
  const calls = [];
  const fake = fakeCamera();
  fake.camera.mediaDevices.getUserMedia = async (options) => {
    calls.push(options);
    return fake.stream;
  };
  await fake.camera.start();
  assert.deepEqual(calls[0].video.facingMode, { ideal: "environment" });
  assert.equal(calls[0].video.deviceId, undefined);
  await fake.camera.start("usb");
  assert.deepEqual(calls[1].video.deviceId, { exact: "usb" });
  assert.equal(calls[1].video.facingMode, undefined);
  fake.camera.stop();
});

test("captura em retrato e paisagem preserva proporção e limita resolução", async () => {
  const original = globalThis.document;
  const dimensions = [];
  const formats = [];
  globalThis.document = { createElement: () => {
    const canvas = {
      width: 0, height: 0,
      getContext: () => ({ drawImage: (...args) => dimensions.push(args.slice(-2)) }),
      toBlob: (callback, format) => {
        formats.push(format);
        callback(new Blob(["foto"], { type: format }));
      },
    };
    return canvas;
  } };
  try {
    await frameBlob({ videoWidth: 4032, videoHeight: 3024 });
    await frameBlob({ videoWidth: 3024, videoHeight: 4032 });
    await frameBlob({ videoWidth: 4032, videoHeight: 3024 }, 800);
    assert.deepEqual(dimensions, [[2560, 1920], [1920, 2560], [800, 600]]);
    assert.deepEqual(formats, ["image/jpeg", "image/jpeg", "image/png"]);
  } finally { globalThis.document = original; }
});

test("permissão tardia é encerrada depois de sair da aba", async () => {
  let permit;
  const fake = fakeCamera();
  fake.camera.mediaDevices.getUserMedia = () =>
    new Promise((resolve) => {
      permit = resolve;
    });
  const opening = fake.camera.start();
  fake.camera.stop();
  permit(fake.stream);
  assert.equal(await opening, false);
  assert.equal(fake.stopped(), 1);
  assert.equal(fake.video.srcObject, null);
});

test("analisa em frequência limitada e descarta resposta após parar", async () => {
  let finish;
  const fake = fakeCamera({
    analyze: () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  });
  await fake.camera.start();
  assert.equal(fake.scheduled.length, 1);
  assert.equal(fake.delays[0], 500);
  const pending = fake.scheduled[0]();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(fake.scheduled.length, 1);
  fake.camera.stop();
  finish({ estado: "verde" });
  await pending;
  assert.equal(fake.states.at(-1).estado, "vermelho");
  assert.equal(fake.scheduled.length, 1);
});

test("falha de análise nunca informa verde", async () => {
  const fake = fakeCamera({
    analyze: async () => {
      throw new Error("offline");
    },
  });
  await fake.camera.start();
  await fake.scheduled[0]();
  assert.equal(fake.states.at(-1).estado, "vermelho");
  assert.match(fake.states.at(-1).mensagem, /não validado/);
  assert.equal(fake.scheduled.length, 2);
  assert.equal(fake.delays[1], 5000);
  fake.camera.stop();
});

test("análise bem-sucedida reduz chamadas e quadro inicial ausente tenta novamente", async () => {
  const normal = fakeCamera();
  await normal.camera.start();
  await normal.scheduled[0]();
  assert.equal(normal.delays[1], 3000);
  normal.camera.stop();
  const aguardando = fakeCamera({ snapshot: async () => { throw new Error("Aguarde a imagem da câmera."); } });
  await aguardando.camera.start();
  await aguardando.scheduled[0]();
  assert.equal(aguardando.delays[1], 1000);
  aguardando.camera.stop();
});

test("rejeição tardia da câmera antiga não encerra a câmera nova", async () => {
  const tracks = [0, 1].map(() => ({ stopped: false, stop() { this.stopped = true; } }));
  const streams = tracks.map(track => ({ getTracks: () => [track] }));
  let rejectOld, playCalls = 0, mediaCalls = 0;
  const fake = fakeCamera({
    mediaDevices: { getUserMedia: async () => streams[mediaCalls++] },
    video: { srcObject: null, play: () => ++playCalls === 1
      ? new Promise((_, reject) => { rejectOld = reject; }) : Promise.resolve() },
  });
  const first = fake.camera.start();
  await new Promise(resolve => setImmediate(resolve));
  const second = fake.camera.start();
  assert.equal(await second, true);
  rejectOld(new Error("falha antiga"));
  assert.equal(await first, false);
  assert.equal(fake.camera.stream, streams[1]);
  assert.equal(tracks[0].stopped, true);
  assert.equal(tracks[1].stopped, false);
  fake.camera.stop();
});

test("desconexão e permissão negada deixam a câmera fechada", async () => {
  let ended;
  const track = { stop() {}, addEventListener: (_, fn) => { ended = fn; } };
  const stream = { getTracks: () => [track] };
  const fake = fakeCamera({ mediaDevices: { getUserMedia: async () => stream } });
  await fake.camera.start();
  ended();
  assert.equal(fake.camera.stream, null);
  assert.match(fake.states.at(-1).mensagem, /desconectada/);
  const denied = fakeCamera({ mediaDevices: {
    getUserMedia: async () => { throw { name: "NotAllowedError" }; },
  } });
  await assert.rejects(() => denied.camera.start());
  assert.equal(denied.camera.stream, null);
});

test("captura tardia é descartada e capturas consecutivas funcionam", async () => {
  let finish;
  const fake = fakeCamera({ snapshot: () => new Promise(resolve => { finish = resolve; }) });
  await fake.camera.start();
  const old = fake.camera.capture();
  fake.camera.stop();
  finish(new Blob(["antiga"]));
  await assert.rejects(old, { name: "AbortError" });
  await fake.camera.start();
  const first = fake.camera.capture();
  finish(new Blob(["primeira"]));
  assert.equal((await first).size, 8);
  const second = fake.camera.capture();
  finish(new Blob(["segunda"]));
  assert.equal((await second).size, 7);
  fake.camera.stop();
});

test("contexto sem câmera oferece mensagem clara", async () => {
  const fake = fakeCamera({ mediaDevices: null });
  await assert.rejects(() => fake.camera.start(), /HTTPS ou localhost/);
  assert.match(cameraError({ name: "NotAllowedError" }), /Permissão/);
  assert.match(cameraError({ name: "NotFoundError" }), /Nenhuma câmera/);
  assert.match(cameraError({ name: "NotReadableError" }), /ocupada/);
});

test("valida formato e tamanho antes de enviar", () => {
  assert.ok(validateFile({ name: "cartão.PDF", size: 100 }));
  for (const file of [
    { name: "arquivo.exe", size: 10 },
    { name: "cartao.png", size: 0 },
    { name: "cartao.png", size: 10485761 },
  ]) {
    assert.throws(() => validateFile(file));
  }
});

test("conferência exige exatamente 50 alternativas e mantém ordem", () => {
  const values = Array(50).fill("A");
  values[25] = "E";
  const official = officialFromSelections(values);
  assert.equal(official["26"], "E");
  assert.equal(Object.keys(official).length, 50);
  assert.throws(() => officialFromSelections(values.slice(1)));
  values[1] = "";
  assert.throws(() => officialFromSelections(values));
});

test("erros HTTP são mostrados sem fingir sucesso", async () => {
  const before = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: false,
    json: async () => ({ detail: "Persistência indisponível." }),
  });
  try {
    await assert.rejects(() => request("/api/avaliacoes"), /indisponível/);
  } finally {
    globalThis.fetch = before;
  }
});

test("JSON de sucesso truncado não confirma uma gravação", async () => {
  const before = globalThis.fetch;
  globalThis.fetch = async () => ({
    ok: true,
    json: async () => { throw new SyntaxError("JSON truncado"); },
  });
  try {
    await assert.rejects(() => request("/api/correcoes/salvar"), /Resposta incompleta/);
  } finally {
    globalThis.fetch = before;
  }
});
