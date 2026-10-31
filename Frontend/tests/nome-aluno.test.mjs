import test from 'node:test';
import assert from 'node:assert/strict';
import {StudentNameReader} from '../js/nome-aluno.mjs';

function setup(recognize) {
  const field = new EventTarget(); field.value = '';
  const status = {textContent: ''}, pending = [];
  let changed = 0;
  const reader = new StudentNameReader({field, status, recognize,
    onChange: () => changed++, onPending: value => pending.push(value)});
  return {reader, field, status, pending, changed: () => changed};
}

test('preenche sugestão e preserva a edição manual', async () => {
  const {reader, field, changed} = setup(async () => ({estado: 'sugerido', nome: 'Maria Silva', mensagem: 'Confira'}));
  await reader.read(new Blob(), {captura: true});
  assert.equal(field.value, 'Maria Silva'); assert.equal(changed(), 1);
  field.value = 'Maria da Silva'; field.dispatchEvent(new Event('input'));
  await reader.read(new Blob(), {captura: true});
  assert.equal(field.value, 'Maria da Silva');
});

test('falha ou baixa confiança mantém nome vazio', async () => {
  for (const recognize of [async () => ({estado: 'baixa_confianca', nome: null, mensagem: 'Digite manualmente'}),
    async () => {throw new Error('offline');}]) {
    const {reader, field, status, pending} = setup(recognize);
    await reader.read(new Blob(), {});
    assert.equal(field.value, ''); assert.match(status.textContent, /manualmente/);
    assert.equal(pending.at(-1), false);
  }
});

test('resposta atrasada não sobrescreve digitação nem outra captura', async () => {
  let finish;
  const {reader, field} = setup(() => new Promise(resolve => {finish = resolve;}));
  const old = reader.read(new Blob(), {});
  field.value = 'Aluno digitado'; field.dispatchEvent(new Event('input'));
  finish({estado: 'sugerido', nome: 'Nome antigo'}); await old;
  assert.equal(field.value, 'Aluno digitado');
  field.value = '';
  const other = reader.read(new Blob(), {});
  reader.clear();
  finish({estado: 'sugerido', nome: 'Outro nome antigo'}); await other;
  assert.equal(field.value, '');
});

test('trocar captura remove sugestão anterior não editada', async () => {
  const {reader, field} = setup(async () => ({estado: 'sugerido', nome: 'Maria Silva'}));
  await reader.read(new Blob(), {});
  reader.clear();
  assert.equal(field.value, '');
});
