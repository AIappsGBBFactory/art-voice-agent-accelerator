import { test, expect } from '@playwright/test';
import { installQuickTuneMocks } from './helpers/quick-tune-mocks.js';
import { layoutViolations } from './helpers/authoring-layout.js';

const voices = [
  {
    name: 'en-US-AvaMultilingualNeural', display_name: 'Ava', language: 'en-US',
    category: 'standard', gender: 'Female', styles: [], status: 'GA',
  },
  {
    name: 'fr-FR-DeniseNeural', display_name: 'Denise', language: 'fr-FR',
    category: 'standard', gender: 'Female', styles: ['cheerful'], status: 'GA',
  },
  {
    name: 'ja-JP-NanamiNeural', display_name: 'Nanami', language: 'ja-JP',
    category: 'standard', gender: 'Female', styles: [], status: 'GA',
  },
];

async function prepare(page, gate = null) {
  const state = await installQuickTuneMocks(page);
  state.voiceRequests = [];
  state.voiceFailure = false;
  state.voiceCatalog = {
    voices: structuredClone(voices), source: 'regional-service', region: 'westus2',
    catalog_complete: true, verified_against_region: true, total_available: voices.length, warnings: [],
  };
  await page.route('**/api/v1/agent-builder/voices{,?*}', async (route) => {
    state.voiceRequests.push(route.request().url());
    if (gate) await gate;
    await route.fulfill(state.voiceFailure
      ? { status: 503, json: { detail: 'Regional voice catalog unavailable.' } }
      : { json: state.voiceCatalog });
  });
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'Quick Tune workspace' });
  await expect(panel.getByRole('slider', { name: 'Speaking rate', exact: true })).toBeVisible();
  return { state, panel };
}

test('searches all returned voices by language, identifier, and style', async ({ page }) => {
  const { state, panel } = await prepare(page);
  await expect(panel.getByText('3 voices from westus2.', { exact: true })).toBeVisible();
  const voice = panel.getByRole('combobox', { name: 'Voice', exact: true });
  for (const term of ['French', 'fr-FR-DeniseNeural', 'cheerful']) {
    await voice.fill(term);
    await expect(page.getByRole('option', { name: /Denise.*fr-FR-DeniseNeural/ })).toBeVisible();
  }
  await voice.fill('Japanese');
  await expect(page.getByRole('option', { name: /Nanami.*ja-JP-NanamiNeural/ })).toBeVisible();
  expect(state.calls).toEqual([]);
});

for (const mode of ['VoiceLive', 'Custom Speech']) {
  test(`saves the exact regional voice identifier in ${mode} without changing other settings`, async ({ page }) => {
    const { state, panel } = await prepare(page);
    const original = structuredClone(state.agents.BankingConcierge);
    await panel.getByRole('button', { name: mode, exact: true }).click();
    await panel.getByRole('combobox', { name: 'Voice', exact: true }).fill('French');
    await page.getByRole('option', { name: /Denise.*fr-FR-DeniseNeural/ }).click();
    await panel.getByRole('button', { name: 'Save changes', exact: true }).click();
    await expect(panel.getByText(/Saved for the next connection/)).toBeVisible();
    const saved = state.calls.find((call) => call.type === 'save-agent').body;
    expect(saved.voice).toEqual({ ...original.voice, name: 'fr-FR-DeniseNeural' });
    for (const field of ['prompt', 'tools', 'cascade_model', 'voicelive_model', 'speech', 'session']) {
      expect(saved[field]).toEqual(original[field]);
    }
  });
}

test('regional discovery does not hold up the rest of the agent editor', async ({ page }) => {
  let release;
  const gate = new Promise((resolve) => { release = resolve; });
  try {
    const { panel } = await prepare(page, gate);
    await expect(panel.getByText('Loading the regional Speech voice catalog...')).toBeVisible();
    await panel.getByRole('button', { name: /^Behavior/ }).click();
    await expect(panel.getByRole('textbox', { name: 'Instructions', exact: true })).toBeVisible();
    release();
    await panel.getByRole('button', { name: /^Voice & model/ }).click();
    await expect(panel.getByText('3 voices from westus2.', { exact: true })).toBeVisible();
  } finally {
    release?.();
  }
});

test('refresh bypasses the cache and preserves a voice no longer in the returned list', async ({ page }) => {
  const { state, panel } = await prepare(page);
  await expect(panel.getByText('3 voices from westus2.', { exact: true })).toBeVisible();
  const voice = panel.getByRole('combobox', { name: 'Voice', exact: true });
  await voice.fill('French');
  await page.getByRole('option', { name: /Denise.*fr-FR-DeniseNeural/ }).click();
  state.voiceCatalog.voices = state.voiceCatalog.voices.filter((item) => item.language !== 'fr-FR');
  state.voiceCatalog.total_available = 2;
  await panel.getByRole('button', { name: 'Refresh regional voice catalog', exact: true }).click();
  await expect(panel.getByText('2 voices from westus2.', { exact: true })).toBeVisible();
  await expect(voice).toHaveValue('fr-FR-DeniseNeural');
  await expect(panel.getByText(/The current voice was not returned by this resource/)).toBeVisible();
  expect(state.voiceRequests.some((url) => url.endsWith('?use_cache=false'))).toBe(true);
  expect(state.calls).toEqual([]);
});

test('labels local-only and preset catalogs instead of implying full regional availability', async ({ page }) => {
  const { state, panel } = await prepare(page);
  await expect(panel.getByText('3 voices from westus2.', { exact: true })).toBeVisible();
  state.voiceCatalog = {
    voices: [{ name: 'en-US-AvaMultilingualNeural', display_name: 'Ava' }],
    source: 'repository-configurations', verified_against_region: false,
  };
  await panel.getByRole('button', { name: 'Refresh regional voice catalog', exact: true }).click();
  await expect(panel.getByText(/Repository voices only/)).toBeVisible();
  state.voiceCatalog.source = 'static-catalog';
  await panel.getByRole('button', { name: 'Refresh regional voice catalog', exact: true }).click();
  await expect(panel.getByText('Limited starter presets. Regional availability is not verified.')).toBeVisible();
});

test('a failed refresh retains the previous catalog and the current selection', async ({ page }) => {
  const { state, panel } = await prepare(page);
  await expect(panel.getByText('3 voices from westus2.', { exact: true })).toBeVisible();
  state.voiceFailure = true;
  await panel.getByRole('button', { name: 'Refresh regional voice catalog', exact: true }).click();
  await expect(panel.getByText(/Could not refresh the regional voice catalog/)).toBeVisible();
  await expect(panel.getByRole('combobox', { name: 'Voice', exact: true })).toHaveValue('Ava');
  expect(state.calls).toEqual([]);
});

test('voice metadata and multilingual options stay contained on mobile', async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const { panel } = await prepare(page);
  await expect(panel.getByText('3 voices from westus2.', { exact: true })).toBeVisible();
  await panel.getByRole('combobox', { name: 'Voice', exact: true }).fill('Japanese');
  const list = page.getByRole('listbox');
  await expect(list.getByRole('option', { name: /Nanami.*ja-JP-NanamiNeural/ })).toBeVisible();
  expect(await layoutViolations(list)).toEqual([]);
  await page.screenshot({ path: testInfo.outputPath('regional-voices-mobile.png'), animations: 'disabled' });
  await page.getByRole('option', { name: /Nanami.*ja-JP-NanamiNeural/ }).click();
  expect(await layoutViolations(panel)).toEqual([]);
});
