import { test, expect } from '@playwright/test';
import { AGENT_CONFIG, installQuickTuneMocks } from './helpers/quick-tune-mocks.js';
import { layoutViolations } from './helpers/authoring-layout.js';

async function openEditor(page) {
  await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'Quick Tune workspace' });
  await panel.getByRole('tab', { name: 'Edit scenario', exact: true }).click();
  await expect(panel.getByRole('textbox', { name: 'Scenario name', exact: true })).toBeVisible();
  return panel;
}

async function chooseScenario(page, panel, name) {
  await panel.getByRole('combobox', { name: 'Scenario to edit', exact: true }).fill(name);
  await page.getByRole('option', { name, exact: true }).click();
  await expect(panel.getByRole('textbox', { name: 'Scenario name', exact: true })).toHaveValue(name);
}

test('updates an existing template for the session and retains the edit on reopening', async ({ page }) => {
  const state = await installQuickTuneMocks(page);
  await page.goto('/');
  let panel = await openEditor(page);
  await panel.getByRole('textbox', { name: 'Scenario purpose', exact: true }).fill('Premium account support with fraud escalation.');
  await panel.getByRole('textbox', { name: 'Icon', exact: true }).fill('P');
  await panel.getByRole('button', { name: 'Scenario context', exact: true }).click();
  const context = { company_name: 'Northwind', enabled: false, limit: 0, preferences: { language: 'fr' } };
  await panel.getByRole('textbox', { name: 'Scenario context (JSON)', exact: true }).fill(JSON.stringify(context));
  expect(state.scenarios.calls.filter((call) => call.type === 'update')).toEqual([]);
  await panel.getByRole('button', { name: 'Save scenario', exact: true }).click();
  await expect(panel.getByText('Scenario saved and selected. Start a conversation to try it.')).toBeVisible();
  const saved = state.scenarios.calls.find((call) => call.type === 'update').body;
  expect(saved.name).toBe('Banking');
  expect(saved.global_template_vars).toEqual(context);
  expect(saved.agent_defaults).toEqual({ voice_rate: '-5%' });
  expect(saved.tools).toEqual(['check_balance']);
  expect(saved.handoffs[0].context_vars).toEqual({ priority: 'urgent' });
  await panel.getByRole('button', { name: 'Close Quick Tune', exact: true }).click();
  panel = await openEditor(page);
  await expect(panel.getByRole('textbox', { name: 'Scenario purpose', exact: true }))
    .toHaveValue('Premium account support with fraud escalation.');
  expect(state.scenarios.scenariosResponse.builtin_scenarios.find((item) => item.name === 'Banking').is_session_override).toBe(true);
});

test('edits a single-agent scenario without activating it until Save and activate', async ({ page }) => {
  const state = await installQuickTuneMocks(page);
  state.agents.HealthConcierge = { ...structuredClone(AGENT_CONFIG), name: 'HealthConcierge' };
  await page.goto('/');
  const panel = await openEditor(page);
  await chooseScenario(page, panel, 'Healthcare');
  await expect(panel.getByText('One agent, one conversation. No handoffs needed.')).toBeVisible();
  await panel.getByRole('textbox', { name: 'Scenario purpose', exact: true }).fill('Help patients prepare for appointments.');
  expect(state.scenarios.scenariosResponse.active_scenario).toBe('Banking');
  expect(state.scenarios.calls.filter((call) => call.method !== 'GET')).toEqual([]);
  await panel.getByRole('button', { name: 'Save & activate', exact: true }).click();
  await expect(panel.getByText('Scenario saved and selected. Start a conversation to try it.')).toBeVisible();
  expect(state.scenarios.scenariosResponse.active_scenario).toBe('Healthcare');
});

test('keeps independent scenario drafts and invalid JSON across selection changes', async ({ page }) => {
  const state = await installQuickTuneMocks(page);
  await page.goto('/');
  const panel = await openEditor(page);
  await panel.getByRole('button', { name: 'Scenario context', exact: true }).click();
  await panel.getByRole('textbox', { name: 'Scenario context (JSON)', exact: true }).fill('{"company_name":');
  await expect(panel.getByRole('button', { name: 'Save scenario', exact: true })).toBeDisabled();
  await chooseScenario(page, panel, 'Insurance');
  await panel.getByRole('textbox', { name: 'Scenario purpose', exact: true }).fill('Insurance draft kept separately.');
  await chooseScenario(page, panel, 'Banking');
  const contextSection = panel.getByRole('button', { name: 'Scenario context', exact: true });
  if (await contextSection.getAttribute('aria-expanded') !== 'true') await contextSection.click();
  await expect(panel.getByRole('textbox', { name: 'Scenario context (JSON)', exact: true })).toHaveValue('{"company_name":');
  await panel.getByRole('button', { name: 'Discard changes', exact: true }).click();
  await chooseScenario(page, panel, 'Insurance');
  await expect(panel.getByRole('textbox', { name: 'Scenario purpose', exact: true })).toHaveValue('Insurance draft kept separately.');
  expect(state.scenarios.calls.filter((call) => call.method !== 'GET')).toEqual([]);
});

test('rejects unsupported defaults instead of pretending they were saved', async ({ page }) => {
  const state = await installQuickTuneMocks(page);
  await page.goto('/');
  const panel = await openEditor(page);
  await panel.getByRole('button', { name: 'Agent defaults', exact: true }).click();
  const defaults = panel.getByRole('textbox', { name: 'Agent defaults (JSON)', exact: true });
  await defaults.fill('{"temperature": 0.1}');
  await expect(panel.getByRole('button', { name: 'Save scenario', exact: true })).toBeDisabled();
  await expect(panel.getByText('Unsupported agent defaults: temperature.').first()).toBeVisible();
  await defaults.fill('{"template_vars":{"company_name":"Northwind"}}');
  await expect(panel.getByRole('button', { name: 'Save scenario', exact: true })).toBeEnabled();
  expect(state.scenarios.calls.filter((call) => call.method !== 'GET')).toEqual([]);
});

test('retains scenario edits after a persistence failure', async ({ page }) => {
  const state = await installQuickTuneMocks(page);
  state.scenarioSaveError = 'Scenario storage is unavailable. Retry after reconnecting.';
  await page.goto('/');
  const panel = await openEditor(page);
  await panel.getByRole('textbox', { name: 'Scenario purpose', exact: true }).fill('A draft that must not disappear.');
  await panel.getByRole('button', { name: 'Save scenario', exact: true }).click();
  await expect(panel.getByText(state.scenarioSaveError, { exact: true })).toBeVisible();
  await expect(panel.getByRole('textbox', { name: 'Scenario purpose', exact: true })).toHaveValue('A draft that must not disappear.');
  state.scenarioSaveError = null;
  await panel.getByRole('button', { name: 'Save scenario', exact: true }).click();
  await expect(panel.getByText('Scenario saved and selected. Start a conversation to try it.')).toBeVisible();
});

test('keeps scenario actions accessible in a narrow workspace', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await installQuickTuneMocks(page);
  await page.goto('/');
  const panel = await openEditor(page);
  await panel.getByRole('button', { name: 'Scenario context', exact: true }).click();
  expect(await layoutViolations(panel)).toEqual([]);
  await expect(panel.getByRole('button', { name: 'Save scenario', exact: true })).toBeInViewport();
  await expect(panel.getByRole('button', { name: 'Close Quick Tune', exact: true })).toBeInViewport();
});

test('preserves legacy all-agents membership when only scenario details change', async ({ page }) => {
  const state = await installQuickTuneMocks(page);
  state.scenarioConfigs.banking = {
    ...state.scenarios.scenariosResponse.builtin_scenarios[0],
    agents: [], tools: ['check_balance'], agent_defaults: null,
  };
  await page.goto('/');
  const panel = await openEditor(page);
  await expect(panel.getByText('This scenario allows all registered agents. Select specific agents to restrict it.')).toBeVisible();
  await panel.getByRole('textbox', { name: 'Scenario purpose', exact: true }).fill('Updated without restricting agent access.');
  await panel.getByRole('button', { name: 'Save scenario', exact: true }).click();
  await expect(panel.getByText('Scenario saved and selected. Start a conversation to try it.')).toBeVisible();
  expect(state.scenarios.calls.find((call) => call.type === 'update').body.agents).toEqual([]);
});
