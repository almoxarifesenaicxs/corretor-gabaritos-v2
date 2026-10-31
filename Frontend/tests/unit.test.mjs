import test from "node:test";
import assert from "node:assert/strict";
import { Camera, cameraError } from "../js/camera.mjs";
import { validateFile, officialFromSelections, request } from "../js/api.mjs";

function fakeCamera(overrides = {}) {
  let stopped = 0;
  const track = {
    stop() {
      stopped++;
    },
  };
  const stream = { getTracks: () => [track] };
  const video = { srcObject: null, play: async () => {} };
  const scheduled = [],
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
    schedule: (fn) => {
      scheduled.push(fn);
      return scheduled.length;
    },
    cancel() {},
    ...overrides,
  });
  return { camera, stream, video, states, scheduled, stopped: () => stopped };
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
