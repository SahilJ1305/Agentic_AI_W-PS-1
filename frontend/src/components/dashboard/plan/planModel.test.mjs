import test from 'node:test';
import assert from 'node:assert/strict';
import { AUTO_ACCEPT_CONFIDENCE, buildPlanModel, initialDecisions, initials, layoutLayers, ownerStyle, pairKey } from './planModel.js';

const task = (key, hours, owner = '') => ({ key, title: `Task ${key}`, estimate_hours: hours, owner_name: owner });
const dep = (upstream, downstream, extra = {}) => ({ upstream, downstream, type: 'hard', confidence: 0.9, ...extra });

// T1 -> T2 -> T4 (long), T1 -> T3 -> T4 (short), T4 -> T5
const draft = {
  tasks: [task('T1', 2, 'Ann'), task('T2', 8, 'Ann'), task('T3', 1, 'Bo'), task('T4', 3, 'Bo'), task('T5', 2)],
  dependencies: [dep('T1', 'T2'), dep('T1', 'T3'), dep('T2', 'T4'), dep('T3', 'T4'), dep('T4', 'T5', { confidence: 0.6 })],
};
const all = (value) => Object.fromEntries(draft.dependencies.map((d) => [pairKey(d), value]));

test('edges at or above the threshold start accepted, the rest wait for review', () => {
  const d = initialDecisions(draft);
  assert.equal(d['T1>T2'], true);
  assert.equal(d['T4>T5'], false);
  assert.equal(AUTO_ACCEPT_CONFIDENCE, 0.8);
  assert.equal(initialDecisions({ dependencies: [dep('A', 'B', { confidence: 0.8 })] })['A>B'], true);   // exactly at the line
  assert.equal(initialDecisions({ dependencies: [{ upstream: 'A', downstream: 'B' }] })['A>B'], true);     // no confidence = certain
});

test('the critical path is the longest chain by estimated hours, not by number of steps', () => {
  const m = buildPlanModel(draft, all(true));
  assert.deepEqual(m.criticalPath.keys, ['T1', 'T2', 'T4', 'T5']);
  assert.equal(m.criticalPath.hours, 2 + 8 + 3 + 2);
  assert.ok(m.criticalPairs.has('T2>T4') && !m.criticalPairs.has('T3>T4'));
});

test('rejecting an edge changes the path and the stages', () => {
  const m = buildPlanModel(draft, { ...all(true), 'T2>T4': false });
  // T2 no longer feeds T4, but T1 -> T2 (10 h) is now longer than T1 -> T3 -> T4 -> T5 (8 h)
  assert.deepEqual(m.criticalPath.keys, ['T1', 'T2']);
  assert.equal(m.criticalPath.hours, 10);
  const slower = buildPlanModel({ ...draft, tasks: draft.tasks.map((t) => (t.key === 'T2' ? { ...t, estimate_hours: 1 } : t)) },
    { ...all(true), 'T2>T4': false });
  assert.deepEqual(slower.criticalPath.keys, ['T1', 'T3', 'T4', 'T5']);   // with a short T2 the long chain wins again
  assert.equal(m.stage.get('T2'), 1);
  assert.equal(m.stage.get('T4'), 2);
  assert.equal(m.totals.rejected, 1);
});

test('soft dependencies never block: not in stages or the critical path', () => {
  const soft = { tasks: [task('A', 1), task('B', 5)], dependencies: [dep('A', 'B', { type: 'soft' })] };
  const m = buildPlanModel(soft, { 'A>B': true });
  assert.equal(m.stage.get('B'), 0);
  assert.deepEqual(m.criticalPath.keys, []);
  assert.deepEqual(m.waitsFor('B'), []);
  assert.ok(m.relatedTo('A').has('B'));          // but it still shows as related when highlighting
});

test('stages group tasks that can start together', () => {
  const m = buildPlanModel(draft, all(true));
  assert.deepEqual(m.stages.map((s) => s.map((t) => t.key)), [['T1'], ['T2', 'T3'], ['T4'], ['T5']]);
  assert.deepEqual(m.waitsFor('T4').sort(), ['T2', 'T3']);
  assert.deepEqual(m.unlocks('T1').sort(), ['T2', 'T3']);
});

test('without estimates the path counts steps instead of hours', () => {
  const m = buildPlanModel({ tasks: [task('A'), task('B'), task('C')], dependencies: [dep('A', 'B'), dep('B', 'C')] }, { 'A>B': true, 'B>C': true });
  assert.deepEqual(m.criticalPath.keys, ['A', 'B', 'C']);
  assert.equal(m.criticalPath.hours, 0);
});

test('a dependency cycle, unknown tasks, self links and duplicates do not break anything', () => {
  const messy = {
    tasks: [task('A', 1), task('B', 1), task('C', 1)],
    dependencies: [dep('A', 'B'), dep('B', 'A'), dep('B', 'C'), dep('Z', 'A'), dep('C', 'C'), dep('B', 'C')],
  };
  const decisions = { 'A>B': true, 'B>A': true, 'B>C': true };
  const m = buildPlanModel(messy, decisions);
  assert.equal(m.edges.length, 3);                       // Z>A, C>C and the duplicate are dropped
  assert.deepEqual(m.onCycle.sort(), ['A', 'B', 'C']);
  assert.ok([...m.stage.values()].every(Number.isFinite));
  const layout = layoutLayers(['A', 'B', 'C'], m.edges);
  assert.equal(layout.positions.size, 3);
});

test('workload follows the owners chosen on screen, and unassigned work is kept apart', () => {
  const m = buildPlanModel(draft, all(true), { T2: 'Cy', T5: 'Cy' });
  const by = Object.fromEntries(m.workload.map((w) => [w.name, w]));
  assert.equal(by.Ann.hours, 2);
  assert.equal(by.Cy.hours, 8 + 2);
  assert.equal(by.Bo.tasks, 2);
  assert.equal(m.workload.at(-1).name === '' || !('' in by), true);
  const none = buildPlanModel(draft, all(true));
  assert.equal(none.totals.unassigned, 1);
  assert.equal(none.workload.at(-1).name, '');           // unassigned always last
  assert.equal(none.totals.hours, 16);
  assert.equal(none.totals.needsReview, 1);
});

test('layout puts every task to the right of the tasks it waits for, with no overlaps', () => {
  const m = buildPlanModel(draft, all(true));
  const { positions, width, height } = layoutLayers(m.tasks.map((t) => t.key), m.edges);
  m.edges.forEach((e) => assert.ok(positions.get(e.upstream).x < positions.get(e.downstream).x));
  const seen = new Set();
  positions.forEach((p) => { const id = `${p.x},${p.y}`; assert.ok(!seen.has(id)); seen.add(id); });
  assert.ok(width > 0 && height > 0);
});

test('owner colours are stable, and people without an owner are grey', () => {
  assert.deepEqual(ownerStyle('Priya'), ownerStyle('Priya'));
  assert.notDeepEqual(ownerStyle(''), ownerStyle('Priya'));
  assert.equal(initials('Sahil Jagtap'), 'SJ');
  assert.equal(initials(''), '?');
});
