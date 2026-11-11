export function frameBlob(video, maxSize = 1920) {
  if (!video.videoWidth || !video.videoHeight)
    return Promise.reject(new Error("Aguarde a imagem da câmera."));
  const canvas = document.createElement("canvas");
  const scale = Math.min(
    1,
    maxSize / Math.max(video.videoWidth, video.videoHeight),
  );
  canvas.width = Math.round(video.videoWidth * scale);
  canvas.height = Math.round(video.videoHeight * scale);
  canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) =>
    canvas.toBlob(
      (blob) =>
        blob
          ? resolve(blob)
          : reject(new Error("Não foi possível capturar a imagem.")),
      "image/png",
    ),
  );
}

export function cameraError(error) {
  return (
    {
      NotAllowedError:
        "Permissão da câmera negada. Libere o acesso no navegador ou envie um arquivo.",
      NotFoundError:
        "Nenhuma câmera foi encontrada. Conecte a webcam ou envie um arquivo.",
      NotReadableError:
        "A câmera está ocupada ou indisponível. Feche outros aplicativos.",
      OverconstrainedError:
        "A câmera selecionada não está disponível. Selecione outra.",
    }[error.name] ||
    error.message ||
    "Não foi possível ativar a câmera."
  );
}

export class Camera {
  constructor({
    video,
    analyze,
    onState,
    mediaDevices = globalThis.navigator?.mediaDevices,
    snapshot = frameBlob,
    schedule = (fn, delay) => globalThis.setTimeout(fn, delay),
    cancel = (timer) => globalThis.clearTimeout(timer),
  }) {
    Object.assign(this, {
      video,
      analyze,
      onState,
      mediaDevices,
      snapshot,
      schedule,
      cancel,
    });
    this.generation = 0;
    this.stream = null;
  }
  async start(deviceId = "") {
    this.stop();
    const generation = this.generation;
    if (!this.mediaDevices?.getUserMedia)
      throw new Error(
        "Webcam exige HTTPS ou localhost e navegador compatível.",
      );
    const stream = await this.mediaDevices.getUserMedia({
      audio: false,
      video: {
        ...(deviceId ? { deviceId: { exact: deviceId } } : {}),
        width: { ideal: 1920 },
        height: { ideal: 1080 },
      },
    });
    if (generation !== this.generation) {
      stream.getTracks().forEach((track) => track.stop());
      return false;
    }
    this.stream = stream;
    this.video.srcObject = stream;
    try {
      await this.video.play();
    } catch (error) {
      this.stop();
      throw error;
    }
    if (generation !== this.generation) return false;
    for (const track of stream.getTracks()) {
      track.addEventListener?.("ended", () => {
        if (generation === this.generation) this.stop();
      });
    }
    this.timer = this.schedule(() => this.tick(generation), 500);
    return true;
  }
  async devices() {
    return (await this.mediaDevices.enumerateDevices()).filter(
      (device) => device.kind === "videoinput",
    );
  }
  async tick(generation) {
    if (!this.stream || generation !== this.generation) return;
    this.controller = new AbortController();
    try {
      const blob = await this.snapshot(this.video, 800);
      if (generation !== this.generation) return;
      const data = await this.analyze(blob, this.controller.signal);
      if (generation === this.generation) this.onState(data);
    } catch (error) {
      if (generation === this.generation)
        this.onState({
          estado: "vermelho",
          cantos: [],
          mensagem: `Enquadramento não validado: ${error.message}`,
        });
    } finally {
      if (this.stream && generation === this.generation)
        this.timer = this.schedule(() => this.tick(generation), 1200);
    }
  }
  async capture() {
    if (!this.stream) throw new Error("Ative a câmera antes de fotografar.");
    return this.snapshot(this.video);
  }
  stop() {
    this.generation += 1;
    this.cancel(this.timer);
    this.controller?.abort();
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
    this.video.srcObject = null;
    this.onState({
      estado: "vermelho",
      cantos: [],
      mensagem: "Câmera desligada.",
    });
  }
}
