import React, { useState } from 'react';

const DEFAULT_SCENARIOS = [
  {
    title: 'Venmo Support RAG Research',
    focus: 'Stress-test Venmo knowledge base retrieval from https://help.venmo.com/cs/home',
    steps: [
      'Ask for the Venmo-entry agent and immediately request Purchase Protection requirements for sellers.',
      'Follow up with: "If I use Instant Transfer for $2,000 today, what fee does Venmo list?"',
      'Ask for debit-card ATM limits, then request citation links so you can verify the answer.',
      'Wrap up by having the agent read the exact Venmo help article title/URL to prove grounding.',
    ],
  },
  {
    title: 'Report Venmo Fraud & Trigger MFA',
    focus: 'Run the fraud identity tool plus MFA before handing to the fraud specialist',
    steps: [
      'Start with "Route me to Venmo support—I need to report fraud."',
      'Provide full name + SSN last four when asked; let the auth agent verify with `verify_fraud_client_identity`.',
      'When prompted, approve the MFA email and respond with a code like 184512 to finish verification.',
      'Request a freeze on Venmo balance, have risky merchants flagged, then let the agent warm-transfer to Fraud.',
    ],
  },
  {
    title: 'PayPal Payout Hold + Venmo Follow-up',
    focus: 'Authenticate once, then chain PayPal and Venmo actions without losing context',
    steps: [
      'Open with "My PayPal payout is on hold and I also have a Venmo limit question."',
      'Provide full name + PayPal company code last four; let the auth agent verify and send email MFA.',
      'Have the agent hand off to PayPal support, release the payout, then immediately redirect to Venmo for the second request.',
      'Ask the Venmo agent to confirm the verified caller profile they received to prove context hand-off.',
    ],
  },
  {
    title: 'Venmo Balance & Transactions',
    focus: 'Showcase Venmo-specific account lookups after identity verification',
    steps: [
      'Say "I’d like to know my Venmo balance and my last five transactions."',
      'Provide full name + Venmo security code last four so the agent can verify identity and send MFA.',
      'After the Venmo agent reads back the balance, follow with "List my five most recent Venmo payments."',
      'Ask for a proactive alert to be added if large transfers resume, demonstrating memory/actions.',
    ],
  },
  {
    title: 'Venmo Knowledge-Only Guidance',
    focus: 'Keep the call unauthenticated and grounded in the Venmo help center',
    steps: [
      'Open with "Without accessing my account, walk me through Venmo Purchase Protection."',
      'Ask for the exact Venmo policy citation and have the agent read the bullet list.',
      '"What does Venmo say about linked cards being declined?" forces another RAG pull.',
      'End by requesting a short checklist the user can try on their device before calling back.',
    ],
  },
  {
    title: 'PayPal Chargeback + Venmo Fraud',
    focus: 'Demonstrate multi-issue routing while staying in the PayPal/Venmo universe',
    steps: [
      'Start with "I have a PayPal chargeback notice and suspicious Venmo activity."',
      'Let the auth agent capture name + PayPal code and verify once.',
      'Hand off to the PayPal specialist for the dispute, then request a warm handoff to the Venmo agent for fraud mitigation.',
      'Ask the Venmo specialist to file a fraud case and coordinate with the PayPal team for cross-brand awareness.',
    ],
  },
  {
    title: 'Venmo Fraud Escalation with Self-Service Option',
    focus: 'Show how the PayPal/Venmo agent handles fraud when the caller declines a live transfer',
    steps: [
      'Say "I saw a Venmo transfer I didn’t approve but I don’t want a live agent yet."',
      'Allow the agent to verify identity but decline the Fraud Agent transfer when offered.',
      'Listen to the self-service mitigation steps pulled from the Venmo KB (grounded summary).',
      'Finally ask to escalate after all, proving the agent can do both self-service and handoff paths cleanly.',
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
