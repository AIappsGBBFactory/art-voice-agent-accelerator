export function scenarioAgentNames(config) {
  return [...new Set([
    ...(config?.agents || []),
    config?.start_agent,
    ...(config?.handoffs || []).flatMap((handoff) => [handoff.from_agent, handoff.to_agent]),
  ].filter(Boolean))];
}

// A bounded excerpt, not a second editor: keep the start and its nearest routes
// readable instead of shrinking a large scenario into an illegible full map.
export function scenarioGraphPreview(config, agents = []) {
  const names = scenarioAgentNames(config);
  const handoffs = config?.handoffs || [];
  const ordered = [...new Set([
    config?.start_agent,
    ...handoffs.filter((handoff) => handoff.from_agent === config?.start_agent)
      .map((handoff) => handoff.to_agent),
    ...names,
  ].filter(Boolean))].slice(0, 3);
  const height = ordered.length > 2 ? 204 : 116;
  const nodes = ordered.map((name, index) => {
    const agent = agents.find((item) => item.name === name);
    return {
      name,
      label: name.replace(/([a-z\d])([A-Z])/g, '$1 $2').replace(/[_-]+/g, ' '),
      isStart: name === config?.start_agent,
      toolCount: Array.isArray(agent?.tools) ? new Set(agent.tools).size : null,
      x: ordered.length === 1 ? 134 : index === 0 ? 12 : 256,
      y: ordered.length < 3 || index === 0 ? (height - 80) / 2 : index === 1 ? 12 : 112,
      width: 188,
      height: 80,
    };
  });
  const edges = handoffs.flatMap((handoff, index) => {
    const from = nodes.find((node) => node.name === handoff.from_agent);
    const to = nodes.find((node) => node.name === handoff.to_agent);
    if (!from || !to) return [];
    const reverse = handoffs.some((other) => other.from_agent === handoff.to_agent
      && other.to_agent === handoff.from_agent);
    let path;
    if (from.x === to.x) {
      const down = from.y < to.y;
      const x = from.x + from.width / 2 + (reverse ? (down ? 12 : -12) : 0);
      const start = down ? from.y + from.height : from.y;
      const end = down ? to.y - 4 : to.y + to.height + 4;
      path = `M ${x} ${start} L ${x} ${end}`;
    } else {
      const right = from.x < to.x;
      const offset = reverse ? (right ? -10 : 10) : 0;
      const x1 = right ? from.x + from.width : from.x;
      const x2 = right ? to.x - 4 : to.x + to.width + 4;
      const y1 = from.y + from.height / 2 + offset;
      const y2 = to.y + to.height / 2 + offset;
      const mid = (x1 + x2) / 2;
      path = `M ${x1} ${y1} C ${mid} ${y1}, ${mid} ${y2}, ${x2} ${y2}`;
    }
    return [{ ...handoff, id: index, path }];
  });
  return { nodes, edges, width: 456, height, agentCount: names.length, handoffCount: handoffs.length };
}
