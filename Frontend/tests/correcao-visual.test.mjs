import test from "node:test";
import assert from "node:assert/strict";
import {
  COLORS,
  drawAnnotations,
  manualAnswer,
} from "../js/correcao-visual.mjs";

test("cores e números usam as caixas detectadas sem alterar a imagem", () => {
  const draws = [],
    labels = [],
    image = { width: 400, height: 500 };
  const ctx = {
    clearRect() {},
    drawImage(value) {
      assert.equal(value, image);
    },
    strokeRect(...box) {
      draws.push({ box, color: this.strokeStyle });
    },
    fillText(text) {
      labels.push(text);
    },
  };
  const positions = {},
    marks = {};
  for (const [index, state] of [
    "correta",
    "incorreta",
    "pendente",
    "branco",
  ].entries()) {
    const number = String(index + 1);
    positions[number] = {
      A: { x: 40, y: 50 + index * 40, largura: 20, altura: 20 },
    };
    marks[number] = {
      estado: state,
      alternativas: state === "branco" ? [] : ["A"],
    };
  }
  const before = structuredClone(positions);
  assert.equal(drawAnnotations(ctx, image, positions, marks), 4);
  assert.deepEqual(
    draws.map((d) => d.color),
    Object.values(COLORS),
  );
  assert.deepEqual(draws[1].box, [40, 90, 20, 20]);
  assert.deepEqual(labels, ["1+", "2x", "3?", "4-"]);
  assert.deepEqual(positions, before);
});

test("questão sem posição segura permanece sem anotação", () => {
  const ctx = {
    clearRect() {},
    drawImage() {},
    strokeRect() {
      assert.fail("Não pode desenhar");
    },
  };
  assert.equal(
    drawAnnotations(
      ctx,
      { width: 100, height: 100 },
      {},
      { 1: { estado: "correta", alternativas: ["A"] } },
    ),
    0,
  );
});

test("conferência manual preserva original e não resolve pendência por suposição", () => {
  const original = {
    resposta: null,
    estado: "multipla",
    alternativas: ["A", "B"],
  };
  assert.deepEqual(manualAnswer(original, "original"), original);
  assert.deepEqual(manualAnswer(original, "C"), {
    resposta: "C",
    estado: "marcada",
    alternativas: ["C"],
  });
  assert.deepEqual(manualAnswer(original, "branco"), {
    resposta: null,
    estado: "branco",
    alternativas: [],
  });
  assert.equal(original.resposta, null);
  assert.throws(() => manualAnswer(original, "F"));
});
