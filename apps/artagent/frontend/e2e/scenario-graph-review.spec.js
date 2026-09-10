import { test, expect } from '@playwright/test';
import { installQuickTuneMocks } from './helpers/quick-tune-mocks.js';

// Opens Quick Tune, switches to "Create scenario", and generates a draft.
// Returns both the Quick Tune panel and the graph review dialog that opens
// automatically on a successful generate - callers close it explicitly where
// the test doesn't need it kept open.
async function openTuneAndGenerate(page, prompt = 'Help customers understand their balance with the available banking tools.') {
  await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'Quick Tune workspace' });
  await expect(panel).toBeVisible();
  await panel.getByRole('tab', { name: 'Create scenario', exact: true }).click();
  await panel.getByRole('textbox', { name: 'What should this scenario do?' }).fill(prompt);
  await panel.getByRole('button', { name: 'Generate draft', exact: true }).click();
  const dialog = page.getByRole('dialog', { name: /Review the generated scenario/ });
  await expect(dialog).toBeVisible();
  return { panel, dialog };
}

test.describe('Graphical scenario review (generated drafts)', () => {
  test('opens automatically after generating and shows new and reused agents without registering anything', async ({ page }) => {
    const state = await installQuickTuneMocks(page);
    await page.goto('/');
    const { dialog } = await openTuneAndGenerate(page);
    // Both the reused start agent and the newly drafted specialist render as
    // nodes - the new agent is visible even though the review isn't applied.
    await expect(dialog.getByTestId('graph-node-BankingConcierge')).toBeVisible();
    await expect(dialog.getByTestId('graph-node-BalanceGuide')).toBeVisible();
    // No side door to register/create agents from inside the review, and no
    // network write has happened yet - only the generate call.
    await expect(dialog.getByRole('button', { name: 'Create New Agent' })).toHaveCount(0);
    expect(state.calls.map((call) => call.type)).toEqual(['generate']);
  });

  test('renders an isolated new agent from the draft without inventing a handoff', async ({ page }) => {
    const state = await installQuickTuneMocks(page);
    // Strip the generated handoff so BalanceGuide has no connection - it must
    // still render (via the explicit scenario.agents membership) instead of
    // being hidden or auto-wired with an invented edge/condition.
    state.draft.scenario.handoffs = [];
    await page.goto('/');
    const { dialog } = await openTuneAndGenerate(page);
    await expect(dialog.getByTestId('graph-node-BalanceGuide')).toBeVisible();
    await expect(dialog.getByTestId('graph-edge-BankingConcierge-BalanceGuide')).toHaveCount(0);
    await expect(dialog.getByText('Needs connection')).toBeVisible();
  });

  test('keeps a dragged node position after closing and reopening the review', async ({ page }) => {
    await installQuickTuneMocks(page);
    await page.goto('/');
    const { panel, dialog } = await openTuneAndGenerate(page);
    const node = dialog.getByTestId('graph-node-BalanceGuide');
    const before = await node.boundingBox();
    await page.mouse.move(before.x + before.width / 2, before.y + before.height / 2);
    await page.mouse.down();
    await page.mouse.move(before.x + before.width / 2 + 180, before.y + before.height / 2 + 140, { steps: 12 });
    await page.mouse.up();
    const dragged = await node.boundingBox();
    expect(dragged.x - before.x).toBeCloseTo(180, 0);
    expect(dragged.y - before.y).toBeCloseTo(140, 0);

    await dialog.getByRole('button', { name: 'Close graphical editor' }).click();
    await expect(dialog).not.toBeVisible();
    // Reopen via the composer's manual entry point (not a second Generate) -
    // the same draft and its layout must still be there.
    await panel.getByRole('button', { name: 'Graphical editor', exact: true }).click();
    await expect(dialog).toBeVisible();
    const reopened = await dialog.getByTestId('graph-node-BalanceGuide').boundingBox();
    expect(Math.round(reopened.x)).toBe(Math.round(dragged.x));
    expect(Math.round(reopened.y)).toBe(Math.round(dragged.y));
  });

  test('editing a handoff condition through the graph updates the Apply payload, with no writes before Apply', async ({ page }) => {
    const state = await installQuickTuneMocks(page);
    await page.goto('/');
    const { panel, dialog } = await openTuneAndGenerate(page);

    await dialog.getByTestId('graph-edge-BankingConcierge-BalanceGuide').click();
    const handoffDialog = page.getByRole('dialog', { name: 'Edit Handoff' });
    await expect(handoffDialog).toBeVisible();
    await handoffDialog.locator('textarea').first().fill('The customer specifically asks how much money they have.');
    await handoffDialog.getByRole('button', { name: 'Save Changes' }).click();
    await expect(handoffDialog).not.toBeVisible();

    // The edit lives in the draft only - nothing was written yet.
    expect(state.calls.map((call) => call.type)).toEqual(['generate']);

    await dialog.getByRole('button', { name: 'Close graphical editor' }).click();
    await panel.getByRole('textbox', { name: 'company_name' }).fill('Northwind');
    await panel.getByRole('button', { name: 'Apply scenario', exact: true }).click();
    await expect(panel.getByText('Scenario saved and selected. Start a conversation to try it.')).toBeVisible();
    const applied = state.calls.find((call) => call.type === 'apply-draft').body;
    expect(applied.scenario.handoffs[0].handoff_condition).toBe('The customer specifically asks how much money they have.');
  });

  test('closing the review preserves the draft and edits for the next reopen', async ({ page }) => {
    await installQuickTuneMocks(page);
    await page.goto('/');
    const { panel, dialog } = await openTuneAndGenerate(page);
    await dialog.getByRole('button', { name: 'Close graphical editor' }).click();
    await expect(dialog).not.toBeVisible();
    // The composer's own draft state (list view) is unaffected by opening or
    // closing the graph review.
    await expect(panel.getByText('Draft - not active', { exact: true })).toBeVisible();
    await panel.getByRole('textbox', { name: 'Scenario purpose' }).fill('Kept across graph review close/reopen.');
    await panel.getByRole('button', { name: 'Graphical editor', exact: true }).click();
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Close graphical editor' }).click();
    await expect(panel.getByRole('textbox', { name: 'Scenario purpose' })).toHaveValue('Kept across graph review close/reopen.');
  });

  test('keeps the graph inspector open while renaming a new agent', async ({ page }) => {
    await installQuickTuneMocks(page);
    await page.goto('/');
    const { dialog } = await openTuneAndGenerate(page);
    await dialog.getByTestId('graph-node-BalanceGuide')
      .getByRole('button', { name: 'View agent details' }).click();
    const name = dialog.getByRole('textbox', { name: 'Agent name', exact: true });
    await name.fill('RenamedBalanceGuide');
    await expect(name).toBeVisible();
    await expect(name).toHaveValue('RenamedBalanceGuide');
    await expect(dialog.getByTestId('graph-node-RenamedBalanceGuide')).toBeVisible();
    await expect(dialog.getByTestId('graph-edge-BankingConcierge-RenamedBalanceGuide')).toBeVisible();
  });

  test('shows Apply failures inside the graph review without losing the draft', async ({ page }) => {
    const state = await installQuickTuneMocks(page);
    state.draft.scenario.global_template_vars.company_name = 'Northwind';
    state.applyError = 'The session changed. Review the draft and retry.';
    await page.goto('/');
    const { dialog } = await openTuneAndGenerate(page);
    await dialog.getByRole('button', { name: 'Apply scenario', exact: true }).click();
    await expect(dialog.getByText(state.applyError, { exact: true })).toBeVisible();
    await expect(dialog.getByTestId('graph-node-BalanceGuide')).toBeVisible();
    expect(state.scenarios.scenariosResponse.active_scenario).toBe('Banking');
  });
});

test.describe('Graphical editor for the current scenario', () => {
  test('only persists routing changes once Save scenario runs, never while editing in the graph', async ({ page }) => {
    const state = await installQuickTuneMocks(page);
    await page.goto('/');
    await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
    const panel = page.getByRole('complementary', { name: 'Quick Tune workspace' });
    await panel.getByRole('tab', { name: 'Edit scenario', exact: true }).click();
    const graphButton = panel.getByRole('button', { name: 'Open graphical editor for Banking', exact: true });
    await expect(graphButton).toBeVisible();
    await graphButton.click();
    const dialog = page.getByRole('dialog', { name: /Graphical editor - Banking/ });
    await expect(dialog).toBeVisible();

    await dialog.getByTestId('graph-edge-BankingConcierge-FraudAgent').click();
    const handoffDialog = page.getByRole('dialog', { name: 'Edit Handoff' });
    await handoffDialog.locator('textarea').first().fill('The caller specifically mentions an unauthorized charge.');
    await handoffDialog.getByRole('button', { name: 'Save Changes' }).click();

    // Editing in the graph is local to the workspace draft - the scenario
    // endpoint has not been called yet.
    expect(state.scenarios.calls.filter((call) => call.type === 'update')).toHaveLength(0);

    await dialog.getByRole('button', { name: 'Close graphical editor' }).click();
    await panel.getByRole('button', { name: 'Save scenario', exact: true }).click();
    await expect(panel.getByText('Scenario saved and selected. Start a conversation to try it.')).toBeVisible();
    const saved = state.scenarios.calls.find((call) => call.type === 'update');
    expect(saved.body.handoffs[0].handoff_condition).toBe('The caller specifically mentions an unauthorized charge.');
  });
});
