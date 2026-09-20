// Logical paths only: the HTML transcripts own the narrative and remain usable without JS.
(() => {
  const NS = 'http://www.w3.org/2000/svg';
  const node = (id, column, row, title, detail, status = 'reused') => ({
    id, x: 24 + column * 260, y: row === 0 ? 80 : 410, title, detail, status,
  });
  const edge = (id, from, to, kind, path, label, x, y, duplex = false) => ({
    id, from, to, kind, path, label, x, y, duplex,
  });
  const diagrams = {
    acs: {
      title: 'Current ACS: control, media, and context',
      note: 'BASELINE | ACS remains | Browser direct audio is a separate path',
      nodes: [
        node('pstn', 0, 0, 'PSTN caller', 'ACS number', 'external'),
        node('acs', 1, 0, 'ACS Call Automation', 'Call control + streaming'),
        node('events', 2, 0, 'Event Grid', 'IncomingCall delivery'),
        node('app', 3, 0, 'Python / FastAPI', 'Call + media endpoints'),
        node('human', 0, 1, 'Human destination', 'Separate telephone leg', 'external'),
        node('engine', 1, 1, 'Native AI engine', 'Cascade or VoiceLive'),
        node('policy', 2, 1, 'YAML + tools', 'Agents / scenarios / policy'),
        node('state', 3, 1, 'Redis / Cosmos', 'Configured persistence'),
      ],
      edges: [
        edge('ingress', 'pstn', 'acs', 'control', 'M244 116 H284', 'PSTN call', 264, 63),
        edge('carrierAudio', 'pstn', 'acs', 'media', 'M244 147 H284', 'Carrier media', 264, 193, true),
        edge('incoming', 'acs', 'events', 'control', 'M504 122 H544', 'IncomingCall', 524, 63),
        edge('event', 'events', 'app', 'control', 'M764 122 H804', 'HTTPS event', 784, 63),
        edge('command', 'app', 'acs', 'control', 'M914 80 V30 H394 V80', 'HTTPS create / answer / transfer', 654, 22),
        edge('callback', 'acs', 'app', 'control', 'M434 170 V220 H874 V170', 'HTTPS callbacks (not Event Grid)', 654, 212),
        edge('audio', 'acs', 'app', 'media', 'M394 170 V280 H914 V170', 'Duplex WSS | PCM16 mono 16 kHz', 654, 272, true),
        edge('engine', 'app', 'engine', 'media', 'M974 170 V345 H394 V410', 'Audio + native engine execution', 674, 337, true),
        edge('policy', 'engine', 'policy', 'context', 'M504 455 H544', 'Policy / tools', 524, 525, true),
        edge('state', 'policy', 'state', 'context', 'M764 455 H804', 'Session data', 784, 525, true),
        edge('human', 'acs', 'human', 'control', 'M284 145 H12 V380 H134 V410', 'Transfer attempt', 134, 370),
      ],
    },
    tpe: {
      title: 'Teams Phone via TPE: ACS is retained',
      note: 'PROPOSED INTEGRATION | Public TPE model, reused ACS media | Direct Routing shown',
      nodes: [
        node('carrier', 0, 0, 'Carrier / PSTN', 'Number + connectivity', 'external'),
        node('sbc', 1, 0, 'Certified SBC', 'Direct Routing edge', 'added'),
        node('teams', 2, 0, 'Teams Phone + RA', 'Optional AA / call queue', 'added'),
        node('acs', 3, 0, 'ACS Call Automation', 'Added TPE binding; same media'),
        node('human', 0, 1, 'Human destination', 'Teams / PSTN, if supported', 'external'),
        node('app', 1, 1, 'Python / FastAPI', 'Same ACS protocol'),
        node('engine', 2, 1, 'Native AI engine', 'Cascade or VoiceLive'),
        node('state', 3, 1, 'Definitions + state', 'YAML / tools / Redis / Cosmos'),
      ],
      edges: [
        edge('carrier', 'carrier', 'sbc', 'control', 'M244 116 H284', 'SIP / TLS', 264, 63, true),
        edge('carrierAudio', 'carrier', 'sbc', 'media', 'M244 147 H284', 'RTP / SRTP', 264, 193, true),
        edge('routing', 'sbc', 'teams', 'control', 'M504 116 H544', 'SIP / TLS', 524, 63, true),
        edge('routingAudio', 'sbc', 'teams', 'media', 'M504 147 H544', 'SRTP', 524, 193, true),
        edge('tpe', 'teams', 'acs', 'control', 'M764 116 H804', 'TPE', 784, 63, true),
        edge('tpeAudio', 'teams', 'acs', 'media', 'M764 147 H804', 'Service media', 784, 193, true),
        edge('command', 'app', 'acs', 'control', 'M284 435 H264 V30 H984 V80', 'ACS API + teams_app_source identity', 719, 22),
        edge('event', 'acs', 'app', 'control', 'M854 170 V240 H334 V410', 'Event Grid incoming / direct HTTPS callbacks', 594, 232),
        edge('audio', 'acs', 'app', 'media', 'M914 170 V300 H394 V410', 'Duplex ACS media WSS | 16 kHz', 654, 292, true),
        edge('engine', 'app', 'engine', 'media', 'M504 455 H544', 'Engine I/O', 524, 525, true),
        edge('state', 'engine', 'state', 'context', 'M764 455 H804', 'Policy / state', 784, 525, true),
        edge('human', 'teams', 'human', 'control', 'M654 170 V370 H134 V410', 'Human leg: check scenario-specific limits', 394, 362),
      ],
    },
    graph: {
      title: 'Proposed Graph bot: call control is separate from raw media',
      note: 'PROPOSED | Graph REST v1.0 != media-platform release label | No ACS in this path',
      nodes: [
        node('pstn', 0, 0, 'PSTN connectivity', 'Supported number / route', 'external'),
        node('teams', 1, 0, 'Teams application RA', 'Numbered application instance', 'added'),
        node('graph', 2, 0, 'Graph call control', 'Create / answer / transfer', 'added'),
        node('bot', 3, 0, 'Registered calling bot', 'App consent + callbacks', 'added'),
        node('human', 0, 1, 'Human destination', 'Tenant / PSTN scope applies', 'external'),
        node('media', 1, 1, 'Windows / .NET', 'Azure app-hosted media', 'added'),
        node('app', 2, 1, 'Python AI runtime', 'Retained via custom bridge'),
        node('state', 3, 1, 'Definitions + state', 'YAML / tools / Redis / Cosmos'),
      ],
      edges: [
        edge('pstn', 'pstn', 'teams', 'control', 'M244 116 H284', 'PSTN call', 264, 63, true),
        edge('carrierAudio', 'pstn', 'teams', 'media', 'M244 147 H284', 'Carrier media', 264, 193, true),
        edge('graph', 'teams', 'graph', 'control', 'M504 122 H544', 'Call control', 524, 63, true),
        edge('events', 'graph', 'bot', 'control', 'M764 122 H804', 'HTTPS only', 784, 63, true),
        edge('affinity', 'bot', 'media', 'control', 'M914 170 V240 H454 V410', 'Call identity + pinned media instance', 694, 232),
        edge('custom', 'app', 'bot', 'control', 'M654 410 V335 H974 V170', 'Custom control bridge', 824, 327, true),
        edge('media', 'teams', 'media', 'media', 'M394 170 V410', 'Real-time media SDK', 258, 285, true),
        edge('bridge', 'media', 'app', 'media', 'M504 455 H544', 'Custom duplex bridge', 524, 525, true),
        edge('state', 'app', 'state', 'context', 'M764 455 H804', 'Policy / state', 784, 525, true),
        edge('human', 'teams', 'human', 'control', 'M334 170 V365 H134 V410', 'Supported human leg', 224, 357),
      ],
    },
    sip: {
      title: 'Proposed SIP gateway: vendor call control and duplex media',
      note: 'PROPOSED | Select and validate a vendor topology | No generic Teams media WebSocket',
      nodes: [
        node('carrier', 0, 0, 'Carrier / PSTN', 'Contracted number / route', 'external'),
        node('sbc', 1, 0, 'Certified SBC', 'Customer or carrier operated', 'added'),
        node('teams', 2, 0, 'Teams Direct Routing', 'Voice routing / identities', 'added'),
        node('human', 3, 0, 'Teams human / app', 'Validated destination', 'external'),
        node('gateway', 0, 1, 'SIP / CC gateway', 'B2BUA + media ownership', 'added'),
        node('app', 1, 1, 'New channel bridge', 'Vendor-specific contract', 'added'),
        node('engine', 2, 1, 'Python AI runtime', 'Retained native engine'),
        node('state', 3, 1, 'Definitions + state', 'YAML / tools / Redis / Cosmos'),
      ],
      edges: [
        edge('carrier', 'carrier', 'sbc', 'control', 'M244 116 H284', 'SIP / TLS', 264, 63, true),
        edge('carrierAudio', 'carrier', 'sbc', 'media', 'M244 147 H284', 'RTP / SRTP', 264, 193, true),
        edge('routing', 'sbc', 'teams', 'control', 'M504 116 H544', 'SIP / TLS', 524, 63, true),
        edge('routingAudio', 'sbc', 'teams', 'media', 'M504 147 H544', 'SRTP', 524, 193, true),
        edge('human', 'teams', 'human', 'control', 'M764 122 H804', 'Human call leg', 784, 63),
        edge('gateway', 'sbc', 'gateway', 'control', 'M334 170 V235 H94 V410', 'Gateway signaling: SIP / TLS', 214, 227, true),
        edge('gatewayAudio', 'sbc', 'gateway', 'media', 'M394 170 V300 H154 V410', 'Gateway anchors RTP / SRTP', 274, 292, true),
        edge('transfer', 'gateway', 'teams', 'control', 'M214 410 V370 H654 V170', 'Transfer: confirm REFER / NOTIFY direction', 434, 362),
        edge('bridgeControl', 'gateway', 'app', 'control', 'M244 432 H284', 'Vendor API', 264, 397, true),
        edge('bridge', 'gateway', 'app', 'media', 'M244 473 H284', 'Custom duplex I/O', 264, 525, true),
        edge('engine', 'app', 'engine', 'media', 'M504 455 H544', 'Engine I/O', 524, 525, true),
        edge('state', 'engine', 'state', 'context', 'M764 455 H804', 'Policy / state', 784, 525, true),
      ],
    },
    managed: {
      title: 'Managed Teams agents: the conversational runtime moves',
      note: 'PRODUCT PREVIEW | Not a custom PCM bridge | Microsoft internal stack is not shown',
      nodes: [
        node('caller', 0, 0, 'PSTN / Teams caller', 'Configured connectivity', 'external'),
        node('teams', 1, 0, 'Teams RA + number', 'Native voice-app routing', 'added'),
        node('entry', 2, 0, 'Enabled product', 'Teams Agent / Copilot channel', 'added'),
        node('human', 3, 0, 'Human destination', 'Product-supported targets', 'external'),
        node('old', 0, 1, 'Accelerator runtime', 'Not in this conversation path', 'replaced'),
        node('runtime', 1, 1, 'Managed voice agent', 'Product-hosted conversation', 'added'),
        node('knowledge', 2, 1, 'Product knowledge', 'Migrate approved behavior', 'added'),
        node('tools', 3, 1, 'Allowed tools', 'Supported connectors only', 'added'),
      ],
      edges: [
        edge('pstn', 'caller', 'teams', 'control', 'M244 116 H284', 'Incoming call', 264, 63),
        edge('callerAudio', 'caller', 'teams', 'media', 'M244 147 H284', 'Caller audio', 264, 193, true),
        edge('route', 'teams', 'entry', 'control', 'M504 116 H544', 'Native routing', 524, 63),
        edge('productAudio', 'teams', 'entry', 'media', 'M504 147 H544', 'Service audio', 524, 193, true),
        edge('human', 'entry', 'human', 'control', 'M764 122 H804', 'Human call leg', 784, 63),
        edge('channel', 'entry', 'runtime', 'media', 'M654 170 V265 H394 V410', 'Managed audio: no custom PCM endpoint', 524, 257, true),
        edge('handoff', 'runtime', 'human', 'control', 'M454 410 V345 H914 V170', 'Product transfer: observe the outcome', 684, 337),
        edge('knowledge', 'runtime', 'knowledge', 'context', 'M504 455 H544', 'Knowledge', 524, 525, true),
        edge('tools', 'knowledge', 'tools', 'context', 'M764 455 H804', 'Business context', 784, 525, true),
      ],
    },
  };

  function svgElement(tag, attributes, text) {
    const element = document.createElementNS(NS, tag);
    Object.entries(attributes).forEach(([key, value]) => element.setAttribute(key, value));
    if (text !== undefined) element.textContent = text;
    return element;
  }

  function renderDiagram(host, id, diagram, caption) {
    const svg = svgElement('svg', {
      viewBox: '0 0 1048 578',
      role: 'img',
      'aria-labelledby': `${id}-diagram-title ${id}-diagram-description`,
    });
    svg.append(
      svgElement('title', { id: `${id}-diagram-title` }, diagram.title),
      svgElement('desc', { id: `${id}-diagram-description` }, `${caption} Full text and flow steps follow this figure. Solid blue paths are control, dashed teal paths are audio, dotted purple paths are context.`),
    );
    const defs = svgElement('defs', {});
    ['control', 'media', 'context'].forEach(kind => {
      const marker = svgElement('marker', {
        id: `${id}-${kind}-arrow`, viewBox: '0 0 10 10',
        refX: 9, refY: 5, markerWidth: 5, markerHeight: 5,
        orient: 'auto-start-reverse', class: kind,
      });
      marker.append(svgElement('path', { d: 'M0 0 L10 5 L0 10 Z', fill: 'currentColor' }));
      defs.append(marker);
    });
    svg.append(defs);

    diagram.edges.forEach(item => {
      const group = svgElement('g', { class: `flow-edge ${item.kind}`, 'data-edge': item.id });
      const attributes = {
        d: item.path, class: 'flow-wire',
        'marker-end': `url(#${id}-${item.kind}-arrow)`,
      };
      if (item.duplex) attributes['marker-start'] = `url(#${id}-${item.kind}-arrow)`;
      group.append(svgElement('path', attributes));
      group.append(svgElement('text', { x: item.x, y: item.y, 'text-anchor': 'middle' }, item.label));
      const directions = item.duplex ? ['0;1', '1;0'] : ['0;1'];
      directions.forEach(points => {
        const packet = svgElement('circle', { r: 4, class: 'flow-packet', 'aria-hidden': 'true' });
        packet.append(svgElement('animateMotion', {
          path: item.path, dur: '2.4s', repeatCount: 'indefinite',
          keyPoints: points, keyTimes: '0;1', calcMode: 'linear',
        }));
        group.append(packet);
      });
      svg.append(group);
    });

    diagram.nodes.forEach(item => {
      const group = svgElement('g', {
        class: `flow-node ${item.status}`, 'data-node': item.id,
        transform: `translate(${item.x} ${item.y})`,
      });
      group.append(
        svgElement('rect', { width: 220, height: 90, rx: 8 }),
        svgElement('text', { x: 12, y: 20, class: 'node-status' }, item.status.toUpperCase()),
        svgElement('text', { x: 12, y: 45, class: 'node-title' }, item.title),
        svgElement('text', { x: 12, y: 69, class: 'node-detail' }, item.detail),
      );
      svg.append(group);
    });
    svg.append(svgElement('text', { x: 24, y: 560, class: 'diagram-note' }, diagram.note));
    host.setAttribute('tabindex', '0');
    host.setAttribute('role', 'region');
    host.setAttribute('aria-label', `${diagram.title}. Use Left and Right arrows to scroll; text equivalent below.`);
    // WebKit does not consistently scroll a focused overflow region with arrow keys.
    host.addEventListener('keydown', event => {
      if (event.target !== host || event.altKey || event.ctrlKey || event.metaKey) return;
      if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') {
        event.preventDefault();
        host.scrollLeft += event.key === 'ArrowRight' ? 120 : -120;
      }
    });
    host.append(svg);
    svg.pauseAnimations();
    return svg;
  }

  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
  const requested = (new URLSearchParams(location.search).get('flow') || '').split(':');
  const players = [];
  const disclosures = new Map([...document.querySelectorAll('details[data-section]')]
    .map(detail => [detail.dataset.section, detail]));
  const choiceMaps = [
    { id: 'license-map', attribute: 'data-license-panel', picker: '.license-picker',
      status: 'license-selection', defaultId: 'license-tpe', announcement: 'Showing requirements' },
    { id: 'component-map', attribute: 'data-swap-panel', picker: '.component-picker',
      status: 'component-selection', defaultId: 'swap-tpe', announcement: 'Showing component swaps' },
  ].map(config => {
    const element = document.getElementById(config.id);
    return {
      ...config, element,
      panels: new Map([...element.querySelectorAll(`[${config.attribute}]`)]
        .map(panel => [panel.getAttribute(config.attribute), panel])),
      choices: element.querySelectorAll(`${config.picker} a`),
    };
  });

  function selectMap(map, id) {
    map.panels.forEach((panel, key) => { panel.hidden = key !== id; });
    map.choices.forEach(link => {
      if (link.hash === `#${id}`) link.setAttribute('aria-current', 'true');
      else link.removeAttribute('aria-current');
    });
    document.getElementById(map.status).textContent =
      `${map.announcement}: ${document.getElementById(id).textContent}`;
  }

  choiceMaps.forEach(map => {
    const id = location.hash.slice(1);
    selectMap(map, map.panels.has(id) ? id : map.defaultId);
  });

  function revealSection() {
    const target = document.getElementById(location.hash.slice(1));
    if (!target) return;
    let scrollTarget = target;
    choiceMaps.forEach(map => {
      const panel = target.closest(`[${map.attribute}]`);
      if (panel) {
        selectMap(map, panel.getAttribute(map.attribute));
        scrollTarget = map.element;
      }
    });
    const section = disclosures.get(target.id);
    if (section) section.open = true;
    let ancestor = target.closest('details');
    while (ancestor) {
      ancestor.open = true;
      ancestor = ancestor.parentElement.closest('details');
    }
    requestAnimationFrame(() => scrollTarget.scrollIntoView({ block: 'start', behavior: 'instant' }));
  }

  disclosures.forEach((detail, id) => {
    detail.querySelector(':scope > summary').addEventListener('click', () => {
      if (!detail.open) {
        const url = new URL(location.href);
        url.hash = id;
        history.replaceState(null, '', url);
      }
    });
  });
  window.addEventListener('hashchange', revealSection);
  document.addEventListener('click', event => {
    const link = event.target.closest('a[href^="#"]');
    if (link && link.hash === location.hash && !event.defaultPrevented
        && event.button === 0 && !event.metaKey && !event.ctrlKey && !event.shiftKey && !event.altKey) {
      revealSection();
    }
  });

  document.querySelectorAll('.flow-player').forEach(figure => {
    const id = figure.dataset.architecture;
    const diagram = diagrams[id];
    const scripts = new Map([...figure.querySelectorAll('[data-flow]')]
      .map(list => [list.dataset.flow, [...list.children]]));
    const svg = renderDiagram(figure.querySelector('.diagram-host'), id, diagram,
      figure.querySelector('figcaption').textContent);
    const controls = document.createElement('div');
    controls.className = 'flow-controls';
    const label = document.createElement('label');
    label.htmlFor = `${id}-flow`;
    label.textContent = 'Walk through';
    const select = document.createElement('select');
    select.id = `${id}-flow`;
    select.name = `${id}-flow`;
    for (const [value, text] of [
      ['inbound', 'Inbound call'],
      ['outbound', id === 'managed' ? 'Outbound: capability boundary' : 'Outbound call'],
      ['handoff', 'Human handoff'],
    ]) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = text;
      select.append(option);
    }
    function button(text, className) {
      const element = document.createElement('button');
      element.type = 'button';
      element.textContent = text;
      if (className) element.className = className;
      return element;
    }
    const play = button('Play flow', 'play-control');
    const previous = button('Previous step');
    const next = button('Next step');
    const note = document.createElement('p');
    note.className = 'motion-note';
    controls.append(label, select, play, previous, next, note);
    const readout = document.createElement('div');
    readout.className = 'flow-readout';
    readout.setAttribute('role', 'status');
    readout.setAttribute('aria-live', 'polite');
    readout.setAttribute('aria-atomic', 'true');
    const count = document.createElement('span');
    count.className = 'flow-count';
    const description = document.createElement('p');
    description.className = 'flow-description';
    readout.append(count, description);
    figure.prepend(controls, readout);

    let index = 0;
    let timer = null;
    if (requested[0] === id && scripts.has(requested[1])) {
      select.value = requested[1];
      const requestedIndex = Number(requested[2]);
      if (Number.isInteger(requestedIndex) && requestedIndex >= 0
          && requestedIndex < scripts.get(select.value).length) index = requestedIndex;
      figure.closest('.architecture-detail').open = true;
    }

    function remember() {
      const url = new URL(location.href);
      url.searchParams.set('flow', `${id}:${select.value}:${index}`);
      url.hash = figure.closest('.architecture-detail').dataset.section;
      history.replaceState(null, '', url);
    }

    function showStep() {
      const steps = scripts.get(select.value);
      const activePaths = new Set(steps[index].dataset.paths.split(/\s+/).filter(Boolean));
      const activeNodes = new Set(diagram.edges.filter(item => activePaths.has(item.id))
        .flatMap(item => [item.from, item.to]));
      svg.querySelectorAll('[data-edge]').forEach(item => {
        item.classList.toggle('is-active', activePaths.has(item.dataset.edge));
      });
      svg.querySelectorAll('[data-node]').forEach(item => {
        item.classList.toggle('is-active', activeNodes.has(item.dataset.node));
      });
      for (const list of scripts.values()) {
        list.forEach(step => step.classList.toggle('is-current', step === steps[index]));
      }
      count.textContent = `${index + 1} / ${steps.length}`;
      description.textContent = steps[index].textContent;
      previous.disabled = index === 0;
      next.disabled = index === steps.length - 1;
      if (!timer) play.textContent = index === steps.length - 1 ? 'Replay flow' : 'Play flow';
    }

    function pause() {
      window.clearInterval(timer);
      timer = null;
      figure.classList.remove('is-playing');
      svg.pauseAnimations();
      play.setAttribute('aria-pressed', 'false');
      showStep();
    }

    function motionPreference() {
      pause();
      play.disabled = reducedMotion.matches;
      note.textContent = reducedMotion.matches
        ? 'Reduced motion: use Previous step and Next step. No automatic animation.'
        : 'Starts paused. One step every 4 seconds; arrows show direction, not speed. Focus the diagram and use Left/Right to scroll on small screens.';
    }

    play.addEventListener('click', () => {
      if (timer) {
        pause();
        return;
      }
      players.forEach(player => player.pause());
      if (index === scripts.get(select.value).length - 1) index = 0;
      showStep();
      remember();
      figure.classList.add('is-playing');
      svg.unpauseAnimations();
      play.textContent = 'Pause flow';
      play.setAttribute('aria-pressed', 'true');
      timer = window.setInterval(() => {
        if (index < scripts.get(select.value).length - 1) {
          index += 1;
          showStep();
        } else {
          pause();
        }
      }, 4000);
    });
    select.addEventListener('change', () => {
      index = 0;
      pause();
      showStep();
      remember();
    });
    previous.addEventListener('click', () => {
      pause();
      index = Math.max(0, index - 1);
      showStep();
      remember();
    });
    next.addEventListener('click', () => {
      pause();
      index = Math.min(scripts.get(select.value).length - 1, index + 1);
      showStep();
      remember();
    });
    reducedMotion.addEventListener('change', motionPreference);
    figure.closest('.architecture-detail').addEventListener('toggle', event => {
      if (!event.currentTarget.open) pause();
    });
    motionPreference();
    players.push({ figure, pause });
  });

  document.addEventListener('visibilitychange', () => {
    if (document.hidden) players.forEach(player => player.pause());
  });
  const observer = new IntersectionObserver(entries => {
    entries.filter(entry => !entry.isIntersecting).forEach(entry => {
      players.find(player => player.figure === entry.target).pause();
    });
  });
  players.forEach(player => observer.observe(player.figure));
  revealSection();
})();
