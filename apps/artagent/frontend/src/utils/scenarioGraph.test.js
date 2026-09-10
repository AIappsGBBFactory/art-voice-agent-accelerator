import test from 'node:test';
import assert from 'node:assert/strict';
import { scenarioAgentNames, scenarioGraphPreview } from './scenarioGraph.js';

test('graph membership includes isolated members, the start, and referenced agents only once', () => {
  assert.deepEqual(scenarioAgentNames({
    agents: ['Isolated', 'Start'],
    start_agent: 'Start',
    handoffs: [{ from_agent: 'Start', to_agent: 'Specialist' }, { from_agent: '', to_agent: '' }],
  }), ['Isolated', 'Start', 'Specialist']);
  assert.deepEqual(scenarioAgentNames(null), []);
});

test('preview prioritizes the real start and first-hop agents without changing the full graph', () => {
  const config = {
    agents: ['Isolated', 'Deep', 'Start', 'Accounts', 'Support'],
    start_agent: 'Start',
    handoffs: [
      { from_agent: 'Start', to_agent: 'Accounts', handoff_condition: 'An account question.' },
      { from_agent: 'Start', to_agent: 'Support', type: 'discrete', handoff_condition: 'Needs support.' },
      { from_agent: 'Support', to_agent: 'Deep' },
    ],
  };
  const before = structuredClone(config);
  const preview = scenarioGraphPreview(config);
  assert.deepEqual(preview.nodes.map((node) => node.name), ['Start', 'Accounts', 'Support']);
  assert.equal(preview.agentCount, 5);
  assert.equal(preview.handoffCount, 3);
  assert.equal(preview.edges.length, 2);
  assert.equal(preview.edges[1].handoff_condition, 'Needs support.');
  assert.equal(preview.edges[1].type, 'discrete');
  assert.deepEqual(config, before);
});

test('an isolated member never gains a fabricated handoff in the preview', () => {
  const preview = scenarioGraphPreview({
    start_agent: 'Start', agents: ['Start', 'Isolated'], handoffs: [],
  });
  assert.equal(preview.nodes.length, 2);
  assert.equal(preview.edges.length, 0);
  assert.equal(preview.handoffCount, 0);
});

test('single-agent and empty previews have honest membership and no invented routes', () => {
  const single = scenarioGraphPreview({ start_agent: 'Solo', agents: ['Solo'] });
  assert.equal(single.nodes.length, 1);
  assert.equal(single.nodes[0].isStart, true);
  assert.equal(single.nodes[0].x + single.nodes[0].width / 2, single.width / 2);
  assert.equal(single.handoffCount, 0);
  assert.equal(scenarioGraphPreview({}).nodes.length, 0);
});

test('preview distinguishes unavailable tool metadata from a known empty selection', () => {
  const preview = scenarioGraphPreview({ agents: ['Unknown', 'Empty', 'Configured'] }, [
    { name: 'Empty', tools: [] },
    { name: 'Configured', tools: ['lookup', 'lookup', 'handoff_to_agent'] },
  ]);
  assert.deepEqual(preview.nodes.map((node) => node.toolCount), [null, 0, 2]);
});

test('readable preview labels preserve the actual agent identifiers', () => {
  const preview = scenarioGraphPreview({ agents: ['BankingConcierge', 'Fraud_Agent'] });
  assert.deepEqual(preview.nodes.map((node) => [node.name, node.label]), [
    ['BankingConcierge', 'Banking Concierge'],
    ['Fraud_Agent', 'Fraud Agent'],
  ]);
});

test('both handoff directions remain distinct and every node stays inside the thumbnail', () => {
  const preview = scenarioGraphPreview({
    start_agent: 'Start',
    agents: ['Start', 'Support', 'Specialist'],
    handoffs: [
      { from_agent: 'Start', to_agent: 'Support' },
      { from_agent: 'Support', to_agent: 'Start' },
      { from_agent: 'Support', to_agent: 'Specialist' },
      { from_agent: 'Specialist', to_agent: 'Support' },
    ],
  });
  assert.equal(new Set(preview.edges.map((edge) => edge.path)).size, 4);
  for (const node of preview.nodes) {
    assert.ok(node.x >= 0 && node.y >= 0);
    assert.ok(node.x + node.width <= preview.width);
    assert.ok(node.y + node.height <= preview.height);
  }
});
