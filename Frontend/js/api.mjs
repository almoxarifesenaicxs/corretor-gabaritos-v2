export async function request(url, options = {}) {
  const response = await fetch(url, options);
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail =
      typeof data?.detail === "string"
        ? data.detail
        : "Confira os campos e tente novamente.";
    const error = new Error(data?.detail?.mensagem || detail);
    error.details = data?.detail;
    throw error;
  }
  if (data === null)
    throw new Error("Resposta incompleta do servidor. Confira o histórico ou reenvie a mesma operação.");
  return data;
}

export function jsonPost(url, data) {
  return request(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export function upload(url, file, fields = {}, signal) {
  const body = new FormData();
  body.append("arquivo", file, file.name || "captura.png");
  for (const [name, value] of Object.entries(fields))
    body.append(name, String(value));
  return request(url, { method: "POST", body, signal });
}

export function validateFile(file) {
  if (!file || !/\.(pdf|png|jpe?g)$/i.test(file.name))
    throw new Error("Selecione PDF, JPG ou PNG.");
  if (file.size === 0) throw new Error("O arquivo está vazio.");
  if (file.size > 10 * 1024 * 1024)
    throw new Error("O limite é de 10 MiB por arquivo.");
  return file;
}

export function officialFromSelections(values) {
  if (values.length !== 50 || values.some((value) => !/^[A-E]$/.test(value))) {
    throw new Error(
      "Confira e preencha uma alternativa válida em cada uma das 50 questões.",
    );
  }
  return Object.fromEntries(
    values.map((value, index) => [String(index + 1), value]),
  );
}
