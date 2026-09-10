import { test, expect } from '@playwright/test';
import { installQuickTuneMocks, TOOL_CATALOG } from './helpers/quick-tune-mocks.js';
import { layoutViolations } from './helpers/authoring-layout.js';

async function prepare(page, { unavailable = false, retired = false } = {}) {
  const state = await installQuickTuneMocks(page);
  state.agents.FraudAgent.tools = ['get_transactions', 'lookup_customer_case', 'handoff_to_agent'];
  state.agents.FraudAgent.is_session_agent = true;
  const specialist = 'InternationalCustomerResolutionAndAccountSupportSpecialist';
  state.agents[specialist] = {
    ...structuredClone(state.agents.BankingConcierge), name: specialist,
    description: 'Resolve international account questions with the customer support team.',
    tools: ['lookup_customer_case'],
  };
  if (retired) state.agents.BankingConcierge.tools.push('retired_legacy_capability');
  const tools = [
    ...TOOL_CATALOG.map((tool) => tool.name === 'get_transactions'
      ? { ...tool, description: 'Read recent card transactions to help investigate duplicate charges.' } : tool),
    {
      name: 'lookup_customer_case', description: 'Read customer support cases and service history.',
      tags: ['support', 'external'], source: 'mcp', mcp_server: 'CaseDesk', mcp_transport: 'streamable-http',
      parameters: {
        type: 'object',
        properties: {
          customer_id: { type: 'string', description: 'Customer whose cases should be returned.' },
          include_closed: { type: 'boolean', description: 'Include previously closed cases.' },
        },
        required: ['customer_id'],
      },
    },
    ...Array.from({ length: 24 }, (_, index) => ({
      name: `review_policy_${String(index).padStart(2, '0')}`,
      description: `Read policy ${index} terms and eligibility without changing the policy.`,
      tags: ['insurance'], source: 'local', is_handoff: false,
    })),
  ];
  await page.route('**/api/v1/agent-builder/tools', (route) => route.fulfill(
    unavailable ? { status: 503, json: { detail: 'Tool registry unavailable' } } : { json: { tools } },
  ));
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'Quick Tune workspace' });
  await panel.getByRole('button', { name: /^Tools/ }).click();
  const catalog = panel.getByRole('region', { name: 'Tool catalog', exact: true });
  await expect(catalog).toBeVisible();
  return { state, panel, catalog };
}

async function chooseFilter(page, catalog, label, option) {
  const filters = catalog.getByRole('button', { name: 'Tool filters', exact: true });
  if (await filters.getAttribute('aria-expanded') !== 'true') await filters.click();
  await catalog.getByRole('combobox', { name: new RegExp(`^${label}`) }).click();
  await page.getByRole('option', { name: option, exact: true }).click();
}

async function selectAgent(page, panel, name) {
  const input = panel.getByRole('combobox', { name: 'Agent to tune', exact: true });
  await input.fill(name);
  await page.getByRole('option', { name, exact: true }).click();
  await panel.getByRole('button', { name: /^Tools/ }).click();
}

test('searches by purpose, shows assignments, and only saves explicit tool changes', async ({ page }) => {
  const { state, panel, catalog } = await prepare(page);
  const before = structuredClone(state.agents.BankingConcierge);
  await catalog.getByRole('textbox', { name: 'Find capabilities' }).fill('duplicate charges');
  const row = catalog.getByTestId('tool-option-get_transactions');
  await expect(row.getByText('Get transactions', { exact: true })).toBeVisible();
  await expect(row.getByText('Read recent card transactions to help investigate duplicate charges.')).toBeVisible();
  await row.getByRole('button', { name: 'Details for get_transactions' }).click();
  await expect(row.getByText('FraudAgent', { exact: true })).toBeVisible();
  await expect(row.getByText('Session configuration', { exact: true })).toBeVisible();
  await row.getByRole('checkbox', { name: 'Use get_transactions', exact: true }).check();
  await expect(row.getByText('BankingConcierge', { exact: true })).toBeVisible();
  await expect(row.getByText('Workspace draft', { exact: true })).toBeVisible();
  expect(state.calls).toEqual([]);
  await panel.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(panel.getByText(/Saved for the next connection/)).toBeVisible();
  const saved = state.calls.find((call) => call.type === 'save-agent').body;
  expect(saved.tools).toEqual(['check_balance', 'get_transactions', 'handoff_to_agent']);
  expect(saved).not.toHaveProperty('has_local_draft');
  for (const key of ['prompt', 'voice', 'speech', 'session', 'cascade_model', 'voicelive_model', 'byom', 'template_vars']) {
    expect(saved[key]).toEqual(before[key]);
  }
});

test('keeps selections across category filters and pages, with an isolated selected view', async ({ page }) => {
  const { state, panel, catalog } = await prepare(page);
  await chooseFilter(page, catalog, 'Category', 'Insurance');
  await expect(catalog.getByRole('checkbox')).toHaveCount(6);
  await catalog.getByRole('checkbox', { name: 'Use review_policy_00', exact: true }).check();
  await catalog.getByRole('button', { name: 'Go to next page', exact: true }).click();
  await catalog.getByRole('checkbox', { name: 'Use review_policy_06', exact: true }).check();
  await catalog.getByRole('button', { name: 'Selected (3)', exact: true }).click();
  await catalog.getByRole('button', { name: 'Clear filters', exact: true }).click();
  await expect(catalog.getByRole('checkbox')).toHaveCount(3);
  for (const tool of ['check_balance', 'review_policy_00', 'review_policy_06']) {
    await expect(catalog.getByRole('checkbox', { name: `Use ${tool}`, exact: true })).toBeChecked();
  }
  await catalog.getByRole('button', { name: 'Clear selection', exact: true }).click();
  await expect(catalog.getByText('No tools selected yet')).toBeVisible();
  await panel.getByRole('button', { name: 'Discard changes', exact: true }).click();
  await expect(catalog.getByRole('checkbox', { name: 'Use check_balance', exact: true })).toBeChecked();
  await expect(catalog.getByRole('checkbox', { name: 'Use handoff_to_agent', exact: true })).toHaveCount(0);
  expect(state.calls).toEqual([]);
});

test('filters by agent and explains MCP sources, full descriptions, and required inputs', async ({ page }) => {
  const { state, catalog } = await prepare(page);
  await chooseFilter(page, catalog, 'Assigned to', 'FraudAgent');
  await expect(catalog.getByRole('checkbox')).toHaveCount(2);
  await expect(catalog.getByRole('checkbox', { name: 'Use check_balance', exact: true })).toHaveCount(0);
  const row = catalog.getByTestId('tool-option-lookup_customer_case');
  await row.getByRole('button', { name: 'Details for lookup_customer_case' }).click();
  await expect(row.getByText('MCP: CaseDesk', { exact: true })).toBeVisible();
  await expect(row.getByText(/Registration does not confirm a working connection/)).toBeVisible();
  await expect(row.getByText('string / required', { exact: true })).toBeVisible();
  await expect(row.getByText('boolean / optional', { exact: true })).toBeVisible();
  await expect(row.getByText(/not execution history/)).toBeVisible();
  await row.getByRole('button', { name: 'Full input schema', exact: true }).click();
  await expect(row.locator('pre')).toContainText('"customer_id"');
  expect(state.calls).toEqual([]);
});

test('agent assignment search reflects unsaved changes in other workspace agents', async ({ page }) => {
  const { state, panel, catalog } = await prepare(page);
  await catalog.getByRole('textbox', { name: 'Find capabilities' }).fill('get_transactions');
  await catalog.getByRole('checkbox', { name: 'Use get_transactions', exact: true }).check();
  await selectAgent(page, panel, 'FraudAgent');
  const otherCatalog = panel.getByRole('region', { name: 'Tool catalog', exact: true });
  await otherCatalog.getByRole('textbox', { name: 'Find capabilities' }).fill('BankingConcierge');
  const row = otherCatalog.getByTestId('tool-option-get_transactions');
  await row.getByRole('button', { name: 'Details for get_transactions' }).click();
  await expect(row.getByText('Workspace draft', { exact: true })).toBeVisible();
  await selectAgent(page, panel, 'BankingConcierge');
  await panel.getByRole('button', { name: 'Discard changes', exact: true }).click();
  const restored = panel.getByRole('region', { name: 'Tool catalog', exact: true });
  await restored.getByRole('textbox', { name: 'Find capabilities' }).fill('BankingConcierge');
  await expect(restored.getByTestId('tool-option-get_transactions')).toHaveCount(0);
  expect(state.calls).toEqual([]);
});

test('preserves unavailable selected tools until explicitly removed', async ({ page }) => {
  const { state, panel, catalog } = await prepare(page, { retired: true });
  await catalog.getByRole('textbox', { name: 'Find capabilities' }).fill('retired');
  const row = catalog.getByTestId('tool-option-retired_legacy_capability');
  await expect(row.getByText(/Not in the current catalog/)).toBeVisible();
  await row.getByRole('checkbox', { name: 'Use retired_legacy_capability' }).click();
  await expect(row).toHaveCount(0);
  await panel.getByRole('button', { name: 'Discard changes', exact: true }).click();
  await expect(row.getByRole('checkbox', { name: 'Use retired_legacy_capability' })).toBeChecked();
  expect(state.calls).toEqual([]);
});

test('does not enable tool selection when the catalog is unavailable', async ({ page }) => {
  const { state, catalog } = await prepare(page, { unavailable: true });
  await expect(catalog.getByText(/Tool catalog unavailable/)).toBeVisible();
  await expect(catalog.getByRole('checkbox', { name: 'Use check_balance', exact: true })).toBeDisabled();
  expect(state.calls).toEqual([]);
});

test('uses the same catalog for scenario generation without assigning tools to the current agent', async ({ page }) => {
  const { state, panel } = await prepare(page);
  const originalTools = [...state.agents.BankingConcierge.tools];
  await panel.getByRole('tab', { name: 'Create scenario', exact: true }).click();
  await panel.getByRole('button', { name: /^Tool scope:/ }).click();
  const catalog = panel.getByRole('region', { name: 'Tool catalog', exact: true });
  await catalog.getByRole('button', { name: 'Clear selection', exact: true }).click();
  for (const tool of ['check_balance', 'handoff_to_agent']) {
    await catalog.getByRole('textbox', { name: 'Find capabilities' }).fill(tool);
    await catalog.getByRole('checkbox', { name: `Use ${tool}`, exact: true }).check();
  }
  await panel.getByRole('textbox', { name: 'What should this scenario do?' }).fill('Help customers understand their balances.');
  await panel.getByRole('button', { name: 'Generate draft', exact: true }).click();
  const graph = page.getByRole('dialog', { name: 'Review the generated scenario', exact: true });
  await expect(graph).toBeVisible();
  expect(state.calls.map((call) => call.type)).toEqual(['generate']);
  expect(state.calls[0].body.allowed_tools).toEqual(['check_balance', 'handoff_to_agent']);
  expect(state.agents.BankingConcierge.tools).toEqual(originalTools);
  await graph.getByRole('button', { name: 'Close graphical editor' }).click();
  await panel.getByRole('button', { name: 'Use all registered tools', exact: true }).click();
  await panel.getByRole('button', { name: 'Refine draft', exact: true }).click();
  await expect(graph).toBeVisible();
  expect(state.calls.at(-1).body.allowed_tools).toBeNull();
});

test('edits tools on a generated agent in graph review without publishing until Apply', async ({ page }) => {
  const { state, panel } = await prepare(page);
  await panel.getByRole('tab', { name: 'Create scenario', exact: true }).click();
  await panel.getByRole('textbox', { name: 'What should this scenario do?' }).fill('Draft an account balance guide.');
  await panel.getByRole('button', { name: 'Generate draft', exact: true }).click();
  const graph = page.getByRole('dialog', { name: 'Review the generated scenario', exact: true });
  await graph.getByTestId('graph-node-BalanceGuide').getByRole('button', { name: 'View agent details' }).click();
  await graph.getByRole('button', { name: /^Tools/ }).click();
  const catalog = graph.getByRole('region', { name: 'Tool catalog', exact: true });
  await catalog.getByRole('textbox', { name: 'Find capabilities' }).fill('get_transactions');
  await catalog.getByRole('checkbox', { name: 'Use get_transactions', exact: true }).check();
  await catalog.getByRole('button', { name: 'Details for get_transactions' }).click();
  await expect(catalog.getByText('BalanceGuide', { exact: true })).toBeVisible();
  await expect(catalog.getByText('Workspace draft', { exact: true })).toBeVisible();
  expect(state.calls.map((call) => call.type)).toEqual(['generate']);
  await graph.getByRole('button', { name: 'Close graphical editor' }).click();
  await panel.getByRole('textbox', { name: 'company_name', exact: true }).fill('Northwind');
  await panel.getByRole('button', { name: 'Apply scenario', exact: true }).click();
  await expect(panel.getByText(/Scenario saved and selected/)).toBeVisible();
  const guide = state.calls.find((call) => call.type === 'apply-draft').body.agents[0];
  expect(guide.tools).toEqual(['check_balance', 'get_transactions']);
  expect(guide).not.toHaveProperty('has_local_draft');
});

for (const viewport of [{ name: 'desktop', width: 1600, height: 1000 }, { name: 'mobile', width: 390, height: 844 }]) {
  test(`tool catalog remains readable and operable on ${viewport.name}`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const { panel, catalog } = await prepare(page);
    await expect(catalog.getByRole('checkbox').first()).toBeInViewport({ ratio: 1 });
    await page.screenshot({ path: testInfo.outputPath(`tool-catalog-${viewport.name}.png`), animations: 'disabled' });
    await catalog.getByRole('textbox', { name: 'Find capabilities' }).fill('lookup_customer_case');
    await catalog.getByRole('button', { name: 'Details for lookup_customer_case' }).click();
    await expect(catalog.getByText('Agent assignments', { exact: true })).toBeVisible();
    await catalog.getByText('Agent assignments', { exact: true }).scrollIntoViewIfNeeded();
    await page.screenshot({ path: testInfo.outputPath(`tool-catalog-details-${viewport.name}.png`), animations: 'disabled' });
    expect(await layoutViolations(panel)).toEqual([]);
    await chooseFilter(page, catalog, 'Assigned to', 'FraudAgent');
    await catalog.getByRole('checkbox', { name: 'Use lookup_customer_case', exact: true }).check();
    await expect(panel.getByRole('button', { name: 'Save changes', exact: true })).toBeInViewport();
    await panel.getByRole('button', { name: 'Discard changes', exact: true }).click();
  });
}
