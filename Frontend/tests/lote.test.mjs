import test from "node:test";
import assert from "node:assert/strict";
import { Lote } from "../js/lote.mjs";

const manifesto = () => ({ lote_id: "a".repeat(32), total: 3, imagens: [
  { nome: "01.png", estado: "pendente" },
  { nome: "02.jpg", estado: "pendente" },
  { nome: "erro.txt", estado: "falha", erro: "Formato não suportado." },
] });

test("lote é sequencial, exige revisão e conta confirmações sem salvar automaticamente", () => {
  const lote = new Lote(manifesto());
  assert.equal(lote.proxima().indice, 0);
  assert.equal(lote.proxima(), null);
  lote.pronta();
  lote.processada();
  assert.deepEqual(lote.resumo(), { entradas: 3, identificadas: 2, processadas: 1,
    confirmadas: 0, pendentes_revisao: 1, falhas: 1, canceladas: 0 });
  lote.confirmada("11111111-1111-4111-8111-111111111111");
  assert.equal(lote.resumo().confirmadas, 1);
  lote.pausado = true;
  assert.equal(lote.proxima(), null);
  lote.pausado = false;
  assert.equal(lote.proxima().indice, 1);
  lote.falha("OCR indisponível");
  assert.equal(lote.resumo().falhas, 2);
  assert.equal(lote.repetir(1), true);
  assert.equal(lote.proxima().indice, 1);
  lote.cancelar();
  assert.equal(lote.resumo().confirmadas, 1);
  assert.equal(lote.resumo().canceladas, 1);
  assert.equal(lote.proxima(), null);
});

test("mensagem antiga para PDF em subpasta identifica backend desatualizado", () => {
  const nome = "Nova pasta/Grade_de_respostas_com_linhas (1).pdf";
  const lote = new Lote({ lote_id: "b".repeat(32), total: 2, imagens: [
    { nome, estado: "falha", erro: "Formato não suportado. Use JPG ou PNG." },
    { nome: "foto.png", estado: "pendente" },
  ] });
  assert.match(lote.imagens[0].erro, /Reinicie o backend local/);
  assert.equal(lote.imagens[0].estado, "falha");
  assert.equal(lote.imagens[1].estado, "pendente");
});

test("dez lotes de cem preservam contagens em pausa, cancelamento e reimportação", () => {
  let confirmadas = 0;
  const ids = new Set();
  for (let bloco = 0; bloco < 10; bloco++) {
    const manifesto = { lote_id: (bloco + 1).toString(16).padStart(32, "0"), total: 100,
      imagens: Array.from({ length: 100 }, (_, indice) =>
        ({ indice, nome: `gabarito-${bloco * 100 + indice + 1}.jpg`, estado: "pendente" })) };
    const lote = new Lote(manifesto);
    for (let indice = 0; indice < 100; indice++) {
      if (indice === 50) {
        lote.pausado = true;
        assert.equal(lote.proxima(), null);
        lote.pausado = false;
      }
      assert.equal(lote.proxima().indice, indice);
      lote.pronta();
      lote.processada();
      assert.equal(lote.resumo().confirmadas, indice);
      const operacao = (bloco * 100 + indice + 1).toString(16).padStart(8, "0") +
        "-0000-4000-8000-000000000001";
      lote.confirmada(operacao);
      assert.equal(ids.has(operacao), false);
      ids.add(operacao);
    }
    confirmadas += lote.resumo().confirmadas;
    lote.cancelar();
    assert.equal(lote.resumo().confirmadas, 100);
    assert.equal(lote.resumo().canceladas, 0);
  }
  assert.equal(confirmadas, 1000);
  assert.equal(ids.size, 1000);
  // Reimportar cria estado de revisão novo; o cliente não pode inferir que
  // registros antigos já foram salvos sem consultar a operação pendente.
  const reimportado = new Lote({ lote_id: "f".repeat(32), total: 1,
    imagens: [{ nome: "gabarito-1.jpg", estado: "pendente" }] });
  assert.equal(reimportado.resumo().confirmadas, 0);
  assert.equal(reimportado.proxima().indice, 0);
  reimportado.cancelar();
  assert.equal(reimportado.resumo().canceladas, 1);
});
