export function replacePromptSelection(source, start, end, text, selectFrom = text.length, selectTo = selectFrom) {
  const from = Math.max(0, Math.min(start, source.length));
  const to = Math.max(from, Math.min(end, source.length));
  return {
    value: source.slice(0, from) + text + source.slice(to),
    start: from + selectFrom,
    end: from + selectTo,
  };
}

export function promptCaret(source, position) {
  const before = source.slice(0, position);
  const lines = before.split('\n');
  return { line: lines.length, column: lines.at(-1).length + 1 };
}

export function promptScenarioConfig(scenario) {
  if (!scenario) return null;
  const fields = [
    'name', 'description', 'icon', 'agents', 'start_agent', 'handoff_type',
    'handoffs', 'agent_defaults', 'global_template_vars', 'tools',
  ];
  return Object.fromEntries(fields.filter((key) => key in scenario).map((key) => [key, scenario[key]]));
}
