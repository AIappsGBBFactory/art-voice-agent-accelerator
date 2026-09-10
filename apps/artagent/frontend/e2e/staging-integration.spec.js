import { test, expect } from '@playwright/test';
import { installQuickTuneMocks } from './helpers/quick-tune-mocks.js';

test('Quick Tune uses the correct resource for each model list and retains region attribution', async ({ page }) => {
  await installQuickTuneMocks(page);
  const modes = [];
  await page.route('**/api/v1/agent-builder/models?*', (route) => {
    const mode = new URL(route.request().url()).searchParams.get('mode');
    modes.push(mode);
    return route.fulfill({
      json: {
        models: [{
          deployment_id: mode === 'voicelive' ? 'voice-only-deployment' : 'cascade-only-deployment',
          category: 'chat', arch: 'cascaded', modes: ['cascade', 'voicelive'],
        }],
        resource_name: mode === 'voicelive' ? 'voice-foundry' : 'primary-foundry',
        region: mode === 'voicelive' ? 'westus2' : 'eastus',
        app_region: 'eastus',
      },
    });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'Quick Tune workspace' });
  const source = panel.getByRole('combobox', { name: /^Model source/ });
  await source.click();
  await page.getByRole('option', { name: 'My Foundry chat deployment', exact: true }).click();
  await expect(panel.getByText(/Deployments from your connected resource.*voice-foundry.*westus2/)).toBeVisible();
  await panel.getByRole('combobox', { name: /^Model (?!source)/ }).click();
  const options = page.getByRole('listbox');
  await expect(options.getByRole('option', { name: 'voice-only-deployment', exact: true })).toBeVisible();
  await expect(options.getByRole('option', { name: 'cascade-only-deployment', exact: true })).toHaveCount(0);
  await options.getByRole('option', { name: 'voice-only-deployment', exact: true }).click();
  await panel.getByRole('button', { name: 'Custom Speech', exact: true }).click();
  await expect(panel.getByText(/Deployments from your connected resource.*primary-foundry.*eastus/)).toBeVisible();
  await panel.getByRole('combobox', { name: /^Model / }).click();
  await expect(page.getByRole('option', { name: 'cascade-only-deployment', exact: true })).toBeVisible();
  await expect(page.getByRole('option', { name: 'voice-only-deployment', exact: true })).toHaveCount(0);
  expect(new Set(modes)).toEqual(new Set(['cascade', 'voicelive']));
});

test('non-managed VoiceLive deployments require an explicit BYOM profile', async ({ page }) => {
  const state = await installQuickTuneMocks(page);
  state.agents.BankingConcierge.voicelive_model.deployment_id = 'my-custom-chat';
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'Quick Tune workspace' });
  await expect(panel.getByText(/my-custom-chat is not a managed VoiceLive model/)).toBeVisible();
  await panel.getByRole('button', { name: /^Behavior/ }).click();
  await panel.getByRole('textbox', { name: 'Role', exact: true }).fill('Custom chat support');
  await expect(panel.getByRole('button', { name: 'Save changes', exact: true })).toBeDisabled();
  await panel.getByRole('button', { name: /^Voice & model/ }).click();
  await panel.getByRole('combobox', { name: /^Model source/ }).click();
  await page.getByRole('option', { name: 'My Foundry chat deployment', exact: true }).click();
  await expect(panel.getByRole('button', { name: 'Save changes', exact: true })).toBeEnabled();
  expect(state.calls).toEqual([]);
});

test('regional discovery with documented HD additions is not mislabeled as a presets-only backend', async ({ page }) => {
  await installQuickTuneMocks(page);
  await page.route('**/api/v1/agent-builder/voices{,?*}', (route) => route.fulfill({
    json: {
      voices: [
        { name: 'en-US-AvaMultilingualNeural', display_name: 'Ava', region_verified: true },
        { name: 'en-US-Ava:DragonHDLatestNeural', display_name: 'Ava HD', region_verified: false },
      ],
      source: 'region-validated', region: 'northcentralus',
      hd_from_catalog: true, total_available: 2, catalog_complete: false,
    },
  }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'Quick Tune workspace' });
  await expect(panel.getByText('2 catalog voices for northcentralus; documented HD entries are unverified.')).toBeVisible();
  await expect(panel.getByText(/This backend does not expose the full catalog/)).toHaveCount(0);
});
