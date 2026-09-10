import { test, expect } from '@playwright/test';
import { installQuickTuneMocks } from './helpers/quick-tune-mocks.js';

async function prepare(page, { configure = () => {}, maiVoices = true, supported = true } = {}) {
  const state = await installQuickTuneMocks(page);
  configure(state.agents.BankingConcierge);
  await page.route('**/api/v1/agent-builder/voices{,?*}', (route) => route.fulfill({
    json: {
      source: 'regional-service', region: maiVoices ? 'eastus' : 'northcentralus',
      catalog_complete: true, verified_against_region: true,
      runtime_transcription_models: supported ? {
        cascade: ['azure-speech', 'mai-transcribe'],
        voicelive: ['mai-transcribe', 'azure-speech', 'whisper-1'],
      } : {},
      voices: [
        { name: 'en-US-AvaMultilingualNeural', display_name: 'Ava', language: 'en-US', category: 'standard' },
        ...(maiVoices ? [
          { name: 'en-US-Harper:MAI-Voice-2', display_name: 'Harper', language: 'en-US', category: 'mai' },
          { name: 'en-US-Ethan:MAI-Voice-2-Flash', display_name: 'Ethan', language: 'en-US', category: 'mai' },
        ] : []),
      ],
    },
  }));
  await page.goto('/');
  await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
  const panel = page.getByRole('complementary', { name: 'Quick Tune workspace' });
  await expect(panel.getByRole('combobox', { name: /^Input transcription/ })).toBeVisible();
  return { panel, state };
}

async function chooseMai(page, panel) {
  await panel.getByRole('combobox', { name: /^Input transcription/ }).click();
  const option = page.getByRole('option', { name: 'MAI Transcribe (preview)', exact: true });
  await expect(option).toBeEnabled();
  await option.click();
}

test('MAI voices and input are first in both modes without changing defaults', async ({ page }) => {
  const { panel, state } = await prepare(page);
  for (const mode of ['VoiceLive', 'Custom Speech']) {
    await panel.getByRole('button', { name: mode, exact: true }).click();
    const voice = panel.getByRole('combobox', { name: 'Voice', exact: true });
    await voice.fill('');
    await voice.press('ArrowDown');
    const voices = page.getByRole('listbox');
    await expect(voices.getByRole('option').first()).toHaveAttribute('aria-label', /MAI-Voice-2-Flash/);
    await voice.press('Escape');
    await panel.getByRole('combobox', { name: /^Input transcription/ }).click();
    await expect(page.getByRole('listbox').getByRole('option').first()).toHaveText('MAI Transcribe (preview)');
    await page.getByRole('listbox').press('Escape');
  }
  expect(state.calls).toEqual([]);
  expect(state.agents.BankingConcierge.voicelive_model.deployment_id).toBe('gpt-realtime');
  expect(state.agents.BankingConcierge.voice.name).toBe('en-US-AvaMultilingualNeural');
});

test('MAI input requires an explicit switch from native VoiceLive to a managed text pipeline', async ({ page }) => {
  const { panel, state } = await prepare(page);
  await chooseMai(page, panel);
  await expect(panel.getByText(/MAI Transcribe requires a text-based VoiceLive model/)).toBeVisible();
  await expect(panel.getByRole('button', { name: 'Save changes', exact: true })).toBeDisabled();
  expect(state.calls).toEqual([]);
  await panel.getByRole('button', { name: 'Use managed gpt-4.1', exact: true }).click();
  await panel.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(panel.getByText(/Saved for the next connection/)).toBeVisible();
  const saved = state.calls.find((call) => call.type === 'save-agent').body;
  expect(saved.voicelive_model.deployment_id).toBe('gpt-4.1');
  expect(saved.byom).toBeNull();
  expect(saved.session.input_audio_transcription_settings.model).toBe('mai-transcribe');
});

test('explicit BYOM chat retains the user deployment while enabling MAI input', async ({ page }) => {
  const { panel, state } = await prepare(page, { configure: (config) => {
    config.byom = { mode: 'byom-azure-openai-chat-completion' };
    config.voicelive_model.deployment_id = 'customer-chat-deployment';
  } });
  await chooseMai(page, panel);
  await panel.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(panel.getByText(/Saved for the next connection/)).toBeVisible();
  const saved = state.calls.find((call) => call.type === 'save-agent').body;
  expect(saved.voicelive_model.deployment_id).toBe('customer-chat-deployment');
  expect(saved.byom.mode).toBe('byom-azure-openai-chat-completion');
  expect(saved.session.input_audio_transcription_settings.model).toBe('mai-transcribe');
});

test('incompatible Azure-only input options are removed only by explicit action', async ({ page }) => {
  const { panel, state } = await prepare(page, { configure: (config) => {
    config.voicelive_model.deployment_id = 'gpt-4.1';
    config.session.input_audio_transcription_settings = {
      model: 'azure-speech', language: 'en', custom_speech: { en: 'custom-model' }, phrase_list: ['Contoso'],
    };
  } });
  await chooseMai(page, panel);
  await expect(panel.getByRole('button', { name: 'Save changes', exact: true })).toBeDisabled();
  await panel.getByRole('button', { name: 'Remove Azure-only options', exact: true }).click();
  await panel.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(panel.getByText(/Saved for the next connection/)).toBeVisible();
  expect(state.calls.find((call) => call.type === 'save-agent').body.session.input_audio_transcription_settings)
    .toEqual({ model: 'mai-transcribe', language: 'en' });
});

test('Custom Speech MAI input preserves the separate LLM and VoiceLive configuration', async ({ page }) => {
  const { panel, state } = await prepare(page, { configure: (config) => {
    config.speech.use_semantic_segmentation = true;
    config.speech.enable_diarization = true;
  } });
  const original = structuredClone(state.agents.BankingConcierge);
  await panel.getByRole('button', { name: 'Custom Speech', exact: true }).click();
  await chooseMai(page, panel);
  await expect(panel.getByRole('button', { name: 'Save changes', exact: true })).toBeDisabled();
  await panel.getByRole('button', { name: 'Use MAI live input settings', exact: true }).click();
  await panel.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(panel.getByText(/Saved for the next connection/)).toBeVisible();
  const saved = state.calls.find((call) => call.type === 'save-agent').body;
  expect(saved.speech.transcription_model).toBe('mai-transcribe');
  expect(saved.speech.use_semantic_segmentation).toBe(true);
  expect(saved.speech.enable_diarization).toBe(false);
  expect(saved.cascade_model).toEqual(original.cascade_model);
  expect(saved.voicelive_model).toEqual(original.voicelive_model);
  expect(saved.session).toEqual(original.session);
  expect(saved.voice).toEqual(original.voice);
});

test('MAI voice uses Azure output without unnecessarily changing the LLM pipeline', async ({ page }) => {
  const { panel, state } = await prepare(page, { configure: (config) => {
    config.voice.type = 'azure-custom';
    config.voice.endpoint_id = 'old-custom-endpoint';
  } });
  await panel.getByRole('combobox', { name: 'Voice', exact: true }).fill('Ethan');
  await page.getByRole('option', { name: /Ethan.*MAI-Voice-2-Flash/ }).click();
  await panel.getByRole('button', { name: 'Save changes', exact: true }).click();
  await expect(panel.getByText(/Saved for the next connection/)).toBeVisible();
  const saved = state.calls.find((call) => call.type === 'save-agent').body;
  expect(saved.voice.name).toBe('en-US-Ethan:MAI-Voice-2-Flash');
  expect(saved.voice.type).toBe('azure-standard');
  expect(saved.voice.endpoint_id).toBeNull();
  expect(saved.voicelive_model.deployment_id).toBe('gpt-realtime');
});

test('missing regional voices and older backends show MAI options as unavailable', async ({ page }) => {
  const { panel, state } = await prepare(page, { maiVoices: false, supported: false });
  await panel.getByRole('combobox', { name: 'Voice', exact: true }).fill('MAI');
  const choices = page.getByRole('listbox').getByRole('option');
  await expect(choices).toHaveCount(4);
  for (const choice of await choices.all()) await expect(choice).toHaveAttribute('aria-disabled', 'true');
  await panel.getByRole('combobox', { name: 'Voice', exact: true }).press('Escape');
  await panel.getByRole('combobox', { name: /^Input transcription/ }).click();
  await expect(page.getByRole('option', { name: /MAI Transcribe.*backend update required/ })).toHaveAttribute('aria-disabled', 'true');
  expect(state.calls).toEqual([]);
});
