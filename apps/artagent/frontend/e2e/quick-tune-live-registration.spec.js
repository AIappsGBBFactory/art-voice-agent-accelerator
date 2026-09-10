import { randomUUID } from 'node:crypto';
import { test, expect } from '@playwright/test';

// Explicit opt-in: these tests use real HTTP and Redis, never page.route mocks.
const api = process.env.LOCAL_CONFIG_API;
test.skip(!api, 'Set LOCAL_CONFIG_API to a dedicated local backend for registration checks.');

function agentConfig(name) {
  return {
    name, description: 'Local configuration registration check',
    prompt: 'You are a configuration-check assistant for {{company_name}}. Use only assigned tools.',
    greeting: 'Hello from {{company_name}}.', return_greeting: 'Welcome back.',
    tools: ['get_account_summary'],
    cascade_model: {
      deployment_id: 'gpt-4o', name: 'gpt-4o', temperature: 0.31, top_p: 0.83,
      max_tokens: 777, api_version: 'v1', endpoint_preference: 'chat',
    },
    voicelive_model: {
      deployment_id: 'gpt-4o', name: 'gpt-4o', temperature: 0.71,
      top_p: 0.91, max_tokens: 1200,
    },
    byom: { mode: 'byom-azure-openai-chat-completion' },
    voice: {
      name: 'en-US-AvaMultilingualNeural', type: 'azure-standard',
      style: 'chat', rate: '+9%', pitch: '-6%', endpoint_id: null,
    },
    speech: {
      vad_silence_timeout_ms: 1450, use_semantic_segmentation: true,
      candidate_languages: ['en-US', 'es-ES'], enable_diarization: false, speaker_count_hint: 2,
    },
    session: {
      modalities: ['TEXT', 'AUDIO'], input_audio_format: 'PCM16', output_audio_format: 'PCM16',
      turn_detection_type: 'azure_semantic_vad', turn_detection_threshold: 0.65,
      silence_duration_ms: 1250, prefix_padding_ms: 480, tool_choice: 'auto',
      input_audio_transcription_settings: { model: 'azure-speech', language: 'es-ES' },
    },
    template_vars: { company_name: 'Local registration only' },
  };
}

async function expectSuccess(response) {
  const payload = await response.json();
  expect(response.ok(), JSON.stringify(payload)).toBeTruthy();
  return payload;
}

test.beforeEach(() => {
  expect(['127.0.0.1', 'localhost', '[::1]']).toContain(new URL(api).hostname);
});

test('real HTTP scenario editing and prompt previews share registered context', async ({ request }) => {
  const sid = `qt-prompt-context-${randomUUID()}`;
  const { config: original } = await expectSuccess(await request.get(`${api}/scenario-builder/templates/banking`));
  const edited = {
    ...original, description: 'Temporary Quick Tune integration check.',
    global_template_vars: {
      ...original.global_template_vars, preview_company: 'Preview Scenario Company',
      preview_zero: 0, preview_false: false,
    },
    agent_defaults: {
      ...original.agent_defaults,
      template_vars: { ...original.agent_defaults?.template_vars, preview_layer: 'scenario-default' },
    },
  };
  try {
    await expectSuccess(await request.put(`${api}/scenario-builder/session/${sid}`, { data: edited }));
    const saved = await expectSuccess(await request.get(
      `${api}/scenario-builder/session/${sid}?scenario_name=${encodeURIComponent(edited.name)}`,
    ));
    expect(saved.config.description).toBe(edited.description);
    expect(saved.config.global_template_vars.preview_zero).toBe(0);
    expect(saved.config.global_template_vars.preview_false).toBe(false);
    const catalog = await expectSuccess(await request.get(`${api}/scenario-builder/session/${sid}/scenarios`));
    const listed = catalog.builtin_scenarios.find((item) => item.name === edited.name);
    expect(listed.description).toBe(edited.description);
    expect(listed.is_session_override).toBe(true);
    expect(listed.agent_defaults).toEqual(saved.config.agent_defaults);
    expect(listed.tools).toEqual(saved.config.tools);

    const body = {
      prompt: '{{ preview_company }}|{{ preview_layer }}|{{ preview_zero }}|{{ preview_false }}',
      agent_name: edited.start_agent, template_vars: { preview_company: 'Agent fallback', preview_layer: 'agent' },
      tools: [], scenario: null, mode: 'cascade',
    };
    for (const mode of ['cascade', 'voicelive']) {
      const preview = await expectSuccess(await request.post(
        `${api}/agent-builder/prompt-preview?session_id=${sid}`, { data: { ...body, mode } },
      ));
      expect(preview.errors).toEqual([]);
      expect(preview.rendered_prompt).toBe('Preview Scenario Company|scenario-default|0|False');
      expect(preview.variables.find((item) => item.path === 'preview_zero').available).toBe(true);
      expect(preview.variables.find((item) => item.path === 'preview_false').available).toBe(true);
    }
    const draft = {
      ...edited, global_template_vars: { ...edited.global_template_vars, preview_company: 'Unapplied draft' },
    };
    const preview = await expectSuccess(await request.post(
      `${api}/agent-builder/prompt-preview?session_id=${sid}`, { data: { ...body, scenario: draft } },
    ));
    expect(preview.errors).toEqual([]);
    expect(preview.rendered_prompt).toBe('Unapplied draft|scenario-default|0|False');
    const unchanged = await expectSuccess(await request.get(
      `${api}/scenario-builder/session/${sid}?scenario_name=${encodeURIComponent(edited.name)}`,
    ));
    expect(unchanged.config.global_template_vars.preview_company).toBe('Preview Scenario Company');
    const template = await expectSuccess(await request.get(`${api}/scenario-builder/templates/banking`));
    expect(template.config).toEqual(original);
  } finally {
    const reset = await request.delete(`${api}/scenario-builder/session/${sid}`);
    const deleted = await request.delete(`${api}/sessions/${sid}`);
    expect([200, 404]).toContain(reset.status());
    expect([200, 404]).toContain(deleted.status());
  }
});

test('real HTTP registration preserves every configuration group and BYOM profile', async ({ request }) => {
  const sid = `qt-registration-${randomUUID()}`;
  const config = agentConfig('RegistrationAgent');
  try {
    await expectSuccess(await request.put(`${api}/agent-builder/session/${sid}?create_only=true&activate=false`, {
      data: config,
    }));
    for (const [mode, deployment] of [
      ['byom-azure-openai-realtime', 'gpt-realtime'],
      ['byom-azure-openai-chat-completion', 'gpt-4o'],
      ['byom-foundry-anthropic-messages', 'claude-sonnet'],
    ]) {
      config.byom.mode = mode;
      config.voicelive_model.deployment_id = deployment;
      config.voicelive_model.name = deployment;
      await expectSuccess(await request.put(`${api}/agent-builder/session/${sid}?activate=false`, { data: config }));
      const saved = await expectSuccess(await request.get(`${api}/agent-builder/session/${sid}?agent_name=${config.name}`));
      for (const field of ['name', 'description', 'greeting', 'return_greeting', 'tools', 'byom', 'voice', 'speech', 'template_vars']) {
        expect(saved.config[field], field).toEqual(config[field]);
      }
      expect(saved.config.prompt_full).toBe(config.prompt);
      expect(saved.config.cascade_model).toMatchObject(config.cascade_model);
      expect(saved.config.voicelive_model).toMatchObject(config.voicelive_model);
      expect(saved.config.session.turn_detection).toEqual({
        type: config.session.turn_detection_type,
        threshold: config.session.turn_detection_threshold,
        silence_duration_ms: config.session.silence_duration_ms,
        prefix_padding_ms: config.session.prefix_padding_ms,
      });
      expect(saved.config.session.input_audio_transcription_settings)
        .toEqual(config.session.input_audio_transcription_settings);
    }
  } finally {
    await request.delete(`${api}/sessions/${sid}`);
  }
});

test('real HTTP scenario registration preserves agents, routing and context', async ({ request }) => {
  const sid = `qt-scenario-registration-${randomUUID()}`;
  const first = agentConfig('ScenarioEntry');
  const second = agentConfig('ScenarioSpecialist');
  const scenario = {
    name: 'Scenario registration check',
    description: 'Configuration-only fixture; no customer actions are executed.',
    agents: [first.name, second.name],
    start_agent: first.name,
    handoff_type: 'announced',
    handoffs: [{
      from_agent: first.name, to_agent: second.name, tool: 'handoff_to_agent',
      type: 'announced', share_context: true, handoff_condition: 'When specialist help is requested.',
      context_vars: { 'handoff_context.topic': 'registration check' },
    }],
    global_template_vars: { company_name: 'Scenario registration value' },
    agent_defaults: { greeting: 'Welcome to {{company_name}}.', voice_rate: '-5%' },
  };
  try {
    await expectSuccess(await request.post(`${api}/scenario-builder/apply-draft?session_id=${sid}`, {
      data: { summary: 'Hand-authored registration fixture.', scenario, agents: [first, second] },
    }));
    const stored = await expectSuccess(await request.get(`${api}/scenario-builder/session/${sid}`));
    expect(stored.config).toMatchObject(scenario);
    const available = await expectSuccess(await request.get(`${api}/scenario-builder/agents?session_id=${sid}`));
    for (const name of scenario.agents) {
      const agent = available.agents.find((item) => (item.original_name || item.name) === name);
      expect(agent, name).toBeTruthy();
      expect(agent.is_session_agent).toBe(true);
      expect(agent.tools).toContain('get_account_summary');
    }
    const changed = structuredClone(stored.config);
    changed.start_agent = second.name;
    changed.handoffs = [{
      ...changed.handoffs[0], from_agent: second.name, to_agent: first.name,
      type: 'discrete', share_context: false, handoff_condition: 'When returning to the entry agent.',
    }];
    await expectSuccess(await request.put(`${api}/scenario-builder/session/${sid}`, { data: changed }));
    const updated = await expectSuccess(await request.get(`${api}/scenario-builder/session/${sid}`));
    expect(updated.config).toEqual(changed);
  } finally {
    await request.delete(`${api}/sessions/${sid}`);
  }
});

test('browser edits register in the real agent and scenario stores', async ({ page, request }, testInfo) => {
  const sid = `qt-browser-registration-${randomUUID()}`;
  const first = agentConfig('LocalConcierge');
  const second = agentConfig('LocalSpecialist');
  const scenario = {
    name: 'Local registration demo',
    agents: [first.name, second.name],
    start_agent: first.name,
    handoffs: [{
      from_agent: first.name, to_agent: second.name, tool: 'handoff_to_agent',
      handoff_condition: 'When specialist help is requested.', type: 'announced',
      share_context: true, context_vars: {},
    }],
    global_template_vars: { company_name: 'Scenario registration value' },
  };
  try {
    await expectSuccess(await request.post(`${api}/scenario-builder/apply-draft?session_id=${sid}`, {
      data: { summary: 'Hand-authored registration fixture, not an AI generation result.', scenario, agents: [first, second] },
    }));
    await page.goto(`/?session_id=${sid}`);
    await page.getByRole('button', { name: 'Open Quick Tune', exact: true }).click();
    const panel = page.getByRole('complementary', { name: 'Quick Tune workspace' });
    await expect(panel.getByRole('combobox', { name: 'Agent to tune' })).toHaveValue(first.name);
    await panel.getByRole('button', { name: /^Behavior/ }).click();
    await panel.getByRole('textbox', { name: 'First greeting', exact: true }).fill('A real local registration update.');
    await panel.getByRole('button', { name: /^Voice & model/ }).click();
    const rate = panel.getByRole('slider', { name: 'Speaking rate', exact: true });
    await rate.focus();
    await rate.press('End');
    await rate.press('ArrowLeft');
    await panel.getByRole('button', { name: 'Save changes', exact: true }).click();
    await expect(panel.getByRole('status')).toContainText('Saved for the next connection');
    const updated = await expectSuccess(await request.get(`${api}/agent-builder/session/${sid}?agent_name=${first.name}`));
    expect(updated.config.greeting).toBe('A real local registration update.');
    expect(updated.config.voice.rate).toBe('+49%');
    expect(updated.config.speech).toEqual(first.speech);
    expect(updated.config.cascade_model).toMatchObject(first.cascade_model);

    await panel.getByRole('tab', { name: 'Edit scenario', exact: true }).click();
    await panel.getByRole('textbox', { name: 'When should this handoff happen?' }).fill('When the caller asks for specialist assistance.');
    await panel.getByRole('checkbox', { name: 'Share conversation context' }).uncheck();
    await panel.getByRole('combobox', { name: 'Transfer style' }).click();
    await page.getByRole('option', { name: 'Transfer silently', exact: true }).click();
    await panel.getByRole('button', { name: 'Save scenario', exact: true }).click();
    await expect(panel.getByText('Scenario saved and selected. Start a conversation to try it.')).toBeVisible();
    const updatedScenario = await expectSuccess(await request.get(`${api}/scenario-builder/session/${sid}`));
    expect(updatedScenario.config.start_agent).toBe(first.name);
    expect(updatedScenario.config.handoffs[0]).toMatchObject({
      tool: 'handoff_to_agent', type: 'discrete', share_context: false,
      handoff_condition: 'When the caller asks for specialist assistance.',
    });
    expect(updatedScenario.config.global_template_vars).toEqual(scenario.global_template_vars);
    await page.screenshot({ path: testInfo.outputPath('real-local-registration.png') });
  } finally {
    await request.delete(`${api}/sessions/${sid}`);
  }
});
