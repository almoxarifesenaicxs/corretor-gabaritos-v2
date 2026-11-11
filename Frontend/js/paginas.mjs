const fragments = [
  "../pages/avaliacoes.html",
  "../pages/correcao.html",
  "../pages/alunos.html",
  "../components/captura.html",
];

export function tabFromHash(hash) {
  const tab = hash.replace(/^#/, "");
  return ["avaliacoes", "correcao", "alunos"].includes(tab) ? tab : "avaliacoes";
}

export async function loadPages({ root = document, fetcher = fetch } = {}) {
  const contents = await Promise.all(
    fragments.map(async (path) => {
      const response = await fetcher(new URL(path, import.meta.url));
      if (!response.ok) throw new Error("Falha ao carregar a interface.");
      return response.text();
    }),
  );
  const replacements = [];
  const names = new Set();
  for (const html of contents) {
    const fragment = root.createElement("template");
    fragment.innerHTML = html;
    for (const template of fragment.content.querySelectorAll(
      "template[data-slot]",
    )) {
      const name = template.dataset.slot;
      const slot = root.querySelector(`template[data-page-slot="${name}"]`);
      if (!slot || names.has(name))
        throw new Error("Estrutura de página inválida.");
      names.add(name);
      replacements.push([slot, template.content]);
    }
  }
  if (
    replacements.length !==
    root.querySelectorAll("template[data-page-slot]").length
  )
    throw new Error("Página incompleta.");
  // No wrappers: preserve the existing CSS layout and DOM order.
  for (const [slot, content] of replacements) slot.replaceWith(content);
}
