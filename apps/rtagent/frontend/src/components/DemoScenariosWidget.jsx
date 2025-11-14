import React, { useState } from 'react';

const DEFAULT_SCENARIOS = [
  {
    title: 'Venmo Support RAG Research',
    focus: 'Stress-test knowledge base retrieval from https://help.venmo.com/cs/home',
    steps: [
      'Ask the agent to summarize what Venmo Purchase Protection covers for sellers according to the help center.',
      'Follow up with a question about Instant Transfer fees (e.g., "If I move $2,000 today, what fee does Venmo list?").',
      'Request the Venmo help guidance on debit card ATM limits and have the agent read back the key numbers.',
      'Close the loop by asking for citation links so you can verify RAG grounding.',
    ],
  },
  {
    title: 'Report Venmo Fraud & Trigger MFA',
    focus: 'Exercise the verify_fraud_client_identity -> MFA tooling before handoff',
    steps: [
      'Begin with "I need to report fraud on my Venmo account" to route into the fraud track.',
      'Provide profile details (full name, DOB, SSN4) when the agent asks for verification.',
      'When prompted, approve sending the MFA code, then respond with a code like 184512 to finish the check.',
      'Ask the agent to freeze the Venmo balance, flag risky merchants, and warm-transfer to the Fraud Agent for deeper review.',
    ],
  },
  {
    title: 'Full Venmo Account Review (RAG + MFA + Lookups)',
    focus: 'Switch to the Venmo agent, cite help content, then request sensitive data',
    steps: [
      'Ask "Can you connect me with the Venmo agent?" if the call did not already start there.',
      'Pose a RAG question: "What does the Venmo help article say about linked cards being declined?"',
      'Next, request "How much is in my Venmo balance right now?" so the agent has to verify identity with MFA.',
      'After passing MFA, ask for "my most recent transactions" or "any Venmo Credit Card payments pending."',
      'Wrap up by requesting a proactive alert if large transfers resume, showcasing multi-turn memory.',
    ],
  },
  {
    title: 'Fraud Agent Card Freeze',
    focus: 'Use apps/rtagent/backend/src/agents/vlagent/agents/fraud.yaml tooling to block cards',
    steps: [
      'After Venmo alerts you to odd charges, say "Route me to the fraud agent so we can freeze my card."',
      'Share transaction IDs or merchants that look suspicious and let the Fraud Agent summarize anomalies.',
      'Authorize a temporary card block plus reissuance; confirm the agent records case notes and risk score.',
      'Ask for downstream coordination with Compliance so the block reason is documented for regulators.',
    ],
  },
  {
    title: 'Authentication Agent Gatekeeper',
    focus: 'Hit auth.yaml to validate identities before handoffs',
    steps: [
      'Say "Before we proceed, I want to pass through the authentication agent."',
      'Provide multi-factor evidence (email, last 4 SSN, employee ID) and confirm the agent checks `verify_client_identity`.',
      'Once cleared, request a handoff to the Venmo or Fraud agent and observe how the profile context carries forward.',
      'Ask the receiving agent to repeat the verified identity details to prove context sync.',
    ],
  },
  {
    title: 'Compliance Review + RAG Citations',
    focus: 'Exercise compliance.yaml prompts with knowledge grounding',
    steps: [
      'Request "Connect me with the compliance agent to review my call notes."',
      'Ask for an outline of required disclosures for DRIP liquidations or ACH disputes and listen for citations.',
      'Challenge the agent with "Where in the policy library did you pull that guidance?" to test RAG metadata.',
      'Finish by asking for a summary email that documents risk controls applied during the call.',
    ],
  },
  {
    title: 'Transfer Agency & Escrow Flow',
    focus: 'Use transfer.yaml to coordinate payouts after identity checks',
    steps: [
      'Start with the authentication agent to capture SSN4 + MFA, then say "Transfer me to the transfer agency specialist."',
      'Ask about pending DRIP payouts or escrow disbursements; request a breakdown by beneficiary.',
      'Initiate a change request (e.g., "move today’s payment to my brokerage account") and confirm dual-control steps.',
      'Have the agent escalate to Compliance if the transaction exceeds limits, demonstrating multi-agent orchestration.',
    ],
  },
];

const styles = {
  container: {
    position: 'fixed',
    bottom: '32px',
    right: '32px',
    zIndex: 11000,
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-end',
    pointerEvents: 'none',
  },
  toggleButton: (open) => ({
    pointerEvents: 'auto',
    border: 'none',
    outline: 'none',
    borderRadius: '999px',
    background: open
      ? 'linear-gradient(135deg, #312e81, #1d4ed8)'
      : 'linear-gradient(135deg, #0f172a, #1f2937)',
    color: '#fff',
    padding: '10px 16px',
    fontWeight: 600,
    fontSize: '13px',
    letterSpacing: '0.4px',
    cursor: 'pointer',
    boxShadow: '0 12px 32px rgba(15, 23, 42, 0.35)',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    transition: 'transform 0.2s ease, box-shadow 0.2s ease',
  }),
  iconBadge: {
    width: '28px',
    height: '28px',
    borderRadius: '50%',
    background: 'rgba(255, 255, 255, 0.15)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: '16px',
  },
  panel: {
    pointerEvents: 'auto',
    width: '280px',
    maxWidth: 'calc(100vw - 48px)',
    maxHeight: '70vh',
    background: '#0f172a',
    color: '#f8fafc',
    borderRadius: '20px',
    padding: '20px',
    marginBottom: '12px',
    boxShadow: '0 20px 50px rgba(15, 23, 42, 0.55)',
    border: '1px solid rgba(255, 255, 255, 0.06)',
    backdropFilter: 'blur(16px)',
    transition: 'opacity 0.2s ease, transform 0.2s ease',
    overflowY: 'auto',
  },
  panelHidden: {
    opacity: 0,
    transform: 'translateY(10px)',
    pointerEvents: 'none',
  },
  panelVisible: {
    opacity: 1,
    transform: 'translateY(0)',
  },
  panelHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: '12px',
  },
  panelTitle: {
    fontSize: '14px',
    fontWeight: 700,
    letterSpacing: '0.8px',
    textTransform: 'uppercase',
  },
  closeButton: {
    border: 'none',
    background: 'rgba(255, 255, 255, 0.08)',
    color: '#cbd5f5',
    width: '28px',
    height: '28px',
    borderRadius: '50%',
    cursor: 'pointer',
    fontSize: '14px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
  },
  scenarioList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  scenarioCard: {
    background: 'rgba(15, 23, 42, 0.75)',
    borderRadius: '14px',
    padding: '14px',
    border: '1px solid rgba(255, 255, 255, 0.08)',
  },
  scenarioTitle: {
    fontSize: '13px',
    fontWeight: 700,
    marginBottom: '4px',
  },
  scenarioFocus: {
    fontSize: '11px',
    color: '#94a3b8',
    marginBottom: '10px',
  },
  scenarioSteps: {
    margin: 0,
    paddingLeft: '18px',
    color: '#cbd5f5',
    fontSize: '12px',
    lineHeight: 1.6,
  },
  scenarioStep: {
    marginBottom: '6px',
  },
  helperText: {
    fontSize: '11px',
    color: '#94a3b8',
    marginBottom: '12px',
  },
};

const DemoScenariosWidget = ({ scenarios = DEFAULT_SCENARIOS }) => {
  const [open, setOpen] = useState(false);

  const togglePanel = () => setOpen((prev) => !prev);

  return (
    <div style={styles.container} aria-live="polite">
      <div
        style={{
          ...styles.panel,
          ...(open ? styles.panelVisible : styles.panelHidden),
        }}
        role="dialog"
        aria-label="Demo script scenarios"
        aria-hidden={!open}
      >
        <div style={styles.panelHeader}>
          <div style={styles.panelTitle}>Demo Script Scenarios</div>
          <button
            type="button"
            style={styles.closeButton}
            aria-label="Hide demo script scenarios"
            onClick={togglePanel}
          >
            ×
          </button>
        </div>
        <div style={styles.helperText}>
          Use these sample prompts to showcase common workflows during the demo.
        </div>
        <div style={styles.scenarioList}>
          {scenarios.map((scenario) => (
            <div key={scenario.title} style={styles.scenarioCard}>
              <div style={styles.scenarioTitle}>{scenario.title}</div>
              {scenario.focus && <div style={styles.scenarioFocus}>{scenario.focus}</div>}
              <ol style={styles.scenarioSteps}>
                {(scenario.steps || []).map((step) => (
                  <li key={step} style={styles.scenarioStep}>
                    {step}
                  </li>
                ))}
              </ol>
            </div>
          ))}
        </div>
      </div>
      <button
        type="button"
        onClick={togglePanel}
        style={styles.toggleButton(open)}
        aria-expanded={open}
        aria-label="Toggle demo script scenarios"
      >
        <span style={styles.iconBadge}>🎬</span>
        <span>Scenarios</span>
      </button>
    </div>
  );
};

export default DemoScenariosWidget;
