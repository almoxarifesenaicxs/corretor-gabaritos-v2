import test from "node:test";
import assert from "node:assert/strict";
import { createRecovery, recoveryAvailable } from "../js/recuperacao.mjs";

function storage() {
  const values = new Map();
  return {
    getItem: key => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
    values,
  };
}
const payload = (id = "11111111-1111-4111-8111-111111111111") => ({
  operacao_id: id, prova_id: "prova", aluno: "Aluno fictício", aluno_id: null,
  novo_homonimo: false, resultado: { resumo: { pontuacao: 40 } },
  respostas: { "1": { resposta: "A" } }, comprovante: "a".repeat(64),
  confirmado: true, permitir_provisorio: false, imagem: "NÃO GUARDAR",
});

test("operação pendente sobrevive a novo objeto e não guarda imagens", () => {
  const store = storage();
  const first = createRecovery({ storage: store, enabled: true });
  first.preserve(payload());
  const restarted = createRecovery({ storage: store, enabled: true });
  assert.equal(restarted.list().length, 1);
  assert.equal(restarted.matching(payload()), payload().operacao_id);
  assert.equal(restarted.get(payload().operacao_id).imagem, undefined);
  assert.equal(store.values.values().next().value.includes("NÃO GUARDAR"), false);
  first.preserve(payload());
  assert.equal(restarted.list().length, 1);
  restarted.confirm(payload().operacao_id);
  assert.equal(first.list().length, 0);
});

test("payload diferente não reutiliza ID e falha de armazenamento impede envio", () => {
  const store = storage();
  const recovery = createRecovery({ storage: store, enabled: true });
  recovery.preserve(payload());
  assert.throws(() => recovery.preserve({ ...payload(), aluno: "Outro aluno" }), /outra correção/);
  assert.equal(recovery.matching({ ...payload(), aluno: "Outro aluno" }), null);
  const broken = createRecovery({ storage: {
    getItem: () => null, setItem: () => { throw new Error("disco cheio"); },
  }, enabled: true });
  assert.throws(() => broken.preserve(payload()), /envio foi bloqueado/);
});

test("armazenamento durável é ativado no loopback e na Vercel autenticada", () => {
  assert.equal(recoveryAvailable("", { hostname: "127.0.0.1" }), true);
  assert.equal(recoveryAvailable("https://api.example", { hostname: "127.0.0.1" }), false);
  assert.equal(recoveryAvailable("", { hostname: "frontend.example" }), false);
  assert.equal(recoveryAvailable("https://api.example", { hostname: "frontend.example", protocol: "https:" }), true);
  assert.equal(recoveryAvailable("http://api.example", { hostname: "frontend.example", protocol: "https:" }), false);
});

test("recuperação de lote preserva origem e operação sem guardar imagem", () => {
  const store = storage();
  const recovery = createRecovery({ storage: store, enabled: true });
  const origem_lote = { lote_id: "a".repeat(32), indice: 0, imagem_sha256: "b".repeat(64) };
  const entrada = { ...payload(), origem_lote };
  recovery.preserve(entrada);
  const reiniciado = createRecovery({ storage: store, enabled: true });
  assert.deepEqual(reiniciado.get(entrada.operacao_id).origem_lote, origem_lote);
  assert.equal(reiniciado.get(entrada.operacao_id).operacao_id, entrada.operacao_id);
  assert.equal(reiniciado.get(entrada.operacao_id).imagem, undefined);
});
