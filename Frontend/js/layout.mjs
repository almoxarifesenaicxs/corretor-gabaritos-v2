// Comportamento exclusivamente visual: não altera abas, câmera ou dados.
const sidebar = document.getElementById("sidebar");
const toggle = document.getElementById("sidebar-toggle");
const backdrop = document.getElementById("sidebar-backdrop");
const mobile = window.matchMedia("(max-width: 760px)");
let desktopCollapsed = false;

function setCollapsed(collapsed) {
  document.body.classList.toggle("sidebar-collapsed", collapsed);
  toggle.setAttribute("aria-expanded", String(!collapsed));
  const label = collapsed ? "Expandir menu" : "Recolher menu";
  toggle.setAttribute("aria-label", label);
  toggle.title = label;
  backdrop.hidden = !mobile.matches || collapsed;
  // No celular o menu fechado não deve receber foco nem interceptar cliques.
  sidebar.inert = mobile.matches && collapsed;
  if (mobile.matches && collapsed && sidebar.contains(document.activeElement)) {
    toggle.focus();
  }
  if (mobile.matches && !collapsed) {
    sidebar.querySelector("button:not(:disabled)")?.focus();
  }
}

toggle.addEventListener("click", () => {
  const collapsed = !document.body.classList.contains("sidebar-collapsed");
  if (!mobile.matches) desktopCollapsed = collapsed;
  setCollapsed(collapsed);
});
backdrop.addEventListener("click", () => setCollapsed(true));
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && mobile.matches) setCollapsed(true);
});
sidebar.querySelectorAll("[data-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    if (mobile.matches) setCollapsed(true);
  });
});
mobile.addEventListener("change", () => {
  setCollapsed(mobile.matches || desktopCollapsed);
});
setCollapsed(mobile.matches);
