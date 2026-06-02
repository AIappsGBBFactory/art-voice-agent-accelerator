/* ============================================================
   Azure-Style Architecture Diagrams
   Renders inline SVG diagrams into containers with
   data-diagram="<name>" attribute.
   ============================================================ */

/* ---- shared SVG snippets ---- */
const ICONS = {
  phone:   '<path class="icon-glyph" d="M22 22c0-2 1.5-3 3-3h3c2 0 3 1 3 3l-1 4-3 1c2 3 5 6 9 8l1-2 4-1c2 0 3 1 3 3v3c0 2-1 3-3 3-13 0-22-9-22-22 0-2 1-3 3-3z"/>',
  browser: '<rect x="18" y="20" width="24" height="18" rx="2" fill="none" stroke="#fff" stroke-width="1.5"/><line x1="18" y1="25" x2="42" y2="25" stroke="#fff" stroke-width="1.5"/><circle cx="21" cy="22.5" r="0.7" fill="#fff"/><circle cx="23.5" cy="22.5" r="0.7" fill="#fff"/>',
  acs:     '<path class="icon-glyph" d="M20 20h18c1.5 0 2.5 1 2.5 2.5v10c0 1.5-1 2.5-2.5 2.5H29l-5 4v-4h-4c-1.5 0-2.5-1-2.5-2.5v-10c0-1.5 1-2.5 2.5-2.5z"/><circle cx="25" cy="27" r="1.3" fill="var(--d-telephony)"/><circle cx="29" cy="27" r="1.3" fill="var(--d-telephony)"/><circle cx="33" cy="27" r="1.3" fill="var(--d-telephony)"/>',
  apim:    '<path class="icon-glyph" d="M30 18l10 6v12l-10 6-10-6v-12z" fill="none" stroke="#fff" stroke-width="1.6"/><circle cx="30" cy="30" r="3.5" fill="#fff"/>',
  gateway: '<path class="icon-glyph" d="M20 35l10-15 10 15zM30 20v15" fill="none" stroke="#fff" stroke-width="1.8" stroke-linejoin="round"/><circle cx="30" cy="38" r="2" fill="#fff"/>',
  container:'<rect x="19" y="22" width="22" height="6" rx="1" fill="#fff"/><rect x="19" y="30" width="22" height="6" rx="1" fill="#fff" opacity=".75"/><rect x="19" y="38" width="22" height="4" rx="1" fill="#fff" opacity=".5"/>',
  fastapi: '<path class="icon-glyph" d="M30 18l11 6v12l-11 6-11-6V24z" fill="none" stroke="#fff" stroke-width="1.6"/><path class="icon-glyph" d="M28 24l-3 6h4l-2 6 6-8h-4l2-4z"/>',
  registry:'<rect x="20" y="20" width="20" height="20" rx="2" fill="none" stroke="#fff" stroke-width="1.6"/><line x1="20" y1="26" x2="40" y2="26" stroke="#fff" stroke-width="1"/><line x1="20" y1="32" x2="40" y2="32" stroke="#fff" stroke-width="1"/><circle cx="36" cy="23" r="1.2" fill="#fff"/><circle cx="36" cy="29" r="1.2" fill="#fff"/><circle cx="36" cy="35" r="1.2" fill="#fff"/>',
  brain:   '<path class="icon-glyph" d="M22 26c0-3 2-5 5-5 1-2 3-3 5-3s4 1 5 3c3 0 5 2 5 5 0 1-.3 2-.7 3 1 1 1.7 2 1.7 4 0 3-2 5-5 5h-1c-1 1-2 2-4 2-1 0-3 0-4-1-1 1-3 1-4 1-2 0-3-1-4-2h-1c-3 0-5-2-5-5 0-2 .7-3 1.7-4-.4-1-.7-2-.7-3z" fill="#fff"/><circle cx="30" cy="30" r="2" fill="var(--d-ai)"/>',
  mic:     '<rect x="27" y="20" width="6" height="12" rx="3" fill="#fff"/><path d="M23 30v1c0 4 3 7 7 7s7-3 7-7v-1M30 38v4M26 42h8" fill="none" stroke="#fff" stroke-width="1.5" stroke-linecap="round"/>',
  voicelive:'<path d="M19 30c1-3 3-5 6-5s5 2 5 5M30 25c0-3 2-5 5-5s5 2 6 5M30 35c0 3 2 5 5 5s5-2 6-5M19 30c1 3 3 5 6 5s5-2 5-5" fill="none" stroke="#fff" stroke-width="1.6" stroke-linecap="round"/><circle cx="30" cy="30" r="2.5" fill="#fff"/>',
  redis:   '<path class="icon-glyph" d="M28 19l-6 11h5l-2 11 9-13h-6l4-9z"/>',
  cosmos:  '<ellipse cx="30" cy="22" rx="10" ry="3" fill="none" stroke="#fff" stroke-width="1.5"/><path d="M20 22v16c0 1.7 4.5 3 10 3s10-1.3 10-3V22" fill="none" stroke="#fff" stroke-width="1.5"/><line x1="20" y1="30" x2="40" y2="30" stroke="#fff" stroke-width="1" opacity=".6"/>',
  config:  '<circle cx="30" cy="30" r="9" fill="none" stroke="#fff" stroke-width="1.6"/><path d="M30 22v4M30 34v4M22 30h4M34 30h4M24 24l3 3M33 33l3 3M36 24l-3 3M27 33l-3 3" stroke="#fff" stroke-width="1.4" stroke-linecap="round"/><circle cx="30" cy="30" r="2.5" fill="#fff"/>',
  insights:'<path d="M19 38l5-8 5 4 5-12 6 16" fill="none" stroke="#fff" stroke-width="1.8" stroke-linejoin="round" stroke-linecap="round"/>',
  globe:   '<circle cx="30" cy="30" r="10" fill="none" stroke="#fff" stroke-width="1.5"/><ellipse cx="30" cy="30" rx="4" ry="10" fill="none" stroke="#fff" stroke-width="1.2"/><line x1="20" y1="30" x2="40" y2="30" stroke="#fff" stroke-width="1.2"/>',
  sbc:     '<rect x="19" y="22" width="22" height="14" rx="2" fill="none" stroke="#fff" stroke-width="1.6"/><circle cx="24" cy="32" r="1.2" fill="#fff"/><circle cx="28" cy="32" r="1.2" fill="#fff"/><circle cx="32" cy="32" r="1.2" fill="#fff"/><circle cx="36" cy="32" r="1.2" fill="#fff"/><path d="M22 26h16" stroke="#fff" stroke-width="1"/>',
  vnet:    '<path d="M20 25l10-5 10 5v10l-10 5-10-5z" fill="none" stroke="#fff" stroke-width="1.6"/><circle cx="30" cy="30" r="2" fill="#fff"/><circle cx="22" cy="35" r="1.5" fill="#fff"/><circle cx="38" cy="35" r="1.5" fill="#fff"/>',
  shield:  '<path d="M30 20l8 3v8c0 6-4 9-8 11-4-2-8-5-8-11v-8z" fill="none" stroke="#fff" stroke-width="1.6"/><path d="M26 30l3 3 5-6" fill="none" stroke="#fff" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>',
  key:     '<circle cx="25" cy="30" r="5" fill="none" stroke="#fff" stroke-width="1.6"/><line x1="30" y1="30" x2="42" y2="30" stroke="#fff" stroke-width="1.6"/><line x1="38" y1="30" x2="38" y2="34" stroke="#fff" stroke-width="1.6"/><line x1="42" y1="30" x2="42" y2="35" stroke="#fff" stroke-width="1.6"/>'
};

/* arrow marker reused across all diagrams */
const DEFS = `
<defs>
  <marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0 0L10 5L0 10z" fill="var(--d-arrow)"/>
  </marker>
  <marker id="arrow-bi" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
    <path d="M0 0L10 5L0 10z" fill="var(--d-arrow)"/>
  </marker>
  <filter id="tile-shadow" x="-10%" y="-10%" width="120%" height="130%">
    <feDropShadow dx="0" dy="2" stdDeviation="2" flood-opacity="0.08"/>
  </filter>
</defs>`;

/* tile factory */
function tile(x, y, category, name, desc, icon) {
  return `<g transform="translate(${x},${y})" filter="url(#tile-shadow)">
    <rect class="tile" width="200" height="64" rx="6"/>
    <rect class="accent-${category}" width="3" height="64" rx="1.5"/>
    <rect class="icon-bg bg-${category}" x="10" y="12" width="40" height="40" rx="5"/>
    ${ICONS[icon] || ''}
    <text class="tile-name" x="58" y="30">${name}</text>
    <text class="tile-desc" x="58" y="48">${desc}</text>
  </g>`;
}
function zoneHeader(cx, y, text) {
  return `<text class="zone-title" x="${cx}" y="${y}" text-anchor="middle">${text}</text>`;
}
function flowArrow(x1, y1, x2, y2, label, opts = {}) {
  const dashed = opts.dashed ? ' flow-arrow-dashed' : '';
  const labelY = opts.labelY || (y1 - 6);
  const labelX = opts.labelX || ((x1 + x2) / 2);
  const path = opts.curve
    ? `M${x1} ${y1} C${x1 + 30} ${y1}, ${x2 - 30} ${y2}, ${x2} ${y2}`
    : `M${x1} ${y1} L${x2} ${y2}`;
  return `
    <path class="flow-arrow${dashed}" d="${path}" marker-end="url(#arrow)"/>
    ${label ? `<text class="flow-label" x="${labelX}" y="${labelY}" text-anchor="middle">${label}</text>` : ''}
  `;
}

/* ============================================================
   DIAGRAM 1 — System Overview (two ingress paths → orchestrator)
   ============================================================ */
const SYSTEM_OVERVIEW = () => {
  // Zone layout: 5 zones, 220 wide, 50px gaps for arrow labels
  const ZW = 220;
  const ZGAP = 50;
  const Z = [20, 20 + ZW + ZGAP, 20 + 2*(ZW + ZGAP), 20 + 3*(ZW + ZGAP), 20 + 4*(ZW + ZGAP)];
  // Z = [20, 290, 560, 830, 1100], rightmost ends at 1320
  const TX = i => Z[i] + 10;
  const TY = [108, 195, 282];   // 3 rows, ~87px stride (64 tile + 23 gap)
  const VBW = Z[4] + ZW + 20;   // 1340

  // Zone band (taller: 290px to comfortably contain 3 rows + 14px margin)
  const zoneBand = (i, label) => `
    <rect x="${Z[i]}" y="78" width="${ZW}" height="290" rx="6" fill="var(--d-zone-bg)" stroke="var(--d-tile-border)" stroke-opacity="0.5"/>
    <text class="zone-title" x="${Z[i] + ZW/2}" y="94" text-anchor="middle">${label}</text>`;

  // Pill label with readable bg
  const arrowLabel = (x, y, text, color) => `
    <rect x="${x - text.length * 3.2 - 4}" y="${y - 9}" width="${text.length * 6.4 + 8}" height="14" rx="7"
          fill="var(--c-bg)" stroke="${color || 'var(--d-arrow)'}" stroke-width="0.8"/>
    <text class="flow-label" x="${x}" y="${y + 1}" text-anchor="middle" style="fill:${color || 'var(--d-arrow)'}">${text}</text>`;

  const arrow = (x1, y, x2, dashed) => `
    <path class="flow-arrow${dashed ? ' flow-arrow-dashed' : ''}" d="M${x1} ${y} L${x2} ${y}" marker-end="url(#arrow)"/>`;

  // Planned tile: dashed orange border + floating PLANNED pill
  const plannedTile = (x, y, category, name, desc, icon) => `
    <g transform="translate(${x},${y})">
      <rect width="200" height="64" rx="6" fill="var(--d-tile-bg)" stroke="var(--d-telephony)" stroke-width="1.4" stroke-dasharray="5 3"/>
      <rect class="accent-${category}" width="3" height="64" rx="1.5" opacity="0.55"/>
      <rect class="icon-bg bg-${category}" x="10" y="12" width="40" height="40" rx="5"/>
      ${ICONS[icon] || ''}
      <text class="tile-name" x="58" y="30">${name}</text>
      <text class="tile-desc" x="58" y="48">${desc}</text>
      <!-- PLANNED pill (overlay, top-right) -->
      <g transform="translate(138, -8)">
        <rect width="64" height="16" rx="8" fill="var(--d-telephony)"/>
        <text x="32" y="11" text-anchor="middle" style="font:700 9px Inter,sans-serif;letter-spacing:.12em;fill:#fff">PLANNED</text>
      </g>
    </g>`;

  // Common Y midlines
  const Y0 = TY[0] + 32;        // 140 — top row arrow midline
  const Y1 = TY[1] + 32;        // 227 — middle row arrow midline
  const Y2 = TY[2] + 32;        // 314 — bottom row arrow midline

  return `
  <svg viewBox="0 0 ${VBW} 500" xmlns="http://www.w3.org/2000/svg" class="az-svg" role="img" aria-label="ART Voice Agent system architecture">
    ${DEFS}

    <!-- Title -->
    <text x="${VBW/2}" y="32" text-anchor="middle" style="font:600 17px Inter,sans-serif;fill:var(--d-text)">System Architecture</text>
    <text x="${VBW/2}" y="54" text-anchor="middle" style="font:400 12px Inter,sans-serif;fill:var(--d-text-3)">Two entry paths · single FastAPI orchestrator · same agents in both modes</text>

    <!-- Zone bands -->
    ${zoneBand(0, 'Channels')}
    ${zoneBand(1, 'Edge & Gateway')}
    ${zoneBand(2, 'Application')}
    ${zoneBand(3, 'AI Services')}
    ${zoneBand(4, 'State & Config')}

    <!-- Container Apps Environment halo around Application zone -->
    <rect x="${Z[2] + 4}" y="158" width="${ZW - 8}" height="206" rx="8"
          fill="none" stroke="var(--d-app)" stroke-width="1" stroke-dasharray="3 3" opacity="0.45"/>
    <text x="${Z[2] + ZW - 10}" y="172" text-anchor="end"
          style="font:600 9px Inter,sans-serif;letter-spacing:.1em;text-transform:uppercase;fill:var(--d-app);opacity:0.75">Container Apps Env</text>

    <!-- Zone 0: Channels (2 entry paths) -->
    ${tile(TX(0), TY[0], 'channel', 'Phone (PSTN)', 'Inbound SIP calls', 'phone')}
    ${tile(TX(0), TY[1], 'channel', 'Web / Mobile', 'SDK · click-to-call', 'browser')}

    <!-- Zone 1: Edge — ACS (telephony) + APIM (planned, in front of orchestrator) -->
    ${tile(TX(1), TY[0], 'telephony', 'Azure Communication', 'PSTN · audio streaming', 'acs')}
    ${plannedTile(TX(1), TY[1], 'network', 'API Management', 'AI gateway · throttling', 'apim')}

    <!-- Zone 2: Application -->
    ${tile(TX(2), TY[1], 'app', 'FastAPI Orchestrator', 'WebSocket · async I/O', 'fastapi')}
    ${tile(TX(2), TY[2], 'app', 'Agent & Tool Registry', 'YAML agents · @register_tool', 'registry')}

    <!-- Zone 3: AI Services -->
    ${tile(TX(3), TY[0], 'ai', 'Azure OpenAI', 'GPT-4o · function calling', 'brain')}
    ${tile(TX(3), TY[1], 'ai', 'Azure AI Speech', 'STT · 400+ TTS voices', 'mic')}
    ${tile(TX(3), TY[2], 'ai', 'VoiceLive (Realtime)', 'Managed audio pipeline', 'voicelive')}

    <!-- Zone 4: State -->
    ${tile(TX(4), TY[0], 'data', 'Azure Cache for Redis', 'Session state · sub-ms', 'redis')}
    ${tile(TX(4), TY[1], 'data', 'Azure Cosmos DB', 'Transcripts · audit', 'cosmos')}
    ${tile(TX(4), TY[2], 'data', 'App Configuration', 'Feature flags · dynamic', 'config')}

    <!-- ===== Ingress arrows (two paths converging on orchestrator) ===== -->

    <!-- Path A — Telephony: Phone → ACS → FastAPI (top row, then curve down) -->
    ${arrow(Z[0] + ZW + 4, Y0, Z[1] - 8)}
    ${arrowLabel(Z[0] + ZW + ZGAP/2, Y0 - 4, 'SIP audio')}
    <path class="flow-arrow" d="M${Z[1] + ZW + 4} ${Y0}
                                C${Z[1] + ZW + 30} ${Y0},
                                 ${Z[2] - 30} ${Y1},
                                 ${Z[2] - 8} ${Y1}"
          marker-end="url(#arrow)"/>

    <!-- Path B — Web/Mobile: today direct, planned through APIM -->
    <!-- (a) Today: Web/Mobile → FastAPI direct (solid bypass curve UNDER apim) -->
    <path class="flow-arrow" d="M${Z[0] + ZW + 4} ${Y1 + 6}
                                C${Z[1] - 10} ${Y1 + 50},
                                 ${Z[1] + ZW + 10} ${Y1 + 50},
                                 ${Z[2] - 8} ${Y1 + 4}"
          marker-end="url(#arrow)"/>
    ${arrowLabel((Z[0] + ZW + Z[2]) / 2, Y1 + 58, 'today: direct HTTPS / WebSocket')}

    <!-- (b) Planned: Web/Mobile → APIM → FastAPI (dashed straight line through APIM) -->
    ${arrow(Z[0] + ZW + 4, Y1 - 8, Z[1] - 8, true)}
    ${arrow(Z[1] + ZW + 4, Y1 - 8, Z[2] - 8, true)}

    <!-- ===== Orchestrator → AI Services (3-arrow fan) ===== -->
    <path class="flow-arrow" d="M${Z[2] + ZW + 4} ${Y1}
                                C${Z[2] + ZW + 25} ${Y1},
                                 ${Z[3] - 25} ${Y0},
                                 ${Z[3] - 8} ${Y0}"
          marker-end="url(#arrow)"/>
    ${arrow(Z[2] + ZW + 4, Y1, Z[3] - 8)}
    ${arrowLabel(Z[2] + ZW + ZGAP/2, Y1 - 4, 'inference')}
    <path class="flow-arrow" d="M${Z[2] + ZW + 4} ${Y1}
                                C${Z[2] + ZW + 25} ${Y1},
                                 ${Z[3] - 25} ${Y2},
                                 ${Z[3] - 8} ${Y2}"
          marker-end="url(#arrow)"/>

    <!-- ===== AI Services / Orchestrator → State ===== -->
    ${arrow(Z[3] + ZW + 4, Y0, Z[4] - 8)}
    ${arrowLabel(Z[3] + ZW + ZGAP/2, Y0 - 4, 'cache R/W')}

    <!-- Session ctx return (dashed, State → Orchestrator) -->
    <path class="flow-arrow flow-arrow-dashed"
          d="M${Z[4]} ${Y1}
             C${Z[4] - 70} ${Y1 + 56},
              ${Z[2] + ZW + 70} ${Y2 + 30},
              ${Z[2] + ZW + 4} ${Y2}"
          marker-end="url(#arrow)"/>
    ${arrowLabel((Z[2] + ZW + Z[4]) / 2, Y2 + 56, 'session ctx', 'var(--d-data)')}

    <!-- ===== Footer band: Cross-cutting ===== -->
    <rect x="20" y="392" width="${VBW - 40}" height="92" rx="6" fill="var(--d-zone-bg)" stroke="var(--d-tile-border)" stroke-dasharray="3 3"/>
    <text class="zone-title" x="38" y="414" text-anchor="start">Cross-cutting</text>

    ${tile(180, 408, 'observ', 'Application Insights', 'Traces · metrics · logs', 'insights')}
    ${tile(450, 408, 'observ', 'Log Analytics', 'KQL queries · alerts', 'insights')}
    ${tile(720, 408, 'network', 'Private DNS + VNet', 'Hub-spoke topology', 'vnet')}
    ${tile(990, 408, 'network', 'Key Vault', 'Managed identity · secrets', 'key')}
  </svg>`;
};

/* ============================================================
   DIAGRAM 2 — SpeechCascade Audio Pipeline
   ============================================================ */
const CASCADE_PIPELINE = () => {
  // Reusable pill label (matches arrowLabel pattern from SYSTEM_OVERVIEW)
  const lbl = (x, y, text, color) => `
    <rect x="${x - text.length * 3.2 - 5}" y="${y - 9}" width="${text.length * 6.4 + 10}" height="14" rx="7"
          fill="var(--c-bg)" stroke="${color || 'var(--d-arrow)'}" stroke-width="0.8"/>
    <text class="flow-label" x="${x}" y="${y + 1}" text-anchor="middle" style="fill:${color || 'var(--d-arrow)'}">${text}</text>`;

  return `
<svg viewBox="0 0 1240 540" xmlns="http://www.w3.org/2000/svg" class="az-svg" role="img" aria-label="SpeechCascade audio pipeline">
  ${DEFS}

  <text x="620" y="32" text-anchor="middle" style="font:600 17px Inter,sans-serif;fill:var(--d-text)">SpeechCascade — Component-Level Control</text>
  <text x="620" y="54" text-anchor="middle" style="font:400 12px Inter,sans-serif;fill:var(--d-text-3)">Audio flows through three independent Azure services. Swap any component.</text>

  <!-- ============== Ingress + central orchestrator ============== -->
  ${tile(40, 180, 'channel', 'Caller', 'PSTN · μ-law 8 kHz', 'phone')}
  ${tile(280, 180, 'telephony', 'Azure Communication', 'Media streaming bridge', 'acs')}

  <!-- Orchestrator (central hub) -->
  <g transform="translate(560, 130)" filter="url(#tile-shadow)">
    <rect class="tile" width="220" height="164" rx="6"/>
    <rect class="accent-app" width="3" height="164" rx="1.5"/>
    <rect class="icon-bg bg-app" x="10" y="12" width="40" height="40" rx="5"/>
    ${ICONS.fastapi}
    <text class="tile-name" x="58" y="30">Cascade Orchestrator</text>
    <text class="tile-desc" x="58" y="48">FastAPI · async I/O</text>
    <line x1="10" y1="68" x2="210" y2="68" stroke="var(--d-tile-border)"/>
    <text class="tile-desc" x="110" y="86" text-anchor="middle">• Audio queue manager</text>
    <text class="tile-desc" x="110" y="104" text-anchor="middle">• Session router</text>
    <text class="tile-desc" x="110" y="122" text-anchor="middle">• Barge-in / VAD</text>
    <text class="tile-desc" x="110" y="140" text-anchor="middle">• Tool dispatcher</text>
  </g>

  <!-- AI services (stacked, right side) -->
  ${tile(900, 100, 'ai', 'Azure AI Speech — STT', 'Streaming recognition', 'mic')}
  ${tile(900, 188, 'ai', 'Azure OpenAI — LLM', 'GPT-4o · function calling', 'brain')}
  ${tile(900, 276, 'ai', 'Azure AI Speech — TTS', '400+ neural voices', 'voicelive')}

  <!-- State (below orchestrator) -->
  ${tile(440, 330, 'data', 'Redis (MemoManager)', 'Conversation context', 'redis')}
  ${tile(680, 330, 'data', 'Cosmos DB', 'Persisted transcripts', 'cosmos')}

  <!-- Ingress arrows -->
  <path class="flow-arrow" d="M240 212 L280 212" marker-end="url(#arrow)"/>
  ${lbl(260, 207, 'SIP')}
  <path class="flow-arrow" d="M484 212 L560 212" marker-end="url(#arrow)"/>
  ${lbl(522, 200, 'audio')}

  <!-- Orchestrator → AI services (3 numbered fan arrows) -->
  <path class="flow-arrow" d="M784 168 C840 168, 850 132, 896 132" marker-end="url(#arrow)"/>
  <path class="flow-arrow" d="M784 212 L896 220" marker-end="url(#arrow)"/>
  <path class="flow-arrow" d="M784 256 C840 256, 850 308, 896 308" marker-end="url(#arrow)"/>
  ${lbl(840, 116, '① transcribe', 'var(--d-ai)')}
  ${lbl(840, 204, '② reason', 'var(--d-ai)')}
  ${lbl(840, 296, '③ synthesize', 'var(--d-ai)')}

  <!-- Dashed state writes from orchestrator → Redis/Cosmos -->
  <path class="flow-arrow flow-arrow-dashed" d="M620 294 L540 330" marker-end="url(#arrow)"/>
  <path class="flow-arrow flow-arrow-dashed" d="M720 294 L780 330" marker-end="url(#arrow)"/>
  ${lbl(540, 318, 'session ctx')}
  ${lbl(782, 318, 'persist on end')}

  <!-- ============== Legend ============== -->
  <rect x="40" y="430" width="1160" height="80" rx="8" fill="var(--d-zone-bg)" stroke="var(--d-tile-border)" stroke-dasharray="3 3"/>
  <text class="zone-title" x="60" y="452" text-anchor="start">Legend</text>

  <!-- Solid arrow sample -->
  <path class="flow-arrow" d="M60 482 L120 482" marker-end="url(#arrow)"/>
  <text style="font:400 11px Inter,sans-serif;fill:var(--d-text)" x="132" y="485">Solid — synchronous request / response</text>

  <!-- Dashed arrow sample -->
  <path class="flow-arrow flow-arrow-dashed" d="M440 482 L500 482" marker-end="url(#arrow)"/>
  <text style="font:400 11px Inter,sans-serif;fill:var(--d-text)" x="512" y="485">Dashed — async session / persistence writes</text>

  <!-- Numbered turn flow -->
  <text style="font:600 11px Inter,sans-serif;fill:var(--d-text)" x="820" y="485">①→②→③</text>
  <text style="font:400 11px Inter,sans-serif;fill:var(--d-text-3)" x="878" y="485">per-turn flow · audio returns via reverse media path</text>
</svg>`;
};

/* ============================================================
   DIAGRAM 3 — VoiceLive Pipeline
   ============================================================ */
const VOICELIVE_PIPELINE = () => `
<svg viewBox="0 0 1240 400" xmlns="http://www.w3.org/2000/svg" class="az-svg" role="img" aria-label="VoiceLive managed audio pipeline">
  ${DEFS}

  <text x="620" y="32" text-anchor="middle" style="font:600 17px Inter,sans-serif;fill:var(--d-text)">VoiceLive — Managed Audio Pipeline</text>
  <text x="620" y="54" text-anchor="middle" style="font:400 12px Inter,sans-serif;fill:var(--d-text-3)">Single hop · STT + LLM + TTS managed by Azure AI Foundry · ~200 ms end-to-end</text>

  <!-- Caller -->
  ${tile(40, 150, 'channel', 'Caller', 'PSTN · WebRTC', 'phone')}

  <!-- ACS -->
  ${tile(280, 150, 'telephony', 'Azure Communication', 'Media bridge', 'acs')}

  <!-- Orchestrator (renamed to fit) -->
  ${tile(520, 150, 'app', 'VoiceLive Proxy', 'Lightweight session bridge', 'fastapi')}

  <!-- VoiceLive managed pipeline container (3 inner mini-tiles, narrower to fit Redis) -->
  <g transform="translate(760, 100)" filter="url(#tile-shadow)">
    <rect class="tile" width="280" height="172" rx="8" stroke-width="2" stroke="var(--d-ai)"/>
    <rect class="accent-ai" width="4" height="172" rx="2"/>
    <text class="zone-title" x="140" y="22" text-anchor="middle" style="fill:var(--d-ai)">Azure AI Foundry · VoiceLive</text>

    <!-- Inner: STT -->
    <g transform="translate(16,40)">
      <rect class="icon-bg bg-ai" width="32" height="32" rx="4"/>
      <rect x="13" y="6" width="6" height="11" rx="3" fill="#fff"/>
      <path d="M9 16v1c0 4 3 6 7 6s7-2 7-6v-1M16 23v3M12 26h8" fill="none" stroke="#fff" stroke-width="1.3" stroke-linecap="round" transform="translate(0,0)"/>
      <text class="tile-name" x="44" y="14">Speech recognition</text>
      <text class="tile-desc" x="44" y="28">Realtime STT · server-side VAD</text>
    </g>
    <line x1="16" y1="82" x2="264" y2="82" stroke="var(--d-tile-border)" stroke-opacity="0.5"/>

    <!-- Inner: LLM -->
    <g transform="translate(16,88)">
      <rect class="icon-bg bg-ai" width="32" height="32" rx="4"/>
      <path d="M6 14c0-2 1.5-4 4-4 .8-1.5 2-2 3.5-2s2.7.5 3.5 2c2 0 3.5 2 3.5 4 0 1-.3 1.5-.5 2 .8.7 1.2 1.5 1.2 2.5 0 2-1.5 3-3 3h-.6c-.6.7-1.4 1.2-2.6 1.2s-2-.3-2.5-1c-.7.7-1.5 1-2.5 1s-2-.5-2.6-1.2H7c-1.5 0-3-1-3-3 0-1 .4-1.8 1.2-2.5-.2-.5-.5-1-.5-2z" fill="#fff"/>
      <circle cx="16" cy="16" r="2" fill="var(--d-ai)"/>
      <text class="tile-name" x="44" y="14">LLM reasoning</text>
      <text class="tile-desc" x="44" y="28">GPT-4o Realtime · function calling</text>
    </g>
    <line x1="16" y1="130" x2="264" y2="130" stroke="var(--d-tile-border)" stroke-opacity="0.5"/>

    <!-- Inner: TTS -->
    <g transform="translate(16,136)">
      <rect class="icon-bg bg-ai" width="32" height="32" rx="4"/>
      <path d="M5 16c.5-2 2-3 4-3s3 1.2 3 3M12 13c0-2 1.5-3 3-3s3 1.2 4 3M12 19c0 2 1.5 3 3 3s3-1.2 4-3M5 16c.5 2 2 3 4 3s3-1.2 3-3" fill="none" stroke="#fff" stroke-width="1.3" stroke-linecap="round"/>
      <circle cx="16" cy="16" r="2" fill="#fff"/>
      <text class="tile-name" x="44" y="14">HD voice synthesis</text>
      <text class="tile-desc" x="44" y="28">e.g. en-US-Ava:DragonHDLatest</text>
    </g>
  </g>

  <!-- Tools -->
  ${tile(520, 280, 'app', 'Tool Registry', 'Native function calling', 'registry')}

  <!-- State (custom narrow tile at x=1060, width=180 → fits in viewBox 1240) -->
  <g transform="translate(1060, 150)" filter="url(#tile-shadow)">
    <rect class="tile" width="180" height="64" rx="6"/>
    <rect class="accent-data" width="3" height="64" rx="1.5"/>
    <rect class="icon-bg bg-data" x="10" y="12" width="40" height="40" rx="5"/>
    ${ICONS.redis}
    <text class="tile-name" x="58" y="30">Redis / Cosmos</text>
    <text class="tile-desc" x="58" y="48">Session + audit</text>
  </g>

  <!-- Arrows -->
  ${flowArrow(240, 182, 280, 182, 'SIP')}
  ${flowArrow(480, 182, 520, 182, 'audio')}
  ${flowArrow(720, 182, 760, 182, 'WebSocket')}
  ${flowArrow(620, 280, 620, 220, 'tool call', { labelX: 660, labelY: 256 })}
  <!-- Persistence (dashed arrow routed ABOVE the Foundry box from Proxy to Redis) -->
  <path class="flow-arrow flow-arrow-dashed" d="M620 150 C620 80, 1058 80, 1058 150" marker-end="url(#arrow)"/>
  <rect x="780" y="60" width="120" height="14" rx="7" fill="var(--c-bg)" stroke="var(--d-arrow)" stroke-width="0.8"/>
  <text class="flow-label" x="840" y="71" text-anchor="middle">session + audit</text>

  <text x="620" y="362" text-anchor="middle" style="font:400 11px Inter,sans-serif;fill:var(--d-text-3)">Single managed pipeline replaces 3 separate components — fewer hops = lower latency</text>
</svg>`;

/* ============================================================
   DIAGRAM 4 — Production Reference (Hub-Spoke + APIM AI Gateway)
   ============================================================ */
const PRODUCTION_REF = () => {
  const VBW = 1340;
  const VBH = 660;
  const ZW = 220;
  const ZGAP = 40;
  const Z = [20, 280, 540, 800, 1060];
  const TX = i => Z[i] + 10;

  // Zone band geometry
  const ZBY = 110;
  const ZBH = 410;

  // VNet outer-band geometry
  const VNET_Y = 100;
  const VNET_H = 430;
  const HUB_X = 265, HUB_W = 510;       // wraps Z[1] + Z[2]
  const SPOKE_X = 785, SPOKE_W = 510;   // wraps Z[3] + Z[4]

  // Row positions for the two ingress paths
  const Y_TOP = 145;   // Web / App GW
  const Y_BOT = 365;   // Phone / ACS

  // Subtle per-zone band
  const zoneBand = (i, label) => `
    <rect x="${Z[i]}" y="${ZBY}" width="${ZW}" height="${ZBH}" rx="6"
          fill="var(--d-zone-bg)" stroke="var(--d-tile-border)" stroke-opacity="0.5"/>
    <text class="zone-title" x="${Z[i] + ZW/2}" y="${ZBY + 18}" text-anchor="middle">${label}</text>`;

  // Outer VNet boundary band with a floating label pill
  const vnetBand = (x, w, color, label) => {
    const lw = label.length * 6.4 + 16;
    return `
      <rect x="${x}" y="${VNET_Y}" width="${w}" height="${VNET_H}" rx="10"
            fill="none" stroke="${color}" stroke-width="1.4" stroke-dasharray="6 4" opacity="0.85"/>
      <g transform="translate(${x + 14}, ${VNET_Y - 8})">
        <rect width="${lw}" height="16" rx="8" fill="${color}"/>
        <text x="${lw/2}" y="11" text-anchor="middle"
              style="font:700 9px Inter,sans-serif;letter-spacing:.12em;fill:#fff">${label}</text>
      </g>`;
  };

  // NSP badge overlay for PaaS tiles inside a Network Security Perimeter
  const nspBadge = `
    <g transform="translate(160, -7)">
      <rect width="42" height="14" rx="7" fill="var(--d-telephony)"/>
      <text x="21" y="10" text-anchor="middle"
            style="font:700 9px Inter,sans-serif;letter-spacing:.12em;fill:#fff">NSP</text>
    </g>`;
  const nspTile = (x, y, category, name, desc, icon) => `
    <g transform="translate(${x},${y})" filter="url(#tile-shadow)">
      <rect class="tile" width="200" height="64" rx="6"/>
      <rect class="accent-${category}" width="3" height="64" rx="1.5"/>
      <rect class="icon-bg bg-${category}" x="10" y="12" width="40" height="40" rx="5"/>
      ${ICONS[icon] || ''}
      <text class="tile-name" x="58" y="30">${name}</text>
      <text class="tile-desc" x="58" y="48">${desc}</text>
      ${nspBadge}
    </g>`;

  // Featured tall APIM tile (capability list inline)
  const apimTile = (x, y) => `
    <g transform="translate(${x},${y})" filter="url(#tile-shadow)">
      <rect class="tile" width="200" height="220" rx="6"/>
      <rect class="accent-network" width="3" height="220" rx="1.5"/>
      <rect class="icon-bg bg-network" x="10" y="12" width="40" height="40" rx="5"/>
      ${ICONS.apim}
      <text class="tile-name" x="58" y="30">API Management</text>
      <text class="tile-desc" x="58" y="48">AI Gateway · governance</text>
      <line x1="14" y1="68" x2="186" y2="68" stroke="var(--d-tile-border)" stroke-opacity="0.6"/>
      <text x="14" y="86" style="font:600 9px Inter,sans-serif;letter-spacing:.1em;fill:var(--d-text);text-transform:uppercase">Capabilities</text>
      <text class="tile-desc" x="14" y="104">• Prompt Shields (Content Safety)</text>
      <text class="tile-desc" x="14" y="122">• Entra ID / JWT validation</text>
      <text class="tile-desc" x="14" y="140">• Token-based throttling</text>
      <text class="tile-desc" x="14" y="158">• Per-subscription cost mgmt</text>
      <text class="tile-desc" x="14" y="176">• Request / response logging</text>
      <text class="tile-desc" x="14" y="194">• Semantic cache · retries</text>
      <text class="tile-desc" x="14" y="212">• Backend pool / circuit breaker</text>
    </g>`;

  // Pill label for arrows
  const lbl = (x, y, text, color) => `
    <rect x="${x - text.length * 3.2 - 5}" y="${y - 9}" width="${text.length * 6.4 + 10}" height="14" rx="7"
          fill="var(--c-bg)" stroke="${color || 'var(--d-arrow)'}" stroke-width="0.8"/>
    <text class="flow-label" x="${x}" y="${y + 1}" text-anchor="middle" style="fill:${color || 'var(--d-arrow)'}">${text}</text>`;

  return `
  <svg viewBox="0 0 ${VBW} ${VBH}" xmlns="http://www.w3.org/2000/svg" class="az-svg" role="img" aria-label="Production reference architecture">
    ${DEFS}

    <text x="${VBW/2}" y="32" text-anchor="middle" style="font:600 17px Inter,sans-serif;fill:var(--d-text)">Production Reference Architecture</text>
    <text x="${VBW/2}" y="54" text-anchor="middle" style="font:400 12px Inter,sans-serif;fill:var(--d-text-3)">Two ingress paths · APIM AI Gateway · Hub-spoke VNet · ACS in NSP · Private Endpoints for app data plane</text>

    <!-- Outer VNet boundaries -->
    ${vnetBand(HUB_X, HUB_W, 'var(--d-app)', 'HUB VNET')}
    ${vnetBand(SPOKE_X, SPOKE_W, 'var(--d-ai)', 'SPOKE VNET · WORKLOAD')}

    <!-- Per-zone bands -->
    ${zoneBand(0, 'External Clients')}
    ${zoneBand(1, 'Edge')}
    ${zoneBand(2, 'AI Gateway')}
    ${zoneBand(3, 'Compute')}
    ${zoneBand(4, 'Data Plane')}

    <!-- Z[0] External Clients -->
    ${tile(TX(0), Y_TOP, 'channel', 'Web / Mobile', 'Browser · SDK · click-to-call', 'browser')}
    ${tile(TX(0), Y_BOT, 'channel', 'Phone / Genesys / IVR', 'PSTN · SIP trunk', 'phone')}

    <!-- Z[1] Edge -->
    ${tile(TX(1), Y_TOP, 'network', 'Application Gateway', 'WAF v2 · DDoS · TLS · OWASP', 'shield')}
    ${nspTile(TX(1), Y_BOT, 'telephony', 'Azure Communication', 'SIP · SRTP ingress', 'acs')}

    <!-- Z[2] APIM (featured tall tile) -->
    ${apimTile(TX(2), 200)}

    <!-- Z[3] Compute (Container Apps Env, centered) -->
    ${tile(TX(3), 278, 'app', 'Container Apps Env', 'Internal LB · MI · KEDA', 'container')}

    <!-- Z[4] Data Plane (4 PE tiles stacked) -->
    ${tile(TX(4),    135, 'ai', 'Microsoft Foundry', 'GPT-4o · realtime · function calling', 'brain')}
    ${tile(TX(4),    215, 'ai', 'Azure AI Speech', 'STT · TTS (Foundry voice stack)', 'mic')}
    ${tile(TX(4),    295, 'data', 'Azure Cache for Redis', 'Session state · pools', 'redis')}
    ${tile(TX(4),    375, 'data', 'Azure Cosmos DB', 'Transcripts · audit', 'cosmos')}

    <!-- ============ ARROWS ============ -->

    <!-- Web → App Gateway (top row) -->
    <path class="flow-arrow" d="M${Z[0]+ZW+4} ${Y_TOP+32} L${Z[1]-8} ${Y_TOP+32}" marker-end="url(#arrow)"/>
    ${lbl((Z[0]+ZW+Z[1])/2, Y_TOP+28, 'HTTPS')}

    <!-- Phone/Genesys/IVR → ACS (bottom row), crosses NSP boundary -->
    <path class="flow-arrow" d="M${Z[0]+ZW+4} ${Y_BOT+32} L${Z[1]-8} ${Y_BOT+32}" marker-end="url(#arrow)"/>
    ${lbl((Z[0]+ZW+Z[1])/2, Y_BOT+28, 'SIP · SRTP')}

    <!-- App Gateway → APIM (top portion of APIM) -->
    <path class="flow-arrow"
          d="M${Z[1]+ZW+4} ${Y_TOP+32}
             C${Z[1]+ZW+30} ${Y_TOP+32}, ${Z[2]-30} ${260}, ${Z[2]-8} ${260}"
          marker-end="url(#arrow)"/>

    <!-- ACS → APIM (bottom portion of APIM) -->
    <path class="flow-arrow"
          d="M${Z[1]+ZW+4} ${Y_BOT+32}
             C${Z[1]+ZW+30} ${Y_BOT+32}, ${Z[2]-30} ${360}, ${Z[2]-8} ${360}"
          marker-end="url(#arrow)"/>

    <!-- APIM → Container Apps (VNet peering between Hub and Spoke) -->
    <path class="flow-arrow"
          d="M${Z[2]+ZW+4} ${310}
             C${Z[2]+ZW+30} ${310}, ${Z[3]-30} ${278+32}, ${Z[3]-8} ${278+32}"
          marker-end="url(#arrow)"/>
    ${lbl((Z[2]+ZW+Z[3])/2, 296, 'VNet peering', 'var(--d-app)')}

    <!-- Container Apps → Data Plane (4-arrow fan via private endpoints) -->
    ${[135, 215, 295, 375].map(targetY => `
      <path class="flow-arrow"
            d="M${Z[3]+ZW+4} ${278+32}
               C${Z[3]+ZW+20} ${278+32}, ${Z[4]-20} ${targetY+32}, ${Z[4]-8} ${targetY+32}"
            marker-end="url(#arrow)"/>
    `).join('')}
    ${lbl((Z[3]+ZW+Z[4])/2, 260, 'private endpoints')}

    <!-- ============ FOOTER ============ -->
    <rect x="20" y="540" width="${VBW - 40}" height="100" rx="6"
          fill="var(--d-zone-bg)" stroke="var(--d-tile-border)" stroke-dasharray="3 3"/>
    <text class="zone-title" x="38" y="562" text-anchor="start">Cross-cutting</text>

    ${tile(180, 568, 'network', 'Key Vault (PE)', 'Secrets · certs · keys', 'key')}
    ${tile(450, 568, 'network', 'Managed Identity', 'Workload identity · RBAC', 'key')}
    ${tile(720, 568, 'observ', 'App Insights', 'Distributed tracing', 'insights')}
    ${tile(990, 568, 'observ', 'Log Analytics', 'KQL · alerts · workbooks', 'insights')}

    <text x="${VBW/2}" y="650" text-anchor="middle" style="font:italic 11px Inter,sans-serif;fill:var(--d-text-3)">
        NSP badge = ACS in a Network Security Perimeter (public endpoint constrained by NSP policy; private endpoints used for Foundry/Speech app data plane, Redis, and Cosmos)
    </text>
  </svg>`;
};

/* ============================================================
   DIAGRAM 5 — Cross-Cloud (AWS Connect → Azure via SBC)
   ============================================================ */
const CROSS_CLOUD = () => {
  const VBW = 1280;
  const VBH = 410;

  // Pill label helper
  const lbl = (x, y, text, color) => `
    <rect x="${x - text.length * 3.2 - 5}" y="${y - 9}" width="${text.length * 6.4 + 10}" height="14" rx="7"
          fill="var(--c-bg)" stroke="${color || 'var(--d-arrow)'}" stroke-width="0.8"/>
    <text class="flow-label" x="${x}" y="${y + 1}" text-anchor="middle" style="fill:${color || 'var(--d-arrow)'}">${text}</text>`;

  // Cloud zone band
  const cloudZone = (x, y, w, h, label, fill, stroke, textColor) => `
    <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="10" fill="${fill}" stroke="${stroke}" stroke-width="1.4" stroke-dasharray="6 4"/>
    <g transform="translate(${x + 14}, ${y - 8})">
      <rect width="${label.length * 6.8 + 16}" height="16" rx="8" fill="${stroke}"/>
      <text x="${(label.length * 6.8 + 16) / 2}" y="11" text-anchor="middle"
            style="font:700 9px Inter,sans-serif;letter-spacing:.12em;fill:#fff">${label}</text>
    </g>`;

  return `
<svg viewBox="0 0 ${VBW} ${VBH}" xmlns="http://www.w3.org/2000/svg" class="az-svg" role="img" aria-label="Cross-cloud integration: AWS Connect to Azure">
  ${DEFS}

  <text x="${VBW/2}" y="32" text-anchor="middle" style="font:600 17px Inter,sans-serif;fill:var(--d-text)">Cross-Cloud Integration — AWS Connect → Azure</text>
  <text x="${VBW/2}" y="54" text-anchor="middle" style="font:400 12px Inter,sans-serif;fill:var(--d-text-3)">SBC bridges SIP between clouds — only telephony crosses the boundary; AI workload stays in Azure</text>

  <!-- Cloud zones -->
  ${cloudZone(20, 100, 380, 240, 'AWS CLOUD', 'rgba(255,153,0,0.06)', '#cc7000', '#cc7000')}
  ${cloudZone(480, 100, 200, 240, 'BRIDGE', 'rgba(120,120,120,0.06)', '#6b7280', '#6b7280')}
  ${cloudZone(760, 100, 500, 240, 'AZURE CLOUD', 'rgba(0,120,212,0.06)', '#0078D4', '#0078D4')}

  <!-- AWS tiles -->
  ${tile(40, 150, 'telephony', 'Amazon Connect', 'Contact center', 'acs')}
  ${tile(40, 250, 'telephony', 'Chime Voice Connector', 'SIP trunking · DIDs', 'phone')}

  <!-- Bridge tile -->
  ${tile(490, 200, 'network', 'Certified SBC', 'Cross-cloud SIP gateway', 'sbc')}

  <!-- Azure tiles -->
  ${tile(780, 150, 'telephony', 'Azure Communication', 'SIP ingress · media bridge', 'acs')}
  ${tile(780, 250, 'app', 'Voice Agent Backend', 'Container Apps · FastAPI', 'container')}
  ${tile(1050, 200, 'ai', 'AI Services + State', 'OpenAI · Speech · Redis', 'brain')}

  <!-- AWS → SBC (both AWS sources converge on SBC left edge at y=232) -->
  <path class="flow-arrow" d="M244 182 C360 182, 400 232, 486 232" marker-end="url(#arrow)"/>
  <path class="flow-arrow" d="M244 282 C360 282, 400 232, 486 232" marker-end="url(#arrow)"/>
  ${lbl(388, 200, 'SIP', '#cc7000')}

  <!-- SBC → Azure Communication -->
  <path class="flow-arrow" d="M694 232 C724 232, 752 182, 776 182" marker-end="url(#arrow)"/>
  ${lbl(736, 200, 'SIP / SRTP', '#0078D4')}

  <!-- ACS → Voice Agent Backend (internal Azure WebSocket — vertical) -->
  <path class="flow-arrow" d="M880 214 L880 250" marker-end="url(#arrow)"/>
  ${lbl(940, 234, 'WebSocket', 'var(--d-app)')}

  <!-- Voice Agent Backend → AI Services -->
  <path class="flow-arrow" d="M984 282 C1010 282, 1030 232, 1046 232" marker-end="url(#arrow)"/>
  ${lbl(1014, 252, 'private endpoints')}

  <!-- Footer note -->
  <text x="${VBW/2}" y="370" text-anchor="middle" style="font:italic 11px Inter,sans-serif;fill:var(--d-text-3)">No AI traffic crosses the cloud boundary — SBC only carries SIP signalling + RTP media for the call leg</text>
</svg>`;
};

/* ============================================================
   DIAGRAM 6 — Omnichannel Hero (index page)
   Showcase: every channel in → ART Agent core (dual mode + swarm + tools)
            → live agents, persistence, observability
   ============================================================ */
const OMNICHANNEL_HERO = () => {
  const VBW = 1280, VBH = 640;

  // --- Layout ---
  const CH_X = 28;                         // Channels column (200-wide tiles)
  const HUB_X = 326, HUB_W = 600;          // ART Agent hub
  const HUB_Y = 156, HUB_H = 388;
  const HUB_CX = HUB_X + HUB_W / 2;
  const OUT_X = 988;                       // Outputs column

  const CH_YS  = [172, 256, 340, 424];
  const OUT_YS = [196, 308, 420];

  // Hub interior anchors
  const HUB_TITLE_Y = HUB_Y + 30;
  const HUB_MODE_Y  = HUB_Y + 68;
  const HUB_SWARM_Y = HUB_Y + 158;
  const HUB_STRIP_Y = HUB_Y + HUB_H - 80;

  // --- Header value-prop chips ---
  const chipsRow = (() => {
    const chips = [
      { label: '⚡  < 1s end-to-end',       color: 'var(--d-ai)' },
      { label: '🔄  Live agent handoffs',   color: 'var(--d-app)' },
      { label: '🎙  400+ neural voices',    color: 'var(--d-telephony)' },
      { label: '🔌  MCP-ready tools',       color: 'var(--d-data)' },
      { label: '🛡  Enterprise-grade',      color: 'var(--d-network)' },
    ];
    // Approx pixel width per chip (emoji ~16, letter ~7)
    const widths = chips.map(c => Math.round(c.label.length * 7 + 36));
    const total = widths.reduce((a, b) => a + b, 0) + (chips.length - 1) * 10;
    let x = (VBW - total) / 2;
    return chips.map((c, i) => {
      const w = widths[i];
      const out = `
        <g transform="translate(${x}, 96)">
          <rect width="${w}" height="28" rx="14" fill="${c.color}" opacity="0.12"/>
          <rect width="${w}" height="28" rx="14" fill="none" stroke="${c.color}" stroke-width="1" opacity="0.55"/>
          <text x="${w/2}" y="18" text-anchor="middle"
                style="font:600 12px Inter,sans-serif;fill:${c.color}">${c.label}</text>
        </g>`;
      x += w + 10;
      return out;
    }).join('');
  })();

  // --- Dual-mode strip inside hub ---
  const modeStrip = (() => {
    const modes = [
      { x: HUB_X + 24,  label: 'SpeechCascade', latency: '~400 ms', desc: 'STT · LLM · TTS — full component control' },
      { x: HUB_X + 308, label: 'VoiceLive',     latency: '~200 ms', desc: 'Realtime — managed audio · server VAD' },
    ];
    return modes.map(m => `
      <g transform="translate(${m.x}, ${HUB_MODE_Y})">
        <rect width="268" height="50" rx="6" fill="var(--d-tile-bg)" stroke="var(--d-ai)" stroke-width="1"/>
        <rect width="3" height="50" rx="1.5" fill="var(--d-ai)"/>
        <text x="16" y="20" style="font:700 12.5px Inter,sans-serif;fill:var(--d-text)">${m.label}</text>
        <g transform="translate(180, 8)">
          <rect width="76" height="16" rx="8" fill="var(--d-ai)" opacity="0.18"/>
          <text x="38" y="11" text-anchor="middle"
                style="font:600 10px 'JetBrains Mono',monospace;fill:var(--d-ai)">${m.latency}</text>
        </g>
        <text x="16" y="38" style="font:400 11px Inter,sans-serif;fill:var(--d-text-3)">${m.desc}</text>
      </g>`).join('');
  })();

  // --- Agent swarm (concierge in center + 4 specialists) ---
  const swarm = (() => {
    const concW = 160, concH = 64;
    const concX = HUB_CX - concW / 2;
    const concY = HUB_SWARM_Y + 10;
    const concCY = concY + concH / 2;

    const specs = [
      { x: HUB_X + 24,            y: HUB_SWARM_Y - 4,  label: 'Authentication', sub: 'Verify identity',  color: 'var(--d-app)' },
      { x: HUB_X + 24,            y: HUB_SWARM_Y + 48, label: 'Knowledge / RAG',sub: 'Search · cite',    color: 'var(--d-ai)' },
      { x: HUB_X + HUB_W - 124,   y: HUB_SWARM_Y - 4,  label: 'Fraud',           sub: 'Risk signals',    color: 'var(--d-telephony)' },
      { x: HUB_X + HUB_W - 124,   y: HUB_SWARM_Y + 48, label: 'Escalation',      sub: 'Warm transfer',   color: 'var(--d-data)' },
    ];

    // Concierge tile (filled, looks like "active hub")
    const concierge = `
      <g transform="translate(${concX}, ${concY})" filter="url(#tile-shadow)">
        <rect width="${concW}" height="${concH}" rx="8" fill="var(--d-app)"/>
        <text x="${concW/2}" y="24" text-anchor="middle"
              style="font:700 13.5px Inter,sans-serif;fill:#fff">Concierge</text>
        <text x="${concW/2}" y="40" text-anchor="middle"
              style="font:500 10.5px Inter,sans-serif;fill:#fff;opacity:0.88">Greets · routes intent · hands off</text>
        <g opacity="0.65" transform="translate(${concW/2 - 18}, 48)">
          <circle cx="0" cy="6" r="2.4" fill="#fff"/>
          <circle cx="9" cy="6" r="2.4" fill="#fff"/>
          <circle cx="18" cy="6" r="2.4" fill="#fff"/>
          <circle cx="27" cy="6" r="2.4" fill="#fff"/>
          <circle cx="36" cy="6" r="2.4" fill="#fff"/>
        </g>
      </g>`;

    const specTiles = specs.map(s => `
      <g transform="translate(${s.x}, ${s.y})">
        <rect width="100" height="44" rx="6" fill="var(--d-tile-bg)" stroke="${s.color}" stroke-width="1.2"/>
        <rect width="3" height="44" rx="1.5" fill="${s.color}"/>
        <text x="50" y="18" text-anchor="middle"
              style="font:600 11px Inter,sans-serif;fill:var(--d-text)">${s.label}</text>
        <text x="50" y="33" text-anchor="middle"
              style="font:400 10px Inter,sans-serif;fill:var(--d-text-3)">${s.sub}</text>
      </g>`).join('');

    // Handoff arrows (dashed, curved) between concierge and each specialist
    const handoff = (sx, sy, tx, ty) =>
      `<path class="flow-arrow flow-arrow-dashed" opacity="0.7"
             d="M${sx} ${sy} C${(sx + tx) / 2} ${sy}, ${(sx + tx) / 2} ${ty}, ${tx} ${ty}"
             marker-end="url(#arrow)"/>`;

    const concLeft  = concX;
    const concRight = concX + concW;
    const arrows = [
      handoff(concLeft,  concCY - 8, HUB_X + 124,         specs[0].y + 22),
      handoff(concLeft,  concCY + 8, HUB_X + 124,         specs[1].y + 22),
      handoff(concRight, concCY - 8, HUB_X + HUB_W - 124, specs[2].y + 22),
      handoff(concRight, concCY + 8, HUB_X + HUB_W - 124, specs[3].y + 22),
    ].join('');

    return `
      <text x="${HUB_X + 24}" y="${HUB_SWARM_Y - 14}"
            style="font:600 10.5px Inter,sans-serif;fill:var(--d-text-3);text-transform:uppercase;letter-spacing:0.1em">Multi-Agent Orchestration</text>
      ${arrows}
      ${specTiles}
      ${concierge}`;
  })();

  // --- Capability strip (bottom of hub) ---
  const capStrip = (() => {
    const items = [
      { label: 'Tool Registry',  desc: '@register_tool · YAML',  color: 'var(--d-ai)' },
      { label: 'MCP Servers',    desc: 'External tool catalog',  color: 'var(--d-data)' },
      { label: 'Session Memory', desc: 'Redis (hot) · Cosmos',   color: 'var(--d-telephony)' },
    ];
    const stripW = HUB_W - 48;
    const itemW = (stripW - 16) / 3;
    return `
      <text x="${HUB_X + 24}" y="${HUB_STRIP_Y - 10}"
            style="font:600 10.5px Inter,sans-serif;fill:var(--d-text-3);text-transform:uppercase;letter-spacing:0.1em">Shared Capabilities</text>
      ${items.map((it, i) => {
        const x = HUB_X + 24 + i * (itemW + 8);
        return `
          <g transform="translate(${x}, ${HUB_STRIP_Y})">
            <rect width="${itemW}" height="56" rx="6"
                  fill="var(--d-tile-bg)" stroke="${it.color}" stroke-width="1" stroke-opacity="0.45"/>
            <rect width="3" height="56" rx="1.5" fill="${it.color}"/>
            <text x="14" y="22" style="font:600 12px Inter,sans-serif;fill:var(--d-text)">${it.label}</text>
            <text x="14" y="40" style="font:400 11px Inter,sans-serif;fill:var(--d-text-3)">${it.desc}</text>
          </g>`;
      }).join('')}`;
  })();

  // --- Ingress arrows: 4 channels → hub left edge (spread vertically) ---
  const ingress = (() => {
    const x1 = CH_X + 204;
    const x2 = HUB_X - 4;
    const targets = [HUB_Y + 188, HUB_Y + 218, HUB_Y + 248, HUB_Y + 278];
    return CH_YS.map((y, i) => {
      const ySrc = y + 32, yTgt = targets[i];
      return `<path class="flow-arrow flow-arrow-live"
                    d="M${x1} ${ySrc} C${x1 + 45} ${ySrc}, ${x2 - 45} ${yTgt}, ${x2} ${yTgt}"
                    marker-end="url(#arrow)"/>`;
    }).join('');
  })();

  // --- Egress arrows: hub right edge → 3 outputs ---
  const egress = (() => {
    const x1 = HUB_X + HUB_W + 4;
    const x2 = OUT_X - 4;
    const sources = [HUB_Y + 198, HUB_Y + 238, HUB_Y + 278];
    return OUT_YS.map((y, i) => {
      const yTgt = y + 32, ySrc = sources[i];
      return `<path class="flow-arrow flow-arrow-live flow-out"
                    d="M${x1} ${ySrc} C${x1 + 45} ${ySrc}, ${x2 - 45} ${yTgt}, ${x2} ${yTgt}"
                    marker-end="url(#arrow)"/>`;
    }).join('');
  })();

  // --- Footer capability ribbon ---
  const footer = (() => {
    const caps = [
      '🎯  Barge-in',
      '⚡  Streaming TTS',
      '🛠  Function calling',
      '🎙  Custom Speech',
      '🔐  Managed identity',
      '🌐  Private networking',
      '📊  OpenTelemetry',
    ];
    const itemW = (VBW - 80) / caps.length;
    return `
      <rect x="24" y="${VBH - 58}" width="${VBW - 48}" height="42" rx="8"
            fill="var(--d-zone-bg)" stroke="var(--d-tile-border)" stroke-dasharray="3 3"/>
      ${caps.map((c, i) => {
        const x = 40 + i * itemW + itemW / 2;
        return `<text x="${x}" y="${VBH - 32}" text-anchor="middle"
                      style="font:500 12px Inter,sans-serif;fill:var(--d-text-2)">${c}</text>`;
      }).join('')}`;
  })();

  return `
  <svg viewBox="0 0 ${VBW} ${VBH}" xmlns="http://www.w3.org/2000/svg" class="az-svg"
       role="img" aria-label="ART Agent omnichannel real-time voice experience">
    ${DEFS}

    <!-- ==== Title ==== -->
    <text x="${VBW/2}" y="44" text-anchor="middle"
          style="font:700 24px Inter,sans-serif;fill:var(--d-text);letter-spacing:-0.02em">Real-Time Omnichannel Voice Experience</text>
    <text x="${VBW/2}" y="70" text-anchor="middle"
          style="font:400 13.5px Inter,sans-serif;fill:var(--d-text-3)">Same agents. Every channel. Sub-second latency.</text>

    <!-- ==== Value-prop chips ==== -->
    ${chipsRow}

    <!-- ==== Channels column ==== -->
    <text class="zone-title" x="${CH_X + 100}" y="154" text-anchor="middle">Channels In</text>
    ${tile(CH_X, CH_YS[0], 'telephony', 'Phone (PSTN)',     'Inbound SIP · 1-800 number',    'phone')}
    ${tile(CH_X, CH_YS[1], 'channel',   'Web / Mobile',     'ACS SDK · click-to-call',       'browser')}
    ${tile(CH_X, CH_YS[2], 'telephony', 'Contact Center',   'Genesys · NICE · AWS Connect',  'sbc')}
    ${tile(CH_X, CH_YS[3], 'channel',   'Microsoft Teams',  'Direct routing · native ACS',   'globe')}

    <!-- ==== ART Agent Hub ==== -->
    <rect x="${HUB_X}" y="${HUB_Y}" width="${HUB_W}" height="${HUB_H}" rx="12"
          fill="var(--d-zone-bg)" stroke="var(--d-app)" stroke-width="1.5"/>
    <rect x="${HUB_X}" y="${HUB_Y}" width="${HUB_W}" height="4" rx="2" fill="var(--d-app)"/>

    <text x="${HUB_CX}" y="${HUB_TITLE_Y}" text-anchor="middle"
          style="font:700 17px Inter,sans-serif;fill:var(--d-text);letter-spacing:-0.01em">◆ ART Agent Core</text>
    <text x="${HUB_CX}" y="${HUB_TITLE_Y + 18}" text-anchor="middle"
          style="font:500 10.5px Inter,sans-serif;fill:var(--d-text-3);text-transform:uppercase;letter-spacing:0.1em">FastAPI · Azure Container Apps</text>

    ${modeStrip}
    ${swarm}
    ${capStrip}

    <!-- ==== Outputs column ==== -->
    <text class="zone-title" x="${OUT_X + 100}" y="154" text-anchor="middle">Outcomes</text>
    ${tile(OUT_X, OUT_YS[0], 'telephony', 'Live Agent',    'Warm handoff · context passed', 'phone')}
    ${tile(OUT_X, OUT_YS[1], 'data',      'CRM / Cosmos',  'Transcripts · audit · profiles', 'cosmos')}
    ${tile(OUT_X, OUT_YS[2], 'observ',    'Observability', 'OpenTelemetry · App Insights',   'insights')}

    <!-- ==== Flow arrows ==== -->
    ${ingress}
    ${egress}

    <!-- ==== Footer capability ribbon ==== -->
    ${footer}
  </svg>`;
};

/* ============================================================
   DIAGRAM — Framework positioning (MAF vs our turn-by-turn loop)
   ============================================================ */
const FRAMEWORK_POSITIONING = () => {
  const VBW = 1240, VBH = 440;

  const lbl = (x, y, text, color) => `
    <rect x="${x - text.length * 3.2 - 5}" y="${y - 9}" width="${text.length * 6.4 + 10}" height="14" rx="7"
          fill="var(--c-bg)" stroke="${color || 'var(--d-arrow)'}" stroke-width="0.8"/>
    <text class="flow-label" x="${x}" y="${y + 1}" text-anchor="middle" style="fill:${color || 'var(--d-arrow)'}">${text}</text>`;

  // Track headers
  const trackBg = (y, h, fill, stroke, label, sub, color) => `
    <rect x="20" y="${y}" width="${VBW - 40}" height="${h}" rx="10" fill="${fill}" stroke="${stroke}" stroke-width="1.2" stroke-dasharray="6 4"/>
    <g transform="translate(36, ${y - 10})">
      <rect width="${label.length * 7.2 + 16}" height="18" rx="9" fill="${color}"/>
      <text x="${(label.length * 7.2 + 16)/2}" y="12" text-anchor="middle" style="font:700 10px Inter,sans-serif;letter-spacing:.12em;fill:#fff">${label}</text>
    </g>
    <text x="${VBW - 36}" y="${y + 14}" text-anchor="end" style="font:400 11px Inter,sans-serif;fill:var(--d-text-3);font-style:italic">${sub}</text>`;

  // Simple labelled "step" pill for MAF top track
  const mafStep = (x, y, w, h, name, desc, color) => `
    <g transform="translate(${x}, ${y})" filter="url(#tile-shadow)">
      <rect width="${w}" height="${h}" rx="8" fill="var(--d-tile-bg)" stroke="${color}" stroke-width="1.5"/>
      <rect width="3" height="${h}" rx="1.5" fill="${color}"/>
      <text x="${w/2}" y="24" text-anchor="middle" style="font:600 11px Inter,sans-serif;fill:var(--d-text)">${name}</text>
      <text x="${w/2}" y="40" text-anchor="middle" style="font:400 9px Inter,sans-serif;fill:var(--d-text-3)">${desc}</text>
    </g>`;

  const ourStep = (x, y, w, h, num, name, desc, color, animDelay) => `
    <g transform="translate(${x}, ${y})">
      <rect width="${w}" height="${h}" rx="6" fill="var(--d-tile-bg)" stroke="${color}" stroke-width="1.4"/>
      <rect width="3" height="${h}" rx="1.5" fill="${color}"/>
      <circle cx="${w - 14}" cy="14" r="9" fill="${color}" class="art-pulse-dot" style="animation-delay:${animDelay}s"/>
      <text x="${w - 14}" y="17" text-anchor="middle" style="font:700 10px Inter,sans-serif;fill:#fff">${num}</text>
      <text x="10" y="22" style="font:600 11px Inter,sans-serif;fill:var(--d-text)">${name}</text>
      <text x="10" y="36" style="font:400 9px Inter,sans-serif;fill:var(--d-text-3)">${desc}</text>
    </g>`;

  return `
<svg viewBox="0 0 ${VBW} ${VBH}" xmlns="http://www.w3.org/2000/svg" class="az-svg" role="img" aria-label="Framework positioning: Agent Framework vs our orchestrator">
  ${DEFS}

  <text x="${VBW/2}" y="28" text-anchor="middle" style="font:600 17px Inter,sans-serif;fill:var(--d-text)">Microsoft Agent Framework vs. ART Voice Agent Framework</text>
  <text x="${VBW/2}" y="50" text-anchor="middle" style="font:400 12px Inter,sans-serif;fill:var(--d-text-3)">MAF is strong for agents and workflows; this accelerator keeps the realtime audio loop explicit</text>

  <!-- ===== TOP TRACK — Microsoft Agent Framework approach ===== -->
  ${trackBg(70, 128, 'rgba(92,45,145,0.05)', '#5C2D91', 'MICROSOFT AGENT FRAMEWORK', 'agents · tools · workflows · handoffs', '#5C2D91')}

  ${mafStep(44,  128, 132, 58, 'App / host', 'starts', '#5C2D91')}
  <path class="flow-arrow" d="M176 157 L214 157" marker-end="url(#arrow)"/>
  ${mafStep(214, 118, 286, 76, 'Agent + workflow graph', 'sequential · concurrent · handoff', '#5C2D91')}
  <path class="flow-arrow" d="M500 157 L538 157" marker-end="url(#arrow)"/>
  ${mafStep(538, 118, 270, 76, 'Tools · middleware · memory', 'checkpointing · observability', '#5C2D91')}
  <path class="flow-arrow" d="M808 157 L846 157" marker-end="url(#arrow)"/>
  ${mafStep(846, 128, 130, 58, 'Result', 'reply', '#5C2D91')}

  <text x="610" y="212" text-anchor="middle" style="font:italic 10px Inter,sans-serif;fill:var(--d-text-3)">good for agent logic and workflow orchestration · not where we want to hide the realtime audio seams</text>

  <text x="610" y="232" text-anchor="middle" style="font:600 10px Inter,sans-serif;fill:#5C2D91">Current support: Python + .NET · tools · middleware · workflows · handoffs · streaming · observability</text>
  <text x="610" y="246" text-anchor="middle" style="font:600 10px Inter,sans-serif;fill:#5C2D91">Best fit: agent graphs, policy, tool execution, and stateful orchestration above the audio layer</text>

  <!-- ===== BOTTOM TRACK — Our orchestrator ===== -->
  ${trackBg(284, 124, 'rgba(16,124,16,0.05)', '#107C10', 'ART VOICE AGENT FRAMEWORK', 'explicit per-stage pipeline', '#107C10')}

  <!-- Caller audio in -->
  ${mafStep(34, 308, 84, 50, 'Caller', 'audio', 'var(--d-channel)')}
  <path class="flow-arrow" d="M118 333 L144 333" marker-end="url(#arrow)"/>

  <!-- 5 explicit numbered stages -->
  ${ourStep(144, 308, 122, 50, 1, 'VAD', 'turn boundary',  'var(--d-app)',       0.0)}
  <path class="flow-arrow" d="M266 333 L286 333" marker-end="url(#arrow)"/>
  ${ourStep(286, 308, 122, 50, 2, 'STT', 'partial → final',        '#107C10',            0.4)}
  <path class="flow-arrow" d="M408 333 L428 333" marker-end="url(#arrow)"/>
  ${ourStep(428, 308, 122, 50, 3, 'LLM', 'first token + tools',    '#107C10',            0.8)}
  <path class="flow-arrow" d="M550 333 L570 333" marker-end="url(#arrow)"/>
  ${ourStep(570, 308, 122, 50, 4, 'TTS', 'first audio chunk',      '#107C10',            1.2)}
  <path class="flow-arrow" d="M692 333 L712 333" marker-end="url(#arrow)"/>
  ${ourStep(712, 308, 122, 50, 5, 'Pump', 'cancellable', 'var(--d-telephony)', 1.6)}
  <path class="flow-arrow" d="M834 333 L860 333" marker-end="url(#arrow)"/>
  ${mafStep(860, 308, 146, 50, 'Reply', 'streaming', 'var(--d-channel)')}

  <text x="610" y="396" text-anchor="middle" style="font:italic 10px Inter,sans-serif;fill:var(--d-text-3)">
    we own each transition · cancel TTS mid-utterance on barge-in · stream first LLM token straight into TTS · OpenTelemetry span per stage
  </text>

  <text x="76" y="418" style="font:700 10px Inter,sans-serif;letter-spacing:.08em;text-transform:uppercase;fill:#107C10">Integration path</text>
  <text x="190" y="418" style="font:400 10px Inter,sans-serif;fill:var(--d-text-2)">keep audio transport here; hand off agent graph + tools to MAF</text>

  <!-- Bottom rationale line -->
  <line x1="20" y1="412" x2="${VBW - 20}" y2="412" stroke="var(--d-tile-border)" stroke-width="1"/>
  <text x="30" y="430" style="font:600 11px Inter,sans-serif;fill:var(--d-text)">Rationale:</text>
  <text x="98" y="430" style="font:400 11px Inter,sans-serif;fill:var(--d-text-2)">MAF is a good fit for the orchestration layer today · the custom loop remains useful where realtime audio control matters most</text>
</svg>`;
};

/* ============================================================
   DIAGRAM — Turn latency budget (animated stacked bar)
   ============================================================ */
const TURN_LATENCY_BUDGET = () => {
  const VBW = 1240, VBH = 360;

  // Segments: [name, ms, color, sublabel]
  const stages = [
    ['VAD end-of-speech',  60,  'var(--d-app)',       'silence detected'],
    ['STT final transcript', 180, '#107C10',           'recognition complete'],
    ['LLM first token',    420, '#107C10',           'GPT-4o response begins'],
    ['TTS first audio',    140, '#107C10',           'first frame ready'],
    ['Network / pump',      80, 'var(--d-telephony)', 'jitter buffer · ACS bridge'],
  ];
  const total = stages.reduce((s, [,ms]) => s + ms, 0); // 880

  const barX = 60, barY = 130, barW = 1120, barH = 56;
  let cursor = 0;
  let segments = '';
  let labels = '';
  let timestamps = '';
  stages.forEach(([name, ms, color, sub], i) => {
    const segW = (ms / 1000) * barW;
    const segX = barX + (cursor / 1000) * barW;
    const delay = i * 0.55;
    segments += `
      <g class="art-budget-seg" style="animation-delay:${delay}s">
        <rect x="${segX}" y="${barY}" width="${segW}" height="${barH}" fill="${color}" fill-opacity="0.18" stroke="${color}" stroke-width="1.2"/>
        <text x="${segX + segW/2}" y="${barY + barH/2 + 5}" text-anchor="middle" style="font:600 12px Inter,sans-serif;fill:${color}">${ms} ms</text>
      </g>`;
    // Label below
    labels += `
      <g class="art-budget-label" style="animation-delay:${delay + 0.15}s">
        <line x1="${segX + segW/2}" y1="${barY + barH + 6}" x2="${segX + segW/2}" y2="${barY + barH + 20}" stroke="${color}" stroke-width="1"/>
        <text x="${segX + segW/2}" y="${barY + barH + 36}" text-anchor="middle" style="font:600 11px Inter,sans-serif;fill:var(--d-text)">${name}</text>
        <text x="${segX + segW/2}" y="${barY + barH + 50}" text-anchor="middle" style="font:400 10px Inter,sans-serif;fill:var(--d-text-3)">${sub}</text>
      </g>`;
    cursor += ms;
    timestamps += `
      <g class="art-budget-tick" style="animation-delay:${delay + 0.3}s">
        <text x="${barX + (cursor / 1000) * barW}" y="${barY - 10}" text-anchor="middle" style="font:500 10px JetBrains Mono,monospace;fill:var(--d-text-2)">${cursor}ms</text>
      </g>`;
  });

  // 1000ms budget marker
  const budgetX = barX + barW;

  return `
<svg viewBox="0 0 ${VBW} ${VBH}" xmlns="http://www.w3.org/2000/svg" class="az-svg" role="img" aria-label="Per-turn latency budget breakdown">
  ${DEFS}

  <text x="${VBW/2}" y="32" text-anchor="middle" style="font:600 17px Inter,sans-serif;fill:var(--d-text)">A single turn has a ~1-second budget — every stage fights for it</text>
  <text x="${VBW/2}" y="54" text-anchor="middle" style="font:400 12px Inter,sans-serif;fill:var(--d-text-3)">Anything over 1 second feels like lag. This is why we own the audio loop instead of waiting on a high-level abstraction.</text>

  <!-- Budget cap line + label -->
  <line x1="${budgetX}" y1="${barY - 24}" x2="${budgetX}" y2="${barY + barH + 24}" stroke="var(--d-telephony)" stroke-width="1.5" stroke-dasharray="3 3"/>
  <rect x="${budgetX - 36}" y="${barY - 38}" width="78" height="16" rx="8" fill="var(--c-bg)" stroke="var(--d-telephony)" stroke-width="1"/>
  <text x="${budgetX + 3}" y="${barY - 27}" text-anchor="middle" style="font:600 10px Inter,sans-serif;fill:var(--d-telephony)">1000 ms cap</text>

  <!-- Bar baseline (faint) -->
  <rect x="${barX}" y="${barY}" width="${barW}" height="${barH}" fill="var(--d-zone-bg)" stroke="var(--d-tile-border)" stroke-width="1"/>

  ${timestamps}
  ${segments}
  ${labels}

  <!-- Total -->
  <g transform="translate(${VBW/2 - 130}, 270)">
    <rect width="260" height="36" rx="18" fill="var(--c-bg)" stroke="var(--d-text)" stroke-width="1.4"/>
    <text x="14" y="23" style="font:600 12px Inter,sans-serif;fill:var(--d-text-3)">measured floor:</text>
    <text x="130" y="23" style="font:700 14px JetBrains Mono,monospace;fill:var(--d-text)">${total} ms</text>
    <text x="200" y="23" style="font:400 11px Inter,sans-serif;fill:var(--d-text-3)">/ 1000 ms</text>
  </g>

  <text x="${VBW/2}" y="334" text-anchor="middle" style="font:italic 11px Inter,sans-serif;fill:var(--d-text-3)">
    Connection pooling (skip 100–500 ms client init) · token streaming (don't wait for the full LLM reply) · cancellable audio pump (drop the rest on barge-in) — each shaves a slice
  </text>
</svg>`;
};

/* ============================================================
   DIAGRAM — Barge-in / interruption flow
   ============================================================ */
const BARGE_IN_FLOW = () => {
  const VBW = 1240, VBH = 380;

  const laneY = { caller: 110, vad: 180, orch: 250, tts: 320 };
  const laneX0 = 160, laneX1 = VBW - 40;

  const lane = (y, label, color) => `
    <line x1="${laneX0}" y1="${y}" x2="${laneX1}" y2="${y}" stroke="var(--d-tile-border)" stroke-width="1" stroke-dasharray="2 3"/>
    <rect x="20" y="${y - 14}" width="130" height="28" rx="6" fill="${color}" fill-opacity="0.1" stroke="${color}" stroke-width="1"/>
    <text x="85" y="${y + 4}" text-anchor="middle" style="font:600 11px Inter,sans-serif;fill:${color}">${label}</text>`;

  // Event marker: circle + label
  const event = (x, y, label, color, anim = 0) => `
    <g class="art-barge-event" style="animation-delay:${anim}s">
      <circle cx="${x}" cy="${y}" r="6" fill="${color}"/>
      <rect x="${x - label.length * 3.2 - 6}" y="${y - 30}" width="${label.length * 6.4 + 12}" height="16" rx="8" fill="var(--c-bg)" stroke="${color}" stroke-width="0.8"/>
      <text x="${x}" y="${y - 19}" text-anchor="middle" style="font:500 10px Inter,sans-serif;fill:${color}">${label}</text>
    </g>`;

  // Speech waveform (decorative bars)
  const wave = (x, y, w, color, animClass, delay) => {
    let bars = '';
    const n = Math.floor(w / 5);
    for (let i = 0; i < n; i++) {
      const h = 4 + Math.abs(Math.sin(i * 0.7)) * 14;
      bars += `<rect x="${x + i*5}" y="${y - h/2}" width="3" height="${h}" rx="1.5" fill="${color}" fill-opacity="0.55"/>`;
    }
    return `<g class="${animClass}" style="animation-delay:${delay}s">${bars}</g>`;
  };

  return `
<svg viewBox="0 0 ${VBW} ${VBH}" xmlns="http://www.w3.org/2000/svg" class="az-svg" role="img" aria-label="Barge-in: how user interruption cancels in-flight TTS">
  ${DEFS}

  <text x="${VBW/2}" y="32" text-anchor="middle" style="font:600 17px Inter,sans-serif;fill:var(--d-text)">Barge-in — why we own the audio loop</text>
  <text x="${VBW/2}" y="54" text-anchor="middle" style="font:400 12px Inter,sans-serif;fill:var(--d-text-3)">When the caller interrupts the agent, we have to cancel in-flight TTS, drain the audio buffer, and re-arm STT — all within ~150 ms</text>

  <!-- Lanes -->
  ${lane(laneY.caller, 'Caller mic',     'var(--d-channel)')}
  ${lane(laneY.vad,    'VAD',            'var(--d-app)')}
  ${lane(laneY.orch,   'Orchestrator',   '#107C10')}
  ${lane(laneY.tts,    'TTS audio out',  'var(--d-telephony)')}

  <!-- Phase 1: agent speaking — TTS wave on bottom lane -->
  ${wave(180, laneY.tts, 380, 'var(--d-telephony)', 'art-wave-fade-out', 1.4)}
  ${event(200, laneY.tts, 'agent.synthesize()', 'var(--d-telephony)', 0.2)}

  <!-- User starts talking — caller mic wave -->
  ${wave(400, laneY.caller, 180, 'var(--d-channel)', 'art-wave-appear', 1.2)}
  ${event(420, laneY.caller, 'user starts talking', 'var(--d-channel)', 1.2)}

  <!-- VAD fires speech-start event -->
  ${event(520, laneY.vad, 'speech_started event', 'var(--d-app)', 1.6)}
  <path class="flow-arrow art-barge-arrow" style="animation-delay:1.6s" d="M520 ${laneY.caller + 8} L520 ${laneY.vad - 8}" marker-end="url(#arrow)"/>

  <!-- Orchestrator: cancel in-flight tasks -->
  ${event(620, laneY.orch, 'orchestrator.cancel_turn()', '#107C10', 2.0)}
  <path class="flow-arrow art-barge-arrow" style="animation-delay:2.0s" d="M520 ${laneY.vad + 8} C570 ${laneY.vad + 30}, 580 ${laneY.orch - 30}, 620 ${laneY.orch - 8}" marker-end="url(#arrow)"/>

  <!-- Orchestrator → TTS: kill audio pump -->
  ${event(720, laneY.tts, 'tts.flush() · audio buffer drained', 'var(--d-telephony)', 2.4)}
  <path class="flow-arrow art-barge-arrow" style="animation-delay:2.4s" d="M620 ${laneY.orch + 8} C660 ${laneY.orch + 30}, 680 ${laneY.tts - 30}, 720 ${laneY.tts - 8}" marker-end="url(#arrow)"/>

  <!-- VAD waveform after start -->
  ${wave(720, laneY.vad, 220, 'var(--d-app)', 'art-wave-appear', 2.6)}

  <!-- User finishes — orchestrator processes new turn -->
  ${event(990, laneY.vad, 'speech_ended', 'var(--d-app)', 3.0)}
  ${event(1080, laneY.orch, 'next turn begins', '#107C10', 3.4)}
  <path class="flow-arrow art-barge-arrow" style="animation-delay:3.4s" d="M990 ${laneY.vad + 8} C1030 ${laneY.vad + 30}, 1040 ${laneY.orch - 30}, 1080 ${laneY.orch - 8}" marker-end="url(#arrow)"/>

  <!-- Footer note -->
  <text x="${VBW/2}" y="362" text-anchor="middle" style="font:italic 11px Inter,sans-serif;fill:var(--d-text-3)">
    A higher-level abstraction would treat the agent's reply as one atomic call — by the time the framework finishes, the caller has already said "wait, no, actually…"
  </text>
</svg>`;
};

/* ============================================================
   DIAGRAM — Session isolation: concurrent calls, per-session lanes
   Grounded in: per-call session_id + call_connection_id, per-handler
   queues, per-session MemoManager keys, animated audio flow per call
   ============================================================ */
const SESSION_ISOLATION = () => {
  const VBW = 1240, VBH = 420;

  const sessions = [
    { id: 'sess_001', call: 'cc_aaaa', agent: 'Concierge',  y: 100, hue: '#0078D4' },
    { id: 'sess_002', call: 'cc_bbbb', agent: 'FraudAgent', y: 210, hue: '#CA5010' },
    { id: 'sess_003', call: 'cc_cccc', agent: 'Concierge',  y: 320, hue: '#107C10' },
  ];

  const colX = { client: 60, ingress: 250, handler: 470, queue: 700, state: 940, redis: 1130 };

  const laneBg = (y, color) => `
    <rect x="20" y="${y - 36}" width="${VBW - 40}" height="72" rx="10"
          fill="${color}" fill-opacity="0.05" stroke="${color}" stroke-opacity="0.25" stroke-width="1"/>`;

  const node = (x, y, w, label, sub, color) => `
    <g>
      <rect x="${x}" y="${y - 22}" width="${w}" height="44" rx="6"
            fill="var(--d-tile-bg)" stroke="${color}" stroke-width="1.2"/>
      <rect x="${x}" y="${y - 22}" width="3" height="44" rx="1.5" fill="${color}"/>
      <text x="${x + 10}" y="${y - 4}" style="font:600 12px Inter,sans-serif;fill:var(--d-text)">${label}</text>
      <text x="${x + 10}" y="${y + 12}" style="font:400 10px JetBrains Mono,monospace;fill:var(--d-text-3)">${sub}</text>
    </g>`;

  const liveArrow = (x1, x2, y, color, delay) => `
    <path d="M${x1} ${y} L${x2} ${y}"
          stroke="${color}" stroke-width="1.8" fill="none"
          stroke-dasharray="5 6"
          style="animation: art-flow-pulse 1.6s linear infinite; animation-delay:${delay}s"
          marker-end="url(#arrow)"/>`;

  let svg = `
<svg viewBox="0 0 ${VBW} ${VBH}" xmlns="http://www.w3.org/2000/svg" class="az-svg" role="img" aria-label="How concurrent voice sessions stay isolated">
  ${DEFS}
  <text x="${VBW/2}" y="32" text-anchor="middle" style="font:600 17px Inter,sans-serif;fill:var(--d-text)">Concurrent session isolation</text>
  <text x="${VBW/2}" y="54" text-anchor="middle" style="font:400 12px Inter,sans-serif;fill:var(--d-text-3)">Three calls on the same container — each gets its own handler, queue, MemoManager keys, and Redis namespace</text>

  <text x="${colX.client + 55}"  y="78" text-anchor="middle" style="font:600 10px Inter,sans-serif;letter-spacing:.08em;text-transform:uppercase;fill:var(--d-text-3)">Caller</text>
  <text x="${colX.ingress + 90}" y="78" text-anchor="middle" style="font:600 10px Inter,sans-serif;letter-spacing:.08em;text-transform:uppercase;fill:var(--d-text-3)">Ingress (ACS / WS)</text>
  <text x="${colX.handler + 100}" y="78" text-anchor="middle" style="font:600 10px Inter,sans-serif;letter-spacing:.08em;text-transform:uppercase;fill:var(--d-text-3)">Per-session handler</text>
  <text x="${colX.queue + 100}"   y="78" text-anchor="middle" style="font:600 10px Inter,sans-serif;letter-spacing:.08em;text-transform:uppercase;fill:var(--d-text-3)">Speech queue / span</text>
  <text x="${colX.state + 80}"    y="78" text-anchor="middle" style="font:600 10px Inter,sans-serif;letter-spacing:.08em;text-transform:uppercase;fill:var(--d-text-3)">MemoManager</text>
  <text x="${colX.redis + 50}"    y="78" text-anchor="middle" style="font:600 10px Inter,sans-serif;letter-spacing:.08em;text-transform:uppercase;fill:var(--d-text-3)">Redis key</text>
  `;

  sessions.forEach((s, i) => {
    const delay = (i * 0.35).toFixed(2);
    svg += laneBg(s.y, s.hue);
    svg += node(colX.client, s.y, 110, `Caller ${i + 1}`, s.call, s.hue);
    svg += node(colX.ingress, s.y, 180, 'ACS WebSocket', `session_id=${s.id}`, s.hue);
    svg += node(colX.handler, s.y, 200, `${i === 1 ? 'VoiceLive' : 'SpeechCascade'} handler`, `agent=${s.agent}`, s.hue);
    svg += node(colX.queue, s.y, 200, i === 1 ? 'response_id active' : 'asyncio.Queue', i === 1 ? 'turn span open' : 'FINAL events', s.hue);
    svg += node(colX.state, s.y, 160, 'MemoManager', `turn_id=${(i + 1) * 7}`, s.hue);
    svg += `
      <g>
        <rect x="${colX.redis}" y="${s.y - 18}" width="100" height="36" rx="6"
              fill="${s.hue}" fill-opacity="0.12" stroke="${s.hue}" stroke-width="1"/>
        <text x="${colX.redis + 50}" y="${s.y - 2}" text-anchor="middle"
              style="font:600 11px JetBrains Mono,monospace;fill:${s.hue}">sess:${s.id.slice(-3)}</text>
        <text x="${colX.redis + 50}" y="${s.y + 12}" text-anchor="middle"
              style="font:400 9px Inter,sans-serif;fill:var(--d-text-3)">TTL · isolated</text>
      </g>`;

    svg += liveArrow(colX.client + 110, colX.ingress, s.y, s.hue, +delay);
    svg += liveArrow(colX.ingress + 180, colX.handler, s.y, s.hue, +delay + 0.15);
    svg += liveArrow(colX.handler + 200, colX.queue, s.y, s.hue, +delay + 0.30);
    svg += liveArrow(colX.queue + 200, colX.state, s.y, s.hue, +delay + 0.45);
    svg += liveArrow(colX.state + 160, colX.redis, s.y, s.hue, +delay + 0.60);
  });

  svg += `
    <g transform="translate(${VBW/2 - 240}, 388)">
      <rect width="480" height="22" rx="11" fill="var(--d-ai)" fill-opacity="0.10" stroke="var(--d-ai)" stroke-width="1"/>
      <text x="240" y="15" text-anchor="middle" style="font:600 11px Inter,sans-serif;fill:var(--d-ai)">No shared state across lanes — keys, queues, and turn IDs are session-scoped</text>
    </g>
  </svg>`;

  return svg;
};

/* ============================================================
   DIAGRAM — Session memory lifecycle
   Grounded in: sync_state_from_memo / sync_state_to_memo, per-turn
   updates, persist_to_redis_async on stop, post-call Cosmos archival
   ============================================================ */
const MEMORY_LIFECYCLE = () => {
  const VBW = 1240, VBH = 410;

  const laneY = { handler: 110, memo: 200, redis: 290, cosmos: 360 };
  const laneX0 = 180, laneX1 = VBW - 30;

  const lane = (y, label, color, sub) => `
    <line x1="${laneX0}" y1="${y}" x2="${laneX1}" y2="${y}" stroke="var(--d-tile-border)" stroke-width="1" stroke-dasharray="2 3"/>
    <rect x="20" y="${y - 18}" width="150" height="36" rx="6" fill="${color}" fill-opacity="0.10" stroke="${color}" stroke-width="1"/>
    <text x="95" y="${y - 2}" text-anchor="middle" style="font:600 11px Inter,sans-serif;fill:${color}">${label}</text>
    <text x="95" y="${y + 12}" text-anchor="middle" style="font:400 9px Inter,sans-serif;fill:var(--d-text-3)">${sub}</text>`;

  const event = (x, y, label, color, delay) => `
    <g class="art-barge-event" style="animation-delay:${delay}s">
      <circle cx="${x}" cy="${y}" r="6" fill="${color}"/>
      <rect x="${x - label.length * 3.0 - 6}" y="${y - 30}" width="${label.length * 6.0 + 12}" height="16" rx="8"
            fill="var(--c-bg)" stroke="${color}" stroke-width="0.8"/>
      <text x="${x}" y="${y - 19}" text-anchor="middle" style="font:500 10px Inter,sans-serif;fill:${color}">${label}</text>
    </g>`;

  const arrow = (x1, y1, x2, y2, delay, dashed = false) => `
    <path class="flow-arrow art-barge-arrow${dashed ? ' flow-arrow-dashed' : ''}" style="animation-delay:${delay}s"
          d="M${x1} ${y1} C${(x1 + x2) / 2} ${y1}, ${(x1 + x2) / 2} ${y2}, ${x2} ${y2}"
          marker-end="url(#arrow)"/>`;

  const phase = (x, label) => `
    <text x="${x}" y="78" text-anchor="middle" style="font:600 11px Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;fill:var(--d-text-3)">${label}</text>`;

  return `
<svg viewBox="0 0 ${VBW} ${VBH}" xmlns="http://www.w3.org/2000/svg" class="az-svg" role="img" aria-label="Session memory lifecycle — what persists, when">
  ${DEFS}

  <text x="${VBW/2}" y="32" text-anchor="middle" style="font:600 17px Inter,sans-serif;fill:var(--d-text)">Session memory lifecycle</text>
  <text x="${VBW/2}" y="54" text-anchor="middle" style="font:400 12px Inter,sans-serif;fill:var(--d-text-3)">Read on start · in-memory turn updates · async Redis writes on tool/turn boundaries · Cosmos archival on call end</text>

  ${phase(260, '1 · Session start')}
  ${phase(490, '2 · Turn loop')}
  ${phase(720, '3 · Tool boundary')}
  ${phase(950, '4 · Stop / cleanup')}
  ${phase(1150, '5 · Post-call')}

  ${lane(laneY.handler, 'Voice handler',   'var(--d-app)',       'speech_cascade · voicelive')}
  ${lane(laneY.memo,    'MemoManager',     'var(--d-data)',      'sync_state_to_memo · turn_id')}
  ${lane(laneY.redis,   'Azure Redis',     'var(--d-channel)',   'persist_to_redis_async · TTL')}
  ${lane(laneY.cosmos,  'Cosmos DB',       'var(--d-telephony)', 'post-call archive only')}

  <!-- Phase 1: read on start -->
  ${event(260, laneY.handler, 'handler init', 'var(--d-app)', 0.0)}
  ${event(260, laneY.memo, 'sync_state_from_memo()', 'var(--d-data)', 0.3)}
  ${arrow(260, laneY.redis - 8, 260, laneY.memo + 8, 0.5)}
  ${arrow(260, laneY.memo - 8, 260, laneY.handler + 8, 0.7)}

  <!-- Phase 2: per turn updates -->
  ${event(440, laneY.handler, 'turn N: user → assistant', 'var(--d-app)', 1.1)}
  ${event(540, laneY.memo, 'active_agent + system_vars', 'var(--d-data)', 1.4)}
  ${arrow(440, laneY.handler + 8, 540, laneY.memo - 8, 1.4)}

  <!-- Phase 3: tool boundary -->
  ${event(720, laneY.memo, 'advance_turn_for_tool()', 'var(--d-data)', 1.9)}
  ${event(720, laneY.redis, 'create_task(persist_to_redis_async)', 'var(--d-channel)', 2.2)}
  ${arrow(720, laneY.memo + 8, 720, laneY.redis - 8, 2.2, true)}

  <!-- Phase 4: stop / cleanup -->
  ${event(950, laneY.handler, 'handler.stop()', 'var(--d-app)', 2.7)}
  ${event(950, laneY.memo, 'final sync_state_to_memo', 'var(--d-data)', 3.0)}
  ${event(950, laneY.redis, 'await persist_to_redis_async', 'var(--d-channel)', 3.3)}
  ${arrow(950, laneY.handler + 8, 950, laneY.memo - 8, 3.0)}
  ${arrow(950, laneY.memo + 8, 950, laneY.redis - 8, 3.3)}

  <!-- Phase 5: Cosmos archival -->
  ${event(1150, laneY.redis, 'build_and_flush(cm, cosmos)', 'var(--d-channel)', 3.8)}
  ${event(1150, laneY.cosmos, 'transcript + audit row', 'var(--d-telephony)', 4.1)}
  ${arrow(1150, laneY.redis + 8, 1150, laneY.cosmos - 8, 4.1)}

  <text x="${VBW/2}" y="400" text-anchor="middle" style="font:italic 11px Inter,sans-serif;fill:var(--d-text-3)">
    Hot path stays in MemoManager. Redis is the source of truth across containers. Cosmos is cold archive only — never read on the hot path.
  </text>
</svg>`;
};

/* ============================================================
   DIAGRAM — Turn hooks: Speech Cascade vs Voice Live
   Grounded in: on_partial / on_final callbacks (cascade) and
   ServerEventType.* events (voicelive). Both timelines run in sync.
   ============================================================ */
const TURN_HOOKS_COMPARE = () => {
  const VBW = 1280, VBH = 500;

  const trackY = { cascade: 150, voicelive: 350 };
  const trackX0 = 200, trackX1 = VBW - 30;

  const trackHeader = (y, name, sub, color) => `
    <g>
      <rect x="20" y="${y - 36}" width="170" height="72" rx="10"
            fill="${color}" fill-opacity="0.10" stroke="${color}" stroke-width="1"/>
      <text x="105" y="${y - 8}" text-anchor="middle" style="font:700 13px Inter,sans-serif;fill:${color}">${name}</text>
      <text x="105" y="${y + 10}" text-anchor="middle" style="font:400 10px Inter,sans-serif;fill:var(--d-text-3)">${sub}</text>
    </g>`;

  const track = (y) => `
    <line x1="${trackX0}" y1="${y}" x2="${trackX1}" y2="${y}" stroke="var(--d-tile-border)" stroke-width="1.4"/>`;

  const hook = (x, y, name, code, color, delay, side) => {
    const dy = side === 'up' ? -1 : 1;
    const lineEnd = y + dy * 22;
    const boxY    = y + dy * 30;
    const boxW    = Math.max(name.length, code.length) * 6.4 + 18;
    const boxH    = 34;
    const boxTop  = side === 'up' ? boxY - boxH : boxY;
    const nameY   = side === 'up' ? boxY - boxH + 14 : boxY + 13;
    const codeY   = side === 'up' ? boxY - boxH + 28 : boxY + 27;
    return `
      <g class="art-barge-event" style="animation-delay:${delay}s">
        <circle cx="${x}" cy="${y}" r="6" fill="${color}"/>
        <line x1="${x}" y1="${y + dy * 6}" x2="${x}" y2="${lineEnd}" stroke="${color}" stroke-width="1.2"/>
        <rect x="${x - boxW / 2}" y="${boxTop}" width="${boxW}" height="${boxH}" rx="6"
              fill="var(--c-bg)" stroke="${color}" stroke-width="0.9"/>
        <text x="${x}" y="${nameY}" text-anchor="middle" style="font:600 11px Inter,sans-serif;fill:${color}">${name}</text>
        <text x="${x}" y="${codeY}" text-anchor="middle" style="font:500 10px JetBrains Mono,monospace;fill:var(--d-text-3)">${code}</text>
      </g>`;
  };

  const divider = (x, label) => `
    <line x1="${x}" y1="80" x2="${x}" y2="${VBH - 60}" stroke="var(--d-tile-border)" stroke-width="1" stroke-dasharray="2 4"/>
    <text x="${x}" y="74" text-anchor="middle" style="font:600 10px Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;fill:var(--d-text-3)">${label}</text>`;

  const phaseX = { start: 320, partial: 490, final: 670, tool: 850, audio: 1030, done: 1200 };

  return `
<svg viewBox="0 0 ${VBW} ${VBH}" xmlns="http://www.w3.org/2000/svg" class="az-svg" role="img" aria-label="Turn-by-turn hooks: Speech Cascade vs Voice Live">
  ${DEFS}

  <text x="${VBW/2}" y="32" text-anchor="middle" style="font:600 17px Inter,sans-serif;fill:var(--d-text)">Turn hooks — Speech Cascade vs Voice Live</text>
  <text x="${VBW/2}" y="54" text-anchor="middle" style="font:400 12px Inter,sans-serif;fill:var(--d-text-3)">Same logical turn, different surfaces — local callbacks vs realtime server events</text>

  ${divider(phaseX.start,   '1 · Speech start')}
  ${divider(phaseX.partial, '2 · Partial')}
  ${divider(phaseX.final,   '3 · Final transcript')}
  ${divider(phaseX.tool,    '4 · Tool / handoff')}
  ${divider(phaseX.audio,   '5 · TTS output')}
  ${divider(phaseX.done,    '6 · Turn done')}

  ${trackHeader(trackY.cascade, 'Speech Cascade', 'on_* callbacks · per-handler queue', 'var(--d-app)')}
  ${track(trackY.cascade)}

  ${trackHeader(trackY.voicelive, 'Voice Live', 'ServerEventType.* · realtime model', 'var(--d-ai)')}
  ${track(trackY.voicelive)}

  ${hook(phaseX.start,   trackY.cascade, 'speech_started', 'thread_bridge.schedule_barge_in', 'var(--d-app)', 0.10, 'up')}
  ${hook(phaseX.partial, trackY.cascade, 'on_partial(text)', 'on_partial_transcript()', 'var(--d-app)', 0.45, 'up')}
  ${hook(phaseX.final,   trackY.cascade, 'on_final(text)', 'SpeechEventType.FINAL → queue', 'var(--d-app)', 0.80, 'up')}
  ${hook(phaseX.tool,    trackY.cascade, 'tool / handoff', 'advance_turn_for_tool()', 'var(--d-app)', 1.20, 'up')}
  ${hook(phaseX.audio,   trackY.cascade, 'queue_tts_response', 'route_turn_thread', 'var(--d-app)', 1.55, 'up')}
  ${hook(phaseX.done,    trackY.cascade, 'turn done', 'sync_state_to_memo()', 'var(--d-app)', 1.95, 'up')}

  ${hook(phaseX.start,   trackY.voicelive, 'SPEECH_STARTED', 'begin_user_turn · stop audio', 'var(--d-ai)', 0.15, 'down')}
  ${hook(phaseX.partial, trackY.voicelive, 'TRANSCRIPTION_DELTA', 'streaming user envelope', 'var(--d-ai)', 0.50, 'down')}
  ${hook(phaseX.final,   trackY.voicelive, 'TRANSCRIPTION_COMPLETED', 'send_user_message(turn_id)', 'var(--d-ai)', 0.85, 'down')}
  ${hook(phaseX.tool,    trackY.voicelive, 'FUNCTION_CALL_ARGUMENTS_DONE', 'execute_tool · response.create', 'var(--d-ai)', 1.25, 'down')}
  ${hook(phaseX.audio,   trackY.voicelive, 'RESPONSE_AUDIO_DELTA', 'record_tts_first_audio()', 'var(--d-ai)', 1.60, 'down')}
  ${hook(phaseX.done,    trackY.voicelive, 'RESPONSE_DONE', '_finalize_turn_metrics()', 'var(--d-ai)', 2.00, 'down')}

  <g transform="translate(${VBW/2 - 270}, ${VBH - 40})">
    <rect width="540" height="26" rx="13" fill="var(--d-data)" fill-opacity="0.10" stroke="var(--d-data)" stroke-width="1"/>
    <text x="270" y="17" text-anchor="middle" style="font:600 11px Inter,sans-serif;fill:var(--d-data)">Both modes converge on the same session-state contract — MemoManager + Redis</text>
  </g>
</svg>`;
};

/* ============================================================
   DIAGRAM 13 — Per-turn memory flow (and what grows over time)
   Walks one turn through the 10 real function calls, shows which
   memory tier each touches, and surfaces the growth gap that
   long sessions need new strategies to manage.
   ============================================================ */
const MEMORY_PER_TURN = () => {
  const VBW = 1380;
  const VBH = 540;

  // 10 numbered phases across the top
  const phases = [
    { n: 1, label: 'STT final',           fn: 'on_final(text)',                tier: 'inproc' },
    { n: 2, label: 'Hydrate',             fn: 'sync_state_from_memo(cm)',      tier: 'inproc' },
    { n: 3, label: 'User turn',           fn: 'append_to_history(“user”)',     tier: 'inproc' },
    { n: 4, label: 'Read thread',         fn: 'cm.get_history(agent)',         tier: 'inproc' },
    { n: 5, label: 'Cross-agent',         fn: '_get_conversation_history(cm)', tier: 'inproc' },
    { n: 6, label: 'Build vars',          fn: '_build_session_context(cm)',    tier: 'inproc' },
    { n: 7, label: 'LLM + tools',         fn: 'agent.run(…)',                  tier: 'llm'    },
    { n: 8, label: 'Assistant turn',      fn: 'append_to_history(“assistant”)', tier: 'inproc' },
    { n: 9, label: 'Sync state',          fn: 'sync_state_to_memo(cm, …)',     tier: 'inproc' },
    { n:10, label: 'Warm-flush',          fn: 'create_task(persist_to_redis)', tier: 'redis'  },
  ];

  const phaseW = 128;
  const phaseGap = 6;
  const startX = 26;
  const phaseY = 90;
  const phaseH = 84;

  const tierColor = {
    inproc: 'var(--d-app)',
    llm:    'var(--d-ai)',
    redis:  'var(--d-channel)',
  };

  const phaseSvg = phases.map((p, i) => {
    const x = startX + i * (phaseW + phaseGap);
    const color = tierColor[p.tier];
    const delay = (i * 0.18).toFixed(2);
    return `
    <g class="art-barge-event" style="animation-delay:${delay}s">
      <rect x="${x}" y="${phaseY}" width="${phaseW}" height="${phaseH}" rx="8"
            fill="var(--d-tile-bg)" stroke="${color}" stroke-width="1.2"/>
      <circle cx="${x + 16}" cy="${phaseY + 16}" r="10" fill="${color}"/>
      <text x="${x + 16}" y="${phaseY + 19.5}" text-anchor="middle"
            style="font:700 11px Inter,sans-serif;fill:#fff">${p.n}</text>
      <text x="${x + 32}" y="${phaseY + 20}"
            style="font:600 10.5px Inter,sans-serif;fill:var(--d-text)">${p.label}</text>
      <text x="${x + 8}" y="${phaseY + 42}"
            style="font:500 9.5px 'JetBrains Mono',monospace;fill:var(--d-text-3)">${p.fn}</text>
      <rect x="${x + 8}" y="${phaseY + 54}" width="${phaseW - 16}" height="22" rx="4"
            fill="${color}" fill-opacity="0.10" stroke="${color}" stroke-opacity="0.35" stroke-width="0.8"/>
      <text x="${x + phaseW/2}" y="${phaseY + 69}" text-anchor="middle"
            style="font:600 9px Inter,sans-serif;letter-spacing:.05em;text-transform:uppercase;fill:${color}">${p.tier === 'inproc' ? 'in-process' : p.tier === 'llm' ? 'LLM call' : 'async → Redis'}</text>
    </g>`;
  }).join('');

  // Connecting arrows between phases
  const arrows = phases.slice(0, -1).map((_, i) => {
    const x1 = startX + i * (phaseW + phaseGap) + phaseW;
    const x2 = startX + (i + 1) * (phaseW + phaseGap);
    const y = phaseY + phaseH / 2;
    const delay = ((i + 1) * 0.18).toFixed(2);
    return `<path class="art-barge-arrow" style="animation-delay:${delay}s"
              d="M${x1} ${y} L${x2} ${y}" stroke="var(--d-arrow)" stroke-width="1.4" fill="none"
              marker-end="url(#arrow)"/>`;
  }).join('');

  // Storage band
  const bandY = 222;
  const bandH = 140;
  const totalW = phases.length * (phaseW + phaseGap) - phaseGap;

  // Per-agent thread growth bar
  const growthLanes = [
    { label: 'Per-agent thread',  growth: 'append-only, never trimmed', color: 'var(--d-app)',     filled: 0.74, badge: 'GROWS' },
    { label: 'CoreMemory (slots)', growth: 'session_profile, tool outputs, active_agent', color: 'var(--d-data)', filled: 0.32, badge: 'KEYED' },
    { label: 'Redis (warm tier)', growth: 'mirror of MemoManager, async write on turn-end', color: 'var(--d-channel)', filled: 0.74, badge: 'MIRROR' },
  ];

  const growthSvg = growthLanes.map((g, i) => {
    const y = bandY + 24 + i * 36;
    const barX = 230;
    const barMaxW = totalW - 240;
    return `
    <g>
      <text x="${startX}" y="${y + 4}" style="font:600 11px Inter,sans-serif;fill:var(--d-text)">${g.label}</text>
      <text x="${startX}" y="${y + 18}" style="font:400 9.5px Inter,sans-serif;fill:var(--d-text-3)">${g.growth}</text>
      <rect x="${barX}" y="${y - 8}" width="${barMaxW}" height="14" rx="7"
            fill="var(--d-tile-bg)" stroke="${g.color}" stroke-opacity="0.3" stroke-width="0.8"/>
      <rect x="${barX + 2}" y="${y - 6}" width="${(barMaxW - 4) * g.filled}" height="10" rx="5"
            fill="${g.color}" fill-opacity="0.7"/>
      <rect x="${barX + barMaxW + 8}" y="${y - 9}" width="58" height="16" rx="8"
            fill="${g.color}" fill-opacity="0.12" stroke="${g.color}" stroke-opacity="0.5"/>
      <text x="${barX + barMaxW + 37}" y="${y + 2}" text-anchor="middle"
            style="font:700 9px Inter,sans-serif;letter-spacing:.06em;fill:${g.color}">${g.badge}</text>
    </g>`;
  }).join('');

  // Levers row (planned mitigations)
  const leverY = 410;
  const leverColor = 'var(--d-telephony)';
  const levers = [
    { title: 'Rolling window',        body: 'cap get_history() at N turns or T tokens' },
    { title: 'Turn summarizer',        body: 'collapse stale turns into 1 system note' },
    { title: 'Fact extraction',        body: 'extract entities → CoreMemory slots' },
    { title: 'Cosmos RAG retrieval',  body: 'inject K relevant past-turn snippets' },
  ];
  const leverW = 280;
  const leverGap = 18;
  const leverStartX = (VBW - (levers.length * leverW + (levers.length - 1) * leverGap)) / 2;

  const leverSvg = levers.map((l, i) => {
    const x = leverStartX + i * (leverW + leverGap);
    return `
    <g>
      <rect x="${x}" y="${leverY}" width="${leverW}" height="82" rx="8"
            fill="var(--d-tile-bg)" stroke="${leverColor}" stroke-width="1.2" stroke-dasharray="5 3"/>
      <rect x="${x + 10}" y="${leverY + 10}" width="58" height="16" rx="8"
            fill="${leverColor}"/>
      <text x="${x + 39}" y="${leverY + 21}" text-anchor="middle"
            style="font:700 9px Inter,sans-serif;letter-spacing:.10em;fill:#fff">PLANNED</text>
      <text x="${x + 78}" y="${leverY + 22}"
            style="font:600 12px Inter,sans-serif;fill:var(--d-text)">${l.title}</text>
      <text x="${x + 14}" y="${leverY + 48}"
            style="font:400 10.5px Inter,sans-serif;fill:var(--d-text-3)">${l.body}</text>
      <text x="${x + 14}" y="${leverY + 66}"
            style="font:500 9.5px 'JetBrains Mono',monospace;fill:${leverColor};opacity:0.85">insert between ⑧ and ⑨</text>
    </g>`;
  }).join('');

  return `
  <svg viewBox="0 0 ${VBW} ${VBH}" xmlns="http://www.w3.org/2000/svg" class="az-svg" role="img"
       aria-label="Per-turn memory flow with growth indicators and planned compaction levers">
    ${DEFS}

    <text x="${VBW/2}" y="26" text-anchor="middle"
          style="font:600 16px Inter,sans-serif;fill:var(--d-text)">Per-turn memory flow</text>
    <text x="${VBW/2}" y="46" text-anchor="middle"
          style="font:400 11.5px Inter,sans-serif;fill:var(--d-text-3)">10 calls per turn · only step 10 touches Redis · Cosmos only at end-of-call</text>

    ${arrows}
    ${phaseSvg}

    <!-- Growth band -->
    <rect x="${startX - 8}" y="${bandY}" width="${totalW + 16}" height="${bandH}" rx="8"
          fill="var(--d-zone-bg)" stroke="var(--d-tile-border)" stroke-opacity="0.5"/>
    <text x="${startX}" y="${bandY + 14}"
          style="font:600 10px Inter,sans-serif;letter-spacing:.08em;text-transform:uppercase;fill:var(--d-text-3)">What grows on every turn</text>
    ${growthSvg}

    <!-- Levers strip header -->
    <text x="${VBW/2}" y="${leverY - 14}" text-anchor="middle"
          style="font:600 11px Inter,sans-serif;letter-spacing:.06em;text-transform:uppercase;fill:${leverColor}">Levers to add for long sessions</text>
    ${leverSvg}
  </svg>`;
};

/* ============================================================
   Registry + Renderer
   ============================================================ */
const DIAGRAMS = {
  'system-overview':       SYSTEM_OVERVIEW,
  'cascade-pipeline':      CASCADE_PIPELINE,
  'voicelive-pipeline':    VOICELIVE_PIPELINE,
  'production-ref':        PRODUCTION_REF,
  'cross-cloud':           CROSS_CLOUD,
  'omnichannel-hero':      OMNICHANNEL_HERO,
  'framework-positioning': FRAMEWORK_POSITIONING,
  'turn-latency-budget':   TURN_LATENCY_BUDGET,
  'barge-in-flow':         BARGE_IN_FLOW,
  'session-isolation':     SESSION_ISOLATION,
  'memory-lifecycle':      MEMORY_LIFECYCLE,
  'turn-hooks-compare':    TURN_HOOKS_COMPARE,
  'memory-per-turn':       MEMORY_PER_TURN,
};

function renderDiagrams() {
  document.querySelectorAll('[data-diagram]').forEach(el => {
    const name = el.getAttribute('data-diagram');
    const builder = DIAGRAMS[name];
    if (!builder) return;
    // Wrap SVG; preserve any <figcaption> child
    const caption = el.querySelector('.az-diagram-caption');
    el.innerHTML = builder() + (caption ? caption.outerHTML : '');
  });
}

document.addEventListener('DOMContentLoaded', renderDiagrams);
// Re-render on theme toggle so colors update if any are theme-dependent at render time
document.addEventListener('art-theme-changed', renderDiagrams);
