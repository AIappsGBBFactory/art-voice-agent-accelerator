import { test, expect } from '@playwright/test';
import { AGENT_CONFIG, installQuickTuneMocks } from './helpers/quick-tune-mocks.js';
import { layoutViolations } from './helpers/authoring-layout.js';

async function openTune(page) {
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
  return page.getByRole('complementary', { name: 'Quick Tune workspace' });
}

for (const viewport of [
  { name: 'desktop', width: 1600, height: 1000 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  test(`shows a readable, keyboard-accessible scenario preview on ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const state = await installQuickTuneMocks(page);
    const errors = [];
    page.on('pageerror', (error) => errors.push(error.message));
    const panel = await openTune(page);
    const preview = panel.getByRole('button', { name: 'Open graphical editor for Banking', exact: true });
    await expect(preview).toBeInViewport({ ratio: 0.99 });
    await expect(preview).toContainText('2 agents / 1 handoff');
    await expect(preview.getByTestId('scenario-preview-node-BankingConcierge')).toContainText('Start / 2 tools');
    await expect(preview.getByTestId('scenario-preview-edge-BankingConcierge-FraudAgent')).toHaveCount(1);
    expect(await layoutViolations(panel)).toEqual([]);
    await page.screenshot({ path: testInfo.outputPath(`scenario-preview-${viewport.name}.png`) });

    await preview.focus();
    await page.keyboard.press('Enter');
    const graph = page.getByRole('dialog', { name: 'Graphical editor - Banking', exact: true });
    await expect(graph.getByTestId('graph-node-FraudAgent')).toBeVisible();
    await graph.getByRole('button', { name: 'Close graphical editor', exact: true }).click();
    await expect(preview).toBeFocused();
    await expect(panel.getByRole('tab', { name: 'Edit scenario', exact: true })).toHaveAttribute('aria-selected', 'true');
    expect(state.scenarios.calls.filter((call) => call.method !== 'GET')).toEqual([]);
    expect(state.calls).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test('shows the selected session override rather than a different active or template scenario', async ({ page }) => {
  const state = await installQuickTuneMocks(page);
  state.agents.HealthConcierge = { ...structuredClone(AGENT_CONFIG), name: 'HealthConcierge', tools: [] };
  state.scenarioConfigs.healthcare = {
    ...state.scenarios.scenariosResponse.builtin_scenarios.find((item) => item.name === 'Healthcare'),
    agents: ['HealthConcierge'], handoffs: [], description: 'My saved healthcare scenario.',
  };
  const panel = await openTune(page);
  await panel.getByRole('tab', { name: 'Edit scenario', exact: true }).click();
  await panel.getByRole('combobox', { name: 'Scenario to edit', exact: true }).fill('Healthcare');
  await page.getByRole('option', { name: 'Healthcare', exact: true }).click();
  const preview = panel.getByRole('button', { name: 'Open graphical editor for Healthcare', exact: true });
  await expect(preview).toContainText('1 agent / 0 handoffs');
  await expect(preview.getByTestId('scenario-preview-node-HealthConcierge')).toContainText('Start / 0 tools');
  await expect(preview.locator('[data-testid^="scenario-preview-edge-"]')).toHaveCount(0);
  await panel.getByRole('tab', { name: 'Tune agent', exact: true }).click();
  await preview.click();
  const graph = page.getByRole('dialog', { name: 'Graphical editor - Healthcare', exact: true });
  await expect(graph.getByTestId('graph-node-HealthConcierge')).toBeVisible();
  expect(state.scenarios.scenariosResponse.active_scenario).toBe('Banking');
  expect(state.scenarios.calls.filter((call) => call.method !== 'GET')).toEqual([]);
});

test('reflects unsaved handoff edits, preserves canvas positions, and only writes on Save', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 });
  const state = await installQuickTuneMocks(page);
  const panel = await openTune(page);
  const preview = panel.getByTestId('scenario-graph-preview');
  await preview.click();
  const graph = page.getByRole('dialog', { name: 'Graphical editor - Banking', exact: true });
  const node = graph.getByTestId('graph-node-FraudAgent');
  const initial = await node.boundingBox();
  await page.mouse.move(initial.x + initial.width / 2, initial.y + initial.height / 2);
  await page.mouse.down();
  await page.mouse.move(initial.x + initial.width / 2 + 100, initial.y + initial.height / 2 + 70, { steps: 8 });
  await page.mouse.up();
  const dragged = await node.boundingBox();
  expect(dragged.x - initial.x).toBeCloseTo(100, 0);

  await graph.getByTestId('graph-edge-BankingConcierge-FraudAgent').click();
  const handoff = page.getByRole('dialog', { name: 'Edit Handoff', exact: true });
  await handoff.getByRole('textbox', { name: 'Handoff condition', exact: true }).fill('The caller reports an unauthorized payment.');
  await handoff.getByRole('button', { name: 'Save Changes', exact: true }).click();
  await graph.getByRole('button', { name: 'Close graphical editor', exact: true }).click();
  await expect(preview.getByText('Draft', { exact: true })).toBeVisible();
  await expect(preview.getByTestId('scenario-preview-edge-BankingConcierge-FraudAgent'))
    .toContainText('The caller reports an unauthorized payment.');
  expect(state.scenarios.calls.filter((call) => call.method !== 'GET')).toEqual([]);

  await preview.click();
  const reopened = await node.boundingBox();
  expect(Math.round(reopened.x)).toBe(Math.round(dragged.x));
  expect(Math.round(reopened.y)).toBe(Math.round(dragged.y));
  await graph.getByRole('button', { name: 'Save scenario', exact: true }).click();
  await expect.poll(() => state.scenarios.calls.filter((call) => call.type === 'update').length).toBe(1);
  expect(state.scenarios.calls.find((call) => call.type === 'update').body.handoffs[0].handoff_condition)
    .toBe('The caller reports an unauthorized payment.');
  await graph.getByRole('button', { name: 'Close graphical editor', exact: true }).click();
  await expect(preview.getByText('Draft', { exact: true })).toHaveCount(0);
});

test('bounds large and long-named scenarios without inventing handoffs or losing full editor membership', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const state = await installQuickTuneMocks(page);
  const longName = 'CustomerAccountSpecialistWithAnExtremelyLongUnbrokenName';
  const names = ['BankingConcierge', longName, 'FraudAgent', 'IsolatedGuide', 'PaymentGuide', 'AccountGuide'];
  names.forEach((name) => { state.agents[name] = { ...structuredClone(AGENT_CONFIG), name }; });
  state.scenarioConfigs.banking = {
    ...state.scenarios.scenariosResponse.builtin_scenarios[0],
    agents: names,
    handoffs: [{ from_agent: 'BankingConcierge', to_agent: longName, handoff_condition: 'Needs account help.' }],
  };
  const panel = await openTune(page);
  const preview = panel.getByTestId('scenario-graph-preview');
  await expect(preview).toContainText('3 of 6 agents shown / 1 handoff');
  await expect(preview.locator('[data-testid^="scenario-preview-node-"]')).toHaveCount(3);
  await expect(preview.locator('[data-testid^="scenario-preview-edge-"]')).toHaveCount(1);
  expect(await layoutViolations(panel)).toEqual([]);
  const textBounds = await preview.getByTestId(`scenario-preview-node-${longName}`)
    .locator('foreignObject').boundingBox();
  const previewBounds = await preview.boundingBox();
  expect(textBounds.x + textBounds.width).toBeLessThanOrEqual(previewBounds.x + previewBounds.width);
  await preview.click();
  const graph = page.getByRole('dialog', { name: 'Graphical editor - Banking', exact: true });
  await expect(graph.locator('[data-testid^="graph-node-"]')).toHaveCount(6);
  await expect(graph.getByTestId('graph-edge-BankingConcierge-IsolatedGuide')).toHaveCount(0);
});

test('allows tuning while preview loading fails and retries without losing agent edits', async ({ page }) => {
  const state = await installQuickTuneMocks(page);
  state.scenarioLoadError = 'Scenario storage is temporarily unavailable.';
  const panel = await openTune(page);
  await expect(panel.getByText(`Scenario preview unavailable: ${state.scenarioLoadError}`, { exact: true })).toBeVisible();
  await panel.getByRole('button', { name: /^Behavior/ }).click();
  const instructions = panel.getByRole('textbox', { name: 'Instructions', exact: true });
  await instructions.fill('Keep this agent draft while retrying the scenario preview.');
  state.scenarioLoadError = null;
  await panel.getByRole('button', { name: 'Retry preview', exact: true }).click();
  await expect(panel.getByTestId('scenario-graph-preview')).toContainText('2 agents / 1 handoff');
  await expect(instructions).toHaveValue('Keep this agent draft while retrying the scenario preview.');
  expect(state.calls).toEqual([]);
  expect(state.scenarios.calls.filter((call) => call.method !== 'GET')).toEqual([]);
});

test('does not block agent controls on a slow scenario request or show a fabricated preview', async ({ page }) => {
  await installQuickTuneMocks(page);
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  await page.route('**/api/v1/scenario-builder/session/*?scenario_name=*', async (route) => {
    await gate;
    await route.fallback();
  });
  try {
    const panel = await openTune(page);
    await expect(panel.getByRole('status', { name: 'Loading scenario preview for Banking' })).toBeVisible();
    await expect(panel.getByTestId('scenario-graph-preview')).toHaveCount(0);
    await panel.getByRole('button', { name: /^Behavior/ }).click();
    await expect(panel.getByRole('textbox', { name: 'Instructions', exact: true })).toHaveValue(AGENT_CONFIG.prompt);
    release();
    await expect(panel.getByTestId('scenario-graph-preview')).toContainText('2 agents / 1 handoff');
  } finally {
    release();
  }
});

test('keeps legacy all-agent membership and omits the selected-scenario preview while creating a draft', async ({ page }) => {
  const state = await installQuickTuneMocks(page);
  state.agents.ExtraGuide = { ...structuredClone(AGENT_CONFIG), name: 'ExtraGuide' };
  state.scenarioConfigs.banking = { ...state.scenarios.scenariosResponse.builtin_scenarios[0], agents: [] };
  const panel = await openTune(page);
  await expect(panel.getByTestId('scenario-graph-preview')).toContainText('3 agents / 0 handoffs');
  expect(state.scenarioConfigs.banking.agents).toEqual([]);
  await panel.getByRole('tab', { name: 'Create scenario', exact: true }).click();
  await expect(panel.getByTestId('scenario-graph-preview')).toHaveCount(0);
  expect(state.scenarios.calls.filter((call) => call.method !== 'GET')).toEqual([]);
});
