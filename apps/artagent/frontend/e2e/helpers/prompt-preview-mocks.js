export async function installPromptPreviewMocks(page) {
  const state = { calls: [], failure: null, failureStatus: 503, diagnostics: [], missing: [], delay: 0 };
  await page.route('**/api/v1/agent-builder/prompt-preview?*', async (route) => {
    const body = route.request().postDataJSON();
    state.calls.push(body);
    const company = body.scenario?.agent_defaults?.template_vars?.company_name
      ?? body.scenario?.global_template_vars?.company_name ?? body.template_vars.company_name;
    const diagnostics = structuredClone(state.diagnostics);
    const response = {
      mode: body.mode,
      scenario_name: body.scenario?.name || null,
      variables: [
        { path: 'caller_name', expression: '{{ caller_name }}', source: 'Session profile', type: 'string', value_preview: 'Ava Harper', available: true, sensitive: false },
        { path: 'customer_intelligence.preferences.language', expression: '{{ customer_intelligence.preferences.language }}', source: 'Session profile', type: 'string', value_preview: 'English', available: true, sensitive: false },
        { path: 'company_name', expression: '{{ company_name }}', source: 'Scenario context', type: 'string', value_preview: company ?? '', available: company !== undefined, sensitive: false },
        { path: 'optional_note', expression: '{{ optional_note }}', source: 'Referenced variable', type: 'unknown', value_preview: '', available: false, sensitive: false },
        { path: 'session_profile.verification_code', expression: '{{ session_profile.verification_code }}', source: 'Session profile', type: 'string', value_preview: '', available: false, sensitive: true },
      ],
      rendered_prompt: diagnostics.length ? null : body.prompt
        .replace(/\{\{\s*caller_name\s*\}\}/g, 'Ava Harper')
        .replace(/\{\{\s*company_name\s*\}\}/g, company ?? '')
        .replace(/\{\{\s*raw_markup\s*\}\}/g, '<b>literal markup</b>'),
      errors: diagnostics,
      missing_variables: [...state.missing],
      warnings: [],
    };
    const failure = state.failure;
    if (state.delay) await new Promise((resolve) => setTimeout(resolve, state.delay));
    await route.fulfill(failure
      ? { status: state.failureStatus, json: { detail: failure } }
      : { json: response });
  });
  return state;
}
