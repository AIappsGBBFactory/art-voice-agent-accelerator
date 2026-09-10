import { test, expect } from '@playwright/test';
import { installQuickTuneMocks } from './helpers/quick-tune-mocks.js';
import { installPromptPreviewMocks } from './helpers/prompt-preview-mocks.js';
import { layoutViolations } from './helpers/authoring-layout.js';

async function prepare(page) {
  const state = await installQuickTuneMocks(page);
  const preview = await installPromptPreviewMocks(page);
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'Quick Tune workspace' });
  await panel.getByRole('button', { name: /^Behavior/ }).click();
  return { state, preview, panel };
}

async function openPrompt(page, container) {
  await container.getByRole('button', { name: 'Open prompt editor', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: 'Prompt editor', exact: true });
  await expect(dialog.getByRole('textbox', { name: 'Prompt source', exact: true })).toBeVisible();
  return dialog;
}

async function selectText(source, start, end) {
  await source.evaluate((element, range) => {
    element.focus();
    element.setSelectionRange(range.start, range.end);
  }, { start, end });
}

for (const viewport of [
  { name: 'desktop', width: 1280, height: 720 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  test(`keeps the prompt opener under the pointer during a deliberate click on ${viewport.name}`, async ({ page }) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const { state, panel } = await prepare(page);
    const opener = panel.getByRole('button', { name: 'Open prompt editor', exact: true });
    await opener.scrollIntoViewIfNeeded();
    // Keep the pointer down across the former accordion animation: the action
    // must not move away before pointerup and silently lose the user's click.
    await opener.click({ delay: 250 });
    const dialog = page.getByRole('dialog', { name: 'Prompt editor', exact: true });
    await expect(dialog.getByRole('textbox', { name: 'Prompt source', exact: true }))
      .toHaveValue(state.agents.BankingConcierge.prompt);
    expect(state.calls).toEqual([]);
  });
}

test('inserts Jinja at the cursor, supports undo/redo, and preserves the draft when closing', async ({ page }) => {
  const { state, panel } = await prepare(page);
  const dialog = await openPrompt(page, panel);
  const source = dialog.getByRole('textbox', { name: 'Prompt source', exact: true });
  await source.fill('Hello CUSTOMER, welcome to the support desk.');
  await selectText(source, 6, 14);
  await dialog.getByRole('textbox', { name: 'Find context' }).fill('caller_name');
  await dialog.getByRole('button', { name: 'Insert caller_name', exact: true }).click();
  await expect(source).toHaveValue('Hello {{ caller_name }}, welcome to the support desk.');
  await dialog.getByRole('button', { name: 'Undo prompt edit' }).click();
  await expect(source).toHaveValue('Hello CUSTOMER, welcome to the support desk.');
  await dialog.getByRole('button', { name: 'Redo prompt edit' }).click();
  await expect(source).toHaveValue('Hello {{ caller_name }}, welcome to the support desk.');
  expect(state.calls).toEqual([]);
  await dialog.getByRole('button', { name: 'Done editing', exact: true }).click();
  await expect(panel.getByRole('textbox', { name: 'Instructions', exact: true }))
    .toHaveValue('Hello {{ caller_name }}, welcome to the support desk.');
  await expect(panel.getByRole('button', { name: 'Open prompt editor', exact: true })).toBeFocused();
  const reopened = await openPrompt(page, panel);
  await expect(reopened.getByRole('textbox', { name: 'Prompt source' }))
    .toHaveValue('Hello {{ caller_name }}, welcome to the support desk.');
});

test('saves from the pop-out using the existing full-agent update contract', async ({ page }) => {
  const { state, panel } = await prepare(page);
  const original = structuredClone(state.agents.BankingConcierge);
  const dialog = await openPrompt(page, panel);
  const prompt = '# Support\nHelp {{ caller_name }} using only assigned tools.';
  await dialog.getByRole('textbox', { name: 'Prompt source' }).fill(prompt);
  expect(state.calls).toEqual([]);
  await dialog.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(dialog.getByText(/Saved for the next connection/)).toBeVisible();
  const saved = state.calls.find((call) => call.type === 'save-agent').body;
  expect(saved.prompt).toBe(prompt);
  for (const field of ['name', 'voice', 'speech', 'session', 'cascade_model', 'voicelive_model', 'byom', 'tools', 'template_vars']) {
    expect(saved[field]).toEqual(original[field]);
  }
  await dialog.getByRole('textbox', { name: 'Prompt source' }).fill(`${prompt}\nA newer draft.`);
  await expect(dialog.getByText(/Saved for the next connection/)).toHaveCount(0);
});

test('previews a read-only snapshot and never presents stale output as current', async ({ page }) => {
  const { state, preview, panel } = await prepare(page);
  const dialog = await openPrompt(page, panel);
  const source = dialog.getByRole('textbox', { name: 'Prompt source' });
  await source.fill('Hello {{ caller_name }}.');
  await dialog.getByRole('button', { name: 'Preview prompt', exact: true }).click();
  await expect(dialog.getByTestId('rendered-prompt')).toHaveText('Hello Ava Harper.');
  preview.delay = 300;
  await source.fill('Old preview request.');
  await dialog.getByRole('button', { name: 'Preview prompt', exact: true }).click();
  await source.fill('The latest draft.');
  await expect(dialog.getByRole('button', { name: 'Refresh preview', exact: true })).toBeEnabled();
  await expect(dialog.getByText('The prompt or context changed. Refresh to render the latest draft.')).toBeVisible();
  await expect(dialog.getByTestId('rendered-prompt')).toHaveCount(0);
  preview.delay = 0;
  await dialog.getByRole('button', { name: 'Refresh preview', exact: true }).click();
  await expect(dialog.getByTestId('rendered-prompt')).toHaveText('The latest draft.');
  expect(state.calls).toEqual([]);
  expect(preview.calls.at(-1).agent_name).toBe('BankingConcierge');
  expect(preview.calls.at(-1).scenario).not.toHaveProperty('is_active');
});

test('reports syntax errors with line numbers and renders preview output as text, not HTML', async ({ page }) => {
  const { preview, panel } = await prepare(page);
  const dialog = await openPrompt(page, panel);
  preview.diagnostics = [{ message: 'Unclosed conditional block.', line: 3, kind: 'syntax' }];
  await dialog.getByRole('button', { name: 'Preview prompt', exact: true }).click();
  await expect(dialog.getByText('Line 3: Unclosed conditional block.')).toBeVisible();
  await expect(dialog.getByTestId('rendered-prompt')).toHaveCount(0);
  preview.diagnostics = [{ message: 'A required template variable is unavailable.', line: 2, kind: 'undefined' }];
  preview.missing = ['customer_name'];
  await dialog.getByRole('button', { name: 'Preview prompt', exact: true }).click();
  await expect(dialog.getByText('Missing context: customer_name.', { exact: true })).toBeVisible();
  preview.diagnostics = [];
  preview.missing = [];
  await dialog.getByRole('textbox', { name: 'Prompt source' }).fill('Show {{ raw_markup }} as literal text.');
  await dialog.getByRole('button', { name: 'Preview prompt', exact: true }).click();
  await expect(dialog.getByTestId('rendered-prompt')).toHaveText('Show <b>literal markup</b> as literal text.');
  await expect(dialog.getByTestId('rendered-prompt').locator('b')).toHaveCount(0);
});

test('inserts explicit defaults for unavailable values and never enables sensitive fields', async ({ page }) => {
  const { panel } = await prepare(page);
  const dialog = await openPrompt(page, panel);
  const source = dialog.getByRole('textbox', { name: 'Prompt source' });
  await source.fill('Optional context: ');
  await selectText(source, 18, 18);
  await dialog.getByRole('textbox', { name: 'Find context' }).fill('optional_note');
  await dialog.getByRole('button', { name: 'Insert optional_note', exact: true }).click();
  await expect(source).toHaveValue('Optional context: {{ optional_note | default("") }}');
  await dialog.getByRole('textbox', { name: 'Find context' }).fill('verification_code');
  await expect(dialog.getByRole('button', { name: 'Insert session_profile.verification_code', exact: true })).toBeDisabled();
  await expect(dialog.getByText('Hidden value', { exact: true })).toBeVisible();
});

test('keeps editing available after preview or save failures', async ({ page }) => {
  const { state, preview, panel } = await prepare(page);
  preview.failure = 'Could not read the session context.';
  const dialog = await openPrompt(page, panel);
  await expect(dialog.getByText(preview.failure, { exact: true })).toBeVisible();
  const source = dialog.getByRole('textbox', { name: 'Prompt source' });
  await source.fill('A complete draft even when preview is offline.');
  preview.failure = null;
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Insert caller_name', exact: true })).toBeVisible();
  state.agentSaveError = 'Agent storage is unavailable.';
  await dialog.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(dialog.getByText(state.agentSaveError, { exact: true })).toBeVisible();
  await expect(source).toHaveValue('A complete draft even when preview is offline.');
});

test('recovers from an older backend 404 without reloading or losing the prompt draft', async ({ page }) => {
  const { state, preview, panel } = await prepare(page);
  preview.failure = 'Not Found';
  preview.failureStatus = 404;
  const dialog = await openPrompt(page, panel);
  await expect(dialog.getByText(/Start or restart the updated API, then retry/)).toBeVisible();
  const source = dialog.getByRole('textbox', { name: 'Prompt source', exact: true });
  await source.fill('Keep this unsaved prompt while the backend restarts.');
  preview.failure = null;
  await dialog.getByRole('button', { name: 'Retry', exact: true }).click();
  await expect(dialog.getByRole('button', { name: 'Insert caller_name', exact: true })).toBeVisible();
  await expect(dialog.getByText(/Start or restart the updated API, then retry/)).toHaveCount(0);
  await expect(source).toHaveValue('Keep this unsaved prompt while the backend restarts.');
  expect(state.calls).toEqual([]);
});

test('passes unsaved scenario context to preview without saving or inserting literal values', async ({ page }) => {
  const { state, preview, panel } = await prepare(page);
  await panel.getByRole('tab', { name: 'Edit scenario', exact: true }).click();
  await panel.getByRole('button', { name: 'Scenario context', exact: true }).click();
  await panel.getByRole('textbox', { name: 'Scenario context (JSON)', exact: true })
    .fill('{"company_name":"Draft bank"}');
  await panel.getByRole('tab', { name: 'Tune agent', exact: true }).click();
  const dialog = await openPrompt(page, panel);
  await expect(dialog.getByText(/Preview includes an unsaved scenario draft/)).toBeVisible();
  await dialog.getByRole('textbox', { name: 'Find context' }).fill('company_name');
  await expect(dialog.getByText('Draft bank', { exact: true })).toBeVisible();
  const source = dialog.getByRole('textbox', { name: 'Prompt source' });
  await source.fill('You represent ');
  await selectText(source, 14, 14);
  await dialog.getByRole('button', { name: 'Insert company_name', exact: true }).click();
  await expect(source).toHaveValue('You represent {{ company_name }}');
  expect(preview.calls[0].scenario.global_template_vars.company_name).toBe('Draft bank');
  expect(state.scenarios.calls.filter((call) => call.method !== 'GET')).toEqual([]);
  expect(state.calls).toEqual([]);
});

test('formats Markdown and supports keyboard undo without losing template syntax', async ({ page }) => {
  const { panel } = await prepare(page);
  const dialog = await openPrompt(page, panel);
  const source = dialog.getByRole('textbox', { name: 'Prompt source' });
  await source.fill('Important {{ caller_name }}');
  await selectText(source, 0, 9);
  await dialog.getByRole('button', { name: 'Bold', exact: true }).click();
  await expect(source).toHaveValue('**Important** {{ caller_name }}');
  await source.press('Control+z');
  await expect(source).toHaveValue('Important {{ caller_name }}');
  await source.press('Control+Shift+z');
  await expect(source).toHaveValue('**Important** {{ caller_name }}');
});

test('edits a generated agent prompt without registering it before Apply scenario', async ({ page }) => {
  const { state, preview, panel } = await prepare(page);
  state.draft.scenario.global_template_vars.company_name = 'DraftCo';
  await panel.getByRole('tab', { name: 'Create scenario', exact: true }).click();
  await panel.getByRole('textbox', { name: 'What should this scenario do?' }).fill('Create a balance guide.');
  await panel.getByRole('button', { name: 'Generate draft', exact: true }).click();
  const graph = page.getByRole('dialog', { name: 'Review the generated scenario', exact: true });
  await graph.getByTestId('graph-node-BalanceGuide').getByRole('button', { name: 'View agent details' }).click();
  const dialog = await openPrompt(page, graph);
  await dialog.getByRole('textbox', { name: 'Prompt source' }).fill('Help {{ caller_name }} with balances for {{ company_name }}.');
  await dialog.getByRole('button', { name: 'Preview prompt', exact: true }).click();
  await expect(dialog.getByTestId('rendered-prompt')).toHaveText('Help Ava Harper with balances for DraftCo.');
  await expect(dialog.getByRole('button', { name: 'Save changes', exact: true })).toHaveCount(0);
  expect(preview.calls.at(-1).agent_name).toBe('BalanceGuide');
  expect(state.calls.map((call) => call.type)).toEqual(['generate']);
  await dialog.getByRole('button', { name: 'Done editing', exact: true }).click();
  await graph.getByRole('button', { name: 'Apply scenario', exact: true }).click();
  await expect(panel.getByText(/Scenario saved and selected/)).toBeVisible();
  expect(state.calls.find((call) => call.type === 'apply-draft').body.agents[0].prompt)
    .toBe('Help {{ caller_name }} with balances for {{ company_name }}.');
});

for (const viewport of [{ name: 'desktop', width: 1600, height: 1000 }, { name: 'mobile', width: 390, height: 844 }]) {
  test(`prompt workspace fits ${viewport.name} and preserves cursor insertion across views`, async ({ page }, testInfo) => {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const { panel } = await prepare(page);
    const dialog = await openPrompt(page, panel);
    await expect(dialog).toBeInViewport({ ratio: 0.98 });
    const source = dialog.getByRole('textbox', { name: 'Prompt source' });
    expect((await source.boundingBox()).height).toBeGreaterThan(250);
    await source.fill('# Guidance\nWelcome NAME.');
    await selectText(source, 19, 23);
    await dialog.getByRole('tab', { name: 'Context', exact: true }).click();
    await dialog.getByRole('textbox', { name: 'Find context' }).fill('caller_name');
    await dialog.getByRole('button', { name: 'Insert caller_name', exact: true }).click();
    await expect(source).toHaveValue('# Guidance\nWelcome {{ caller_name }}.');
    await page.screenshot({ path: testInfo.outputPath(`prompt-editor-${viewport.name}.png`), animations: 'disabled' });
    expect(await layoutViolations(dialog)).toEqual([]);
    await expect(dialog.getByRole('button', { name: 'Done editing', exact: true })).toBeInViewport();
    await dialog.getByRole('button', { name: 'Close prompt editor', exact: true }).click();
    await expect(panel).toBeVisible();
  });
}
