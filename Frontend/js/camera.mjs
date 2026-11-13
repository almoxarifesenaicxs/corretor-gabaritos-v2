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
    canvas.toBlob((blob) => {
      canvas.width = canvas.height = 0;
      if (blob) resolve(blob);
      else reject(new Error("Não foi possível capturar a imagem."));
    }, "image/png"),
  );
}

export function cameraError(error) {
  return (
    {
      NotAllowedError:
        "Permissão da câmera negada. Libere o acesso no navegador ou envie um arquivo.",
      NotFoundError:
        "Nenhuma câmera foi encontrada. Conecte uma câmera ou envie um arquivo.",
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
        "Câmera exige HTTPS ou localhost e navegador compatível.",
      );
    const stream = await this.mediaDevices.getUserMedia({
      audio: false,
      video: {
        ...(deviceId
          ? { deviceId: { exact: deviceId } }
          : { facingMode: { ideal: "environment" } }),
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
    for (const track of stream.getTracks()) {
      track.addEventListener?.("ended", () => {
        if (generation !== this.generation) return;
        this.stop();
        this.onState({ estado: "vermelho", cantos: [],
          mensagem: "Câmera desconectada. Reconecte-a ou envie um arquivo." });
      });
    }
    let cancelPlayback;
    const cancelled = new Promise(resolve => {
      cancelPlayback = () => resolve(false);
    });
    this.cancelPlayback = cancelPlayback;
    try {
      const played = await Promise.race([
        Promise.resolve().then(() => this.video.play()).then(() => true), cancelled,
      ]);
      if (!played || generation !== this.generation) return false;
    } catch (error) {
      if (generation !== this.generation) return false;
      this.stop();
      throw error;
    } finally {
      if (this.cancelPlayback === cancelPlayback) this.cancelPlayback = null;
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
    const controller = new AbortController();
    this.controller = controller;
    let nextDelay = 3000;
    try {
      const blob = await this.snapshot(this.video, 800);
      if (generation !== this.generation) return;
      const data = await this.analyze(blob, controller.signal);
      if (generation === this.generation) this.onState(data);
    } catch (error) {
      nextDelay = error.message === "Aguarde a imagem da câmera." ? 1000 : 5000;
      if (generation === this.generation)
        this.onState({
          estado: "vermelho",
          cantos: [],
          mensagem: `Enquadramento não validado: ${error.message}`,
        });
    } finally {
      if (this.controller === controller) this.controller = null;
      if (this.stream && generation === this.generation)
        this.timer = this.schedule(() => this.tick(generation), nextDelay);
    }
  }
  async capture() {
    if (!this.stream) throw new Error("Ative a câmera antes de fotografar.");
    const generation = this.generation;
    const blob = await this.snapshot(this.video);
    if (generation !== this.generation) throw new DOMException("Captura encerrada.", "AbortError");
    return blob;
  }
  stop() {
    this.generation += 1;
    this.cancel(this.timer);
    this.cancelPlayback?.();
    this.cancelPlayback = null;
    this.controller?.abort();
    this.controller = null;
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
