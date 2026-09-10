import { test, expect } from '@playwright/test';
import { installQuickTuneMocks, TOOL_CATALOG } from './helpers/quick-tune-mocks.js';
import { layoutViolations } from './helpers/authoring-layout.js';

const specialist = 'InternationalCustomerResolutionAndAccountSupportSpecialist';
const role = 'Resolve international customer account questions and explain complex transaction details clearly.';
const capability = 'resolve_international_customer_account_transaction_support';
const deployment = 'customer-support-realtime-deployment-north-america-primary';

async function prepare(page) {
  const state = await installQuickTuneMocks(page);
  state.agents.BankingConcierge.description = role;
  state.agents.BankingConcierge.voicelive_model.deployment_id = deployment;
  state.agents.BankingConcierge.tools.push(capability);
  state.agents.FraudAgent.description = role;
  await page.route('**/api/v1/agent-builder/tools', (route) => route.fulfill({
    json: { tools: [...TOOL_CATALOG, { name: capability, description: role, is_handoff: false, source: 'local' }] },
  }));
  state.draft.agents[0].name = specialist;
  state.draft.agents[0].description = role;
  state.draft.scenario.agents[1] = specialist;
  state.draft.scenario.handoffs[0].to_agent = specialist;
  state.draft.scenario.name = 'InternationalCustomerServiceAndAccountResolutionScenario';
  state.draft.scenario.global_template_vars.company_name = 'Northwind International Customer Services';
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'Quick Tune workspace' });
  await expect(panel.getByRole('button', { name: /^Voice & model/ })).toBeVisible();
  return { panel, state };
}

for (const viewport of [
  { name: 'desktop', width: 1600, height: 1000 },
  { name: 'tablet', width: 1024, height: 900 },
  { name: 'mobile', width: 390, height: 844 },
]) {
  test.describe(`Authoring layout ${viewport.name}`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test('contains long model and agent text in the compact editor', async ({ page }, testInfo) => {
      const { panel, state } = await prepare(page);
      await expect(panel).toBeInViewport({ ratio: 0.98 });
      await page.screenshot({
        path: testInfo.outputPath(`quick-tune-${viewport.name}.png`),
        animations: 'disabled',
      });
      expect(await layoutViolations(panel)).toEqual([]);
      await panel.getByRole('combobox', { name: `Model ${deployment}`, exact: true }).click();
      const models = page.getByRole('listbox');
      await expect(models).toBeInViewport({ ratio: 0.98 });
      expect(await layoutViolations(models)).toEqual([]);
      await models.getByRole('option', { name: deployment, exact: true }).click();
      await panel.getByRole('button', { name: /^Behavior/ }).click();
      await expect(panel.getByRole('textbox', { name: 'Role', exact: true })).toHaveValue(role);
      expect(await layoutViolations(panel)).toEqual([]);
      await panel.getByRole('button', { name: /^Tools/ }).click();
      await panel.getByRole('textbox', { name: 'Find capabilities', exact: true }).fill(capability);
      await expect(panel.getByRole('checkbox', { name: `Use ${capability}`, exact: true })).toBeVisible();
      expect(await layoutViolations(panel)).toEqual([]);
      await panel.getByRole('button', { name: 'Expand workspace', exact: true }).click();
      expect(await layoutViolations(panel)).toEqual([]);
      expect(state.calls).toHaveLength(0);
      await expect(panel.getByRole('button', { name: 'Close Quick Tune', exact: true })).toBeInViewport();
    });

    test('keeps create and refine prompt labels clear of the outline', async ({ page }, testInfo) => {
      const { panel, state } = await prepare(page);
      await panel.getByRole('tab', { name: 'Create scenario', exact: true }).click();
      const prompt = panel.getByRole('textbox', { name: 'What should this scenario do?', exact: true });
      const clearance = (field) => field.evaluate((element) => {
        const label = document.querySelector(`label[for="${CSS.escape(element.id)}"]`);
        const outline = element.closest('.MuiOutlinedInput-root');
        return outline.getBoundingClientRect().top - label.getBoundingClientRect().bottom;
      });
      await panel.locator('label').filter({ hasText: /^What should this scenario do\?$/ }).click();
      await expect(prompt).toBeFocused();
      expect(await clearance(prompt)).toBeGreaterThanOrEqual(6);
      await prompt.fill('Help customers with their banking questions.');
      expect(await clearance(prompt)).toBeGreaterThanOrEqual(6);
      await prompt.blur();
      expect(await clearance(prompt)).toBeGreaterThanOrEqual(6);
      await page.screenshot({
        path: testInfo.outputPath(`scenario-prompt-label-${viewport.name}.png`),
        animations: 'disabled',
      });
      expect(await layoutViolations(panel)).toEqual([]);
      await panel.getByRole('button', { name: 'Generate draft', exact: true }).click();
      await page.getByRole('dialog', { name: 'Review the generated scenario', exact: true })
        .getByRole('button', { name: 'Close graphical editor', exact: true }).click();
      const refinement = panel.getByRole('textbox', { name: 'Describe a refinement', exact: true });
      await refinement.focus();
      expect(await clearance(refinement)).toBeGreaterThanOrEqual(6);
      expect(state.calls.map((call) => call.type)).toEqual(['generate']);
    });

    test('keeps graph review and its inspector usable with long agent names', async ({ page }, testInfo) => {
      const { panel, state } = await prepare(page);
      await panel.getByRole('tab', { name: 'Create scenario', exact: true }).click();
      await panel.getByRole('textbox', { name: 'What should this scenario do?' })
        .fill('Create customer support with an international account specialist.');
      await panel.getByRole('button', { name: 'Generate draft', exact: true }).click();
      const dialog = page.getByRole('dialog', { name: 'Review the generated scenario' });
      await expect(dialog).toBeVisible();
      await expect(dialog).toBeInViewport({ ratio: 0.98 });
      await page.screenshot({
        path: testInfo.outputPath(`graph-${viewport.name}.png`),
        animations: 'disabled',
      });
      expect(await layoutViolations(dialog)).toEqual([]);
      const canvas = dialog.getByTestId('graph-canvas');
      const canvasBounds = await canvas.boundingBox();
      expect(canvasBounds.width).toBeGreaterThan(viewport.name === 'mobile' ? 250 : 450);
      const node = dialog.getByTestId(`graph-node-${specialist}`);
      await expect(node).toBeInViewport({ ratio: 0.98 });
      expect(await node.evaluate((element) => {
        const bounds = element.getBoundingClientRect();
        return [...element.querySelectorAll('.MuiTypography-root')].every((text) => {
          const rect = text.getBoundingClientRect();
          return rect.left >= bounds.left && rect.right <= bounds.right;
        });
      })).toBe(true);

      if (viewport.name === 'mobile') {
        await dialog.getByRole('button', { name: 'Show available agents' }).click();
        const palette = dialog.getByRole('region', { name: 'Available agents', exact: true });
        await expect(palette.getByRole('button', { name: 'Add FraudAgent to flow' })).toBeVisible();
        expect(await layoutViolations(dialog)).toEqual([]);
        await dialog.getByRole('button', { name: 'Close available agents' }).click();
        await dialog.getByRole('button', { name: 'Show scenario flow' }).click();
      }
      await dialog.getByRole('button', { name: `Edit handoff from BankingConcierge to ${specialist}`, exact: true }).click();
      const handoff = page.getByRole('dialog', { name: 'Edit Handoff', exact: true });
      await expect(handoff).toBeInViewport({ ratio: 0.98 });
      await page.screenshot({
        path: testInfo.outputPath(`handoff-${viewport.name}.png`),
        animations: 'disabled',
      });
      expect(await layoutViolations(handoff)).toEqual([]);
      await handoff.getByRole('button', { name: `Change target agent: ${specialist}`, exact: true }).click();
      const choices = page.locator('.MuiPopover-paper');
      await expect(choices).toBeInViewport({ ratio: 0.98 });
      expect(await layoutViolations(choices)).toEqual([]);
      await choices.getByRole('menuitem', { name: new RegExp(`^${specialist}`) }).click();
      await handoff.getByRole('textbox', { name: 'Handoff condition', exact: true }).fill(role);
      await handoff.getByRole('button', { name: 'Save Changes', exact: true }).click();
      if (viewport.name === 'mobile') await dialog.getByRole('button', { name: 'Close scenario flow' }).click();
      await dialog.getByTestId(`graph-node-${specialist}`)
        .getByRole('button', { name: 'View agent details' }).click();
      await expect(dialog.getByRole('textbox', { name: 'Agent name', exact: true })).toHaveValue(specialist);
      await page.screenshot({
        path: testInfo.outputPath(`inspector-${viewport.name}.png`),
        animations: 'disabled',
      });
      expect(await layoutViolations(dialog)).toEqual([]);
      const inspector = dialog.getByRole('region', { name: 'Agent inspector' });
      expect((await inspector.boundingBox()).height).toBeGreaterThan(350);
      await expect(dialog.getByRole('button', { name: 'Close graphical editor', exact: true })).toBeInViewport();
      await expect(dialog.getByRole('button', { name: 'Apply scenario', exact: true })).toBeInViewport();
      await dialog.getByRole('button', { name: 'Close inspector', exact: true }).click();
      await expect(canvas).toBeVisible();
      await dialog.getByRole('button', { name: 'Close graphical editor', exact: true }).click();
      expect(await layoutViolations(panel)).toEqual([]);
      expect(state.calls.map((call) => call.type)).toEqual(['generate']);
    });
  });
}
