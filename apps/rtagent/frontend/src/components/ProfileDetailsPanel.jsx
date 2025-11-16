import React, { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import {
  Avatar,
  Box,
  Chip,
  Divider,
  Typography,
} from '@mui/material';
import IconButton from '@mui/material/IconButton';
import CloseRoundedIcon from '@mui/icons-material/CloseRounded';

const currencyFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 0,
  maximumFractionDigits: 0,
});

const currencyWithCentsFormatter = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'USD',
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

const formatCurrency = (value) => {
  if (value === null || value === undefined) return '—';
  try {
    return currencyFormatter.format(value);
  } catch {
    return value;
  }
};

const formatCurrencyWithCents = (value) => {
  if (value === null || value === undefined) return '—';
  try {
    return currencyWithCentsFormatter.format(value);
  } catch {
    return value;
  }
};

const formatNumber = (value) => {
  if (value === null || value === undefined) return '—';
  return value.toString();
};

const formatDate = (dateStr) => {
  if (!dateStr) return '—';
  try {
    return new Date(dateStr).toLocaleDateString();
  } catch {
    return '—';
  }
};

const formatDateTime = (value) => {
  if (!value) return '—';
  try {
    return new Date(value).toLocaleString(undefined, {
      dateStyle: 'medium',
      timeStyle: 'short',
    });
  } catch {
    return '—';
  }
};

const toTitleCase = (value) => {
  if (!value) return '—';
  return value
    .toString()
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
};

const maskSecretValue = (value) => {
  if (!value) return '—';
  if (value.length <= 6) {
    return '••••••';
  }
  const prefix = value.slice(0, 3);
  const suffix = value.slice(-2);
  return `${prefix}••••••${suffix}`;
};

const TAB_META = {
  verification: { icon: '🛡️', accent: '#6366f1' },
  identity: { icon: '🪪', accent: '#0ea5e9' },
  contact: { icon: '☎️', accent: '#10b981' },
  intelligence: { icon: '📈', accent: '#f59e0b' },
  transactions: { icon: '💳', accent: '#6366f1' },
};

const SectionCard = ({ children, sx = {} }) => (
  <Box
    sx={{
      borderRadius: '18px',
      border: '1px solid rgba(226,232,240,0.9)',
      background: 'linear-gradient(135deg, rgba(248,250,252,0.95), rgba(255,255,255,0.9))',
      boxShadow: '0 6px 18px rgba(15,23,42,0.08)',
      padding: '18px 20px',
      ...sx,
    }}
  >
    {children}
  </Box>
);

const SummaryStat = ({ label, value, icon, tooltip }) => (
  <Box
    component="span"
    title={tooltip || label}
    sx={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: '6px',
      padding: '4px 10px',
      borderRadius: '999px',
      backgroundColor: 'rgba(255,255,255,0.85)',
      border: '1px solid rgba(226,232,240,0.8)',
      fontSize: '11px',
      fontWeight: 600,
      color: '#0f172a',
      cursor: tooltip ? 'help' : 'default',
    }}
  >
    {icon && <span style={{ fontSize: '12px' }}>{icon}</span>}
    <span>{value || '—'}</span>
  </Box>
);

const resolveRelationshipTier = (profileData) => (
  profileData?.relationship_tier
  || profileData?.customer_intelligence?.relationship_context?.relationship_tier
  || profileData?.customer_intelligence?.relationship_context?.tier
  || '—'
);

const getInitials = (name) => {
  if (!name) return 'U';
  return name.split(' ').map((n) => n[0]).join('').toUpperCase().slice(0, 2);
};

const getTierColor = (tier) => {
  switch (tier?.toLowerCase()) {
    case 'platinum':
      return '#e5e7eb';
    case 'gold':
      return '#fbbf24';
    case 'silver':
      return '#9ca3af';
    case 'bronze':
      return '#d97706';
    default:
      return '#6b7280';
  }
};

const SectionTitle = ({ icon, children }) => (
  <Typography sx={{
    fontSize: '11px',
    fontWeight: 700,
    color: '#475569',
    textTransform: 'uppercase',
    letterSpacing: '0.6px',
    mb: 1.5,
    display: 'flex',
    alignItems: 'center',
    gap: 1,
  }}>
    {icon && <span>{icon}</span>}
    {children}
  </Typography>
);

const ProfileDetailRow = ({ icon, label, value, multiline = false }) => (
  <Box sx={{
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '6px 0',
    minHeight: '24px',
  }}>
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      {icon && <Box sx={{ color: '#64748b', fontSize: '14px' }}>{icon}</Box>}
      <Typography sx={{
        fontWeight: 600,
        color: '#64748b',
        fontSize: '11px',
        textTransform: 'uppercase',
        letterSpacing: '0.5px',
      }}>
        {label}
      </Typography>
    </Box>
    <Typography sx={{
      fontWeight: 500,
      color: '#1f2937',
      fontSize: '12px',
      textAlign: 'right',
      maxWidth: '220px',
      overflow: multiline ? 'visible' : 'hidden',
      textOverflow: multiline ? 'unset' : 'ellipsis',
      whiteSpace: multiline ? 'normal' : 'nowrap',
    }}>
      {value || '—'}
    </Typography>
  </Box>
);

const ProfileDetailsPanel = ({ profile, sessionId, open, onClose }) => {
  const [renderContent, setRenderContent] = useState(false);
  const [activeTab, setActiveTab] = useState('verification');
  const contentRef = useRef(null);

  useEffect(() => {
    if (open) {
      setRenderContent(true);
      return undefined;
    }
    const timeout = window.setTimeout(() => {
      setRenderContent(false);
    }, 200);
    return () => window.clearTimeout(timeout);
  }, [open]);

  const baseProfile = profile ?? {};
  const profilePayload = baseProfile.profile ?? null;
  const data = profilePayload ?? {};
  const hasProfile = Boolean(profilePayload);
  const tier = resolveRelationshipTier(data);
  const ssnLast4 = data?.verification_codes?.ssn4 || '----';
  const verificationCodes = data?.verification_codes ?? {};
  const institutionName = data?.institution_name || 'Demo Institution';
  const companyCode = data?.company_code;
  const companyCodeLast4 = data?.company_code_last4 || companyCode?.slice?.(-4) || '----';
  const demoMeta = data?.demo_metadata ?? baseProfile.demo_metadata ?? {};
  const transactions = (Array.isArray(baseProfile.transactions) && baseProfile.transactions.length
      ? baseProfile.transactions
      : Array.isArray(demoMeta.transactions)
        ? demoMeta.transactions
        : []) ?? [];
  const interactionPlan = baseProfile.interactionPlan
    ?? demoMeta.interaction_plan
    ?? data?.interaction_plan
    ?? null;
  const entryId = baseProfile.entryId ?? demoMeta.entry_id ?? demoMeta.entryId;
  const expiresAt = baseProfile.expiresAt ?? baseProfile.expires_at ?? demoMeta.expires_at;
  const compliance = data?.compliance ?? {};
  const mfaSettings = data?.mfa_settings ?? {};
  const customerIntel = data?.customer_intelligence ?? {};
  const relationshipContext = customerIntel.relationship_context ?? {};
  const accountStatus = customerIntel.account_status ?? {};
  const spendingPatterns = customerIntel.spending_patterns ?? {};
  const memoryScore = customerIntel.memory_score ?? {};
  const fraudContext = customerIntel.fraud_context ?? {};
  const conversationContext = customerIntel.conversation_context ?? {};
  const activeAlerts = customerIntel.active_alerts ?? [];
  const knownPreferences = conversationContext.known_preferences ?? [];
  const suggestedTalkingPoints = conversationContext.suggested_talking_points ?? [];

  const typicalBehavior = fraudContext.typical_transaction_behavior ?? {};
  const sessionDisplayId = baseProfile.sessionId ?? sessionId;
  const profileId = data?._id ?? data?.id ?? data?.client_id ?? baseProfile.sessionId;
  const createdAt = data?.created_at ?? data?.createdAt;
  const updatedAt = data?.updated_at ?? data?.updatedAt;
  const topLevelLastLogin = data?.last_login ?? data?.lastLogin;
  const loginAttempts = data?.login_attempts ?? data?.loginAttempts;
  const ttlValue = data?.ttl ?? data?.TTL;
  const recordExpiresAt = data?.expires_at ?? data?.expiresAt ?? expiresAt;
  const safetyNotice = baseProfile.safetyNotice ?? demoMeta.safety_notice;
  const profileIdentityKey = `${profileId ?? ''}-${sessionDisplayId ?? ''}`;

  useEffect(() => {
    setActiveTab('verification');
  }, [profileIdentityKey]);

  const tabs = useMemo(
    () => [
      {
        id: 'verification',
        label: 'Verification',
        content: (
          <>
            <SectionCard>
              <SectionTitle icon="🛡️">Verification Tokens</SectionTitle>
              <ProfileDetailRow label="SSN Last 4" value={ssnLast4} />
              <ProfileDetailRow label="Institution" value={institutionName} />
              <ProfileDetailRow label="Employee ID Last 4" value={verificationCodes.employee_id4 || '----'} />
              <ProfileDetailRow label="Phone Last 4" value={verificationCodes.phone4 || '----'} />
              <ProfileDetailRow label="Company Code Last 4" value={companyCodeLast4} />
            </SectionCard>

            {mfaSettings && (
              <SectionCard sx={{ mt: 2 }}>
                <SectionTitle icon="🔐">MFA Settings</SectionTitle>
                <ProfileDetailRow label="Enabled" value={mfaSettings.enabled ? 'Yes' : 'No'} />
                <ProfileDetailRow label="Preferred Method" value={data?.contact_info?.preferred_mfa_method ?? '—'} />
                <ProfileDetailRow label="Secret Key" value={maskSecretValue(mfaSettings.secret_key)} multiline />
                <ProfileDetailRow label="Code Expiry (min)" value={mfaSettings.code_expiry_minutes} />
                <ProfileDetailRow label="Max Attempts" value={mfaSettings.max_attempts} />
              </SectionCard>
            )}
          </>
        ),
      },
      {
        id: 'identity',
        label: 'Identity',
        content: (
          <>
            <SectionCard>
              <SectionTitle icon="🪪">Identity Snapshot</SectionTitle>
              <ProfileDetailRow label="Profile ID" value={profileId} />
              <ProfileDetailRow label="Client ID" value={data?.client_id} />
              <ProfileDetailRow label="Company Code" value={data?.company_code} />
              <ProfileDetailRow label="Client Type" value={toTitleCase(data?.client_type)} />
              <ProfileDetailRow label="Authorization Level" value={toTitleCase(data?.authorization_level)} />
              <ProfileDetailRow label="Max Transaction Limit" value={formatCurrency(data?.max_transaction_limit)} />
              <ProfileDetailRow label="MFA Threshold" value={formatCurrency(data?.mfa_required_threshold)} />
              <ProfileDetailRow label="Demo Entry" value={entryId} />
              <ProfileDetailRow label="Demo Expiry" value={formatDateTime(expiresAt)} />
              <ProfileDetailRow label="Session" value={sessionDisplayId} multiline />
            </SectionCard>

            <SectionCard sx={{ mt: 2 }}>
              <SectionTitle icon="⚖️">Compliance</SectionTitle>
              <ProfileDetailRow label="KYC Verified" value={compliance.kyc_verified ? 'Yes' : 'No'} />
              <ProfileDetailRow label="AML Cleared" value={compliance.aml_cleared ? 'Yes' : 'No'} />
              <ProfileDetailRow label="Last Review" value={formatDate(compliance.last_review_date)} />
              <ProfileDetailRow label="Risk Rating" value={toTitleCase(compliance.risk_rating)} />
            </SectionCard>

            <SectionCard sx={{ mt: 2 }}>
              <SectionTitle icon="📂">Record Metadata</SectionTitle>
              <ProfileDetailRow label="Created" value={formatDateTime(createdAt)} />
              <ProfileDetailRow label="Updated" value={formatDateTime(updatedAt)} />
              <ProfileDetailRow label="Last Login" value={formatDateTime(topLevelLastLogin)} />
              <ProfileDetailRow label="Login Attempts" value={formatNumber(loginAttempts)} />
              <ProfileDetailRow label="TTL (s)" value={formatNumber(ttlValue)} />
              <ProfileDetailRow label="Record Expires" value={formatDateTime(recordExpiresAt)} />
            </SectionCard>
          </>
        ),
      },
      {
        id: 'contact',
        label: 'Contact',
        content: (
          <>
            <SectionCard>
              <SectionTitle icon="📞">Contact</SectionTitle>
              <ProfileDetailRow label="Email" value={data?.contact_info?.email} multiline />
              <ProfileDetailRow label="Phone" value={data?.contact_info?.phone} />
              <ProfileDetailRow label="Preferred MFA Method" value={toTitleCase(data?.contact_info?.preferred_mfa_method)} />
            </SectionCard>

            {interactionPlan && (
              <SectionCard sx={{ mt: 2 }}>
                <SectionTitle icon="🗓️">Interaction Plan</SectionTitle>
                <ProfileDetailRow label="Primary Channel" value={toTitleCase(interactionPlan.primary_channel)} />
                <ProfileDetailRow label="Fallback Channel" value={toTitleCase(interactionPlan.fallback_channel)} />
                <ProfileDetailRow label="MFA Required" value={interactionPlan.mfa_required ? 'Yes' : 'No'} />
                <ProfileDetailRow label="Notification" value={interactionPlan.notification_message} multiline />
              </SectionCard>
            )}
          </>
        ),
      },
      {
        id: 'intelligence',
        label: 'Intelligence',
        content: (
          <>
            <SectionCard>
              <SectionTitle icon="💼">Relationship Context</SectionTitle>
              <ProfileDetailRow label="Tier" value={toTitleCase(relationshipContext.relationship_tier)} />
              <ProfileDetailRow label="Client Since" value={formatDate(relationshipContext.client_since)} />
              <ProfileDetailRow label="Lifetime Value" value={formatCurrency(relationshipContext.lifetime_value)} />
              <ProfileDetailRow label="Duration (yrs)" value={relationshipContext.relationship_duration_years} />
              <ProfileDetailRow label="Satisfaction" value={relationshipContext.satisfaction_score} />
              <ProfileDetailRow label="Previous Interactions" value={relationshipContext.previous_interactions} />
            </SectionCard>

            <SectionCard sx={{ mt: 2 }}>
              <SectionTitle icon="📊">Account Status</SectionTitle>
              <ProfileDetailRow label="Current Balance" value={formatCurrency(accountStatus.current_balance)} />
              <ProfileDetailRow label="YTD Volume" value={formatCurrency(accountStatus.ytd_transaction_volume)} />
              <ProfileDetailRow label="Account Health" value={accountStatus.account_health_score} />
              <ProfileDetailRow label="Login Frequency" value={toTitleCase(accountStatus.login_frequency)} />
              <ProfileDetailRow label="Last Login" value={formatDate(accountStatus.last_login)} />
            </SectionCard>

            <SectionCard sx={{ mt: 2 }}>
              <SectionTitle icon="📈">Spending Patterns</SectionTitle>
              <ProfileDetailRow label="Avg Monthly Spend" value={formatCurrency(spendingPatterns.avg_monthly_spend)} />
              <ProfileDetailRow label="Preferred Times" value={(spendingPatterns.preferred_transaction_times || []).join(', ') || '—'} multiline />
              <ProfileDetailRow label="Usual Range" value={spendingPatterns.usual_spending_range || '—'} />
              <ProfileDetailRow label="Common Merchants" value={(spendingPatterns.common_merchants || []).join(', ') || '—'} multiline />
              <ProfileDetailRow label="Risk Tolerance" value={toTitleCase(spendingPatterns.risk_tolerance)} />
            </SectionCard>

            <SectionCard sx={{ mt: 2 }}>
              <SectionTitle icon="🧠">Memory Profile</SectionTitle>
              <ProfileDetailRow label="Communication Style" value={memoryScore.communication_style} />
              <ProfileDetailRow label="Preferred Resolution" value={memoryScore.preferred_resolution_style} />
              <ProfileDetailRow label="Personality Traits" value={Object.entries(memoryScore.personality_traits || {}).map(([key, value]) => `${toTitleCase(key)}: ${value}`).join(' • ') || '—'} multiline />
            </SectionCard>

            <SectionCard sx={{ mt: 2 }}>
              <SectionTitle icon="🛡️">Fraud Context</SectionTitle>
              <ProfileDetailRow label="Risk Profile" value={fraudContext.risk_profile} />
              <ProfileDetailRow label="Preferred Verification" value={fraudContext.security_preferences?.preferred_verification} />
              <ProfileDetailRow label="Notification Urgency" value={fraudContext.security_preferences?.notification_urgency} />
              <ProfileDetailRow label="Replacement Speed" value={fraudContext.security_preferences?.card_replacement_speed} />
              <ProfileDetailRow label="Previous Cases" value={fraudContext.fraud_history?.previous_cases} />
              <ProfileDetailRow label="False Positive Rate" value={fraudContext.fraud_history?.false_positive_rate} />

              {(typicalBehavior.usual_spending_range
                || (typicalBehavior.common_locations || []).length
                || (typicalBehavior.typical_merchants || []).length) && (
                <Box sx={{ mt: 1.5 }}>
                  <SectionTitle icon="🗺️">Typical Behavior</SectionTitle>
                  <ProfileDetailRow label="Usual Range" value={typicalBehavior.usual_spending_range} />
                  <ProfileDetailRow label="Locations" value={(typicalBehavior.common_locations || []).join(', ') || '—'} multiline />
                  <ProfileDetailRow label="Merchants" value={(typicalBehavior.typical_merchants || []).join(', ') || '—'} multiline />
                </Box>
              )}
            </SectionCard>

            <SectionCard sx={{ mt: 2 }}>
              <SectionTitle icon="💬">Conversation Context</SectionTitle>
              <ProfileDetailRow label="Known Preferences" value={knownPreferences.join(' • ') || '—'} multiline />
              <ProfileDetailRow label="Talking Points" value={suggestedTalkingPoints.join(' • ') || '—'} multiline />

              {!!activeAlerts.length && (
                <Box sx={{ mt: 1.5 }}>
                  <SectionTitle icon="🚨">Active Alerts</SectionTitle>
                  {activeAlerts.map((alert) => (
                    <ProfileDetailRow key={alert.message} label={toTitleCase(alert.type)} value={`${alert.message} (${alert.priority})`} multiline />
                  ))}
                </Box>
              )}
            </SectionCard>
          </>
        ),
      },
      {
        id: 'transactions',
        label: 'Transactions',
        content: (
          <>
            <SectionCard>
              <SectionTitle icon="💳">Recent Transactions</SectionTitle>
              {transactions.length ? (
                <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                  {transactions.map((txn) => (
                    <Box
                      key={txn.transaction_id}
                      sx={{
                        border: '1px solid rgba(226,232,240,0.9)',
                        borderRadius: '14px',
                        padding: '12px 14px',
                        backgroundColor: '#fff',
                        boxShadow: '0 6px 16px rgba(15,23,42,0.08)',
                      }}
                    >
                      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                        <Typography sx={{ fontWeight: 700, color: '#0f172a', fontSize: '13px' }}>
                          {txn.merchant}
                        </Typography>
                        <Typography sx={{ fontWeight: 700, color: '#111827', fontSize: '12px' }}>
                          {formatCurrencyWithCents(txn.amount)}
                        </Typography>
                      </Box>
                      <Typography sx={{ color: '#64748b', fontSize: '11px' }}>
                        {formatDateTime(txn.timestamp)} • {toTitleCase(txn.category)}
                      </Typography>
                      <Typography sx={{ color: '#0ea5e9', fontSize: '10px', fontWeight: 700, mt: 0.5 }}>
                        Risk Score: {txn.risk_score}
                      </Typography>
                    </Box>
                  ))}
                </Box>
              ) : (
                <Typography sx={{ fontSize: '11px', color: '#94a3b8' }}>
                  No transactions available for this profile yet.
                </Typography>
              )}
            </SectionCard>
          </>
        ),
      },
    ],
    [
      accountStatus,
      activeAlerts,
      compliance,
      conversationContext,
      createdAt,
      data,
      entryId,
      expiresAt,
      fraudContext,
      interactionPlan,
      knownPreferences,
      loginAttempts,
      memoryScore,
      mfaSettings,
      profileId,
      recordExpiresAt,
      relationshipContext,
      sessionDisplayId,
      spendingPatterns,
      suggestedTalkingPoints,
      topLevelLastLogin,
      transactions,
      typicalBehavior,
      ttlValue,
      updatedAt,
      verificationCodes,
    ],
  );

  const activeTabContent = tabs.find((tab) => tab.id === activeTab)?.content;

  if (!hasProfile) {
    return null;
  }

  const panel = (
    <Box
      sx={{
        position: 'fixed',
        top: '20px',
        right: '20px',
        width: '360px',
        height: 'calc(100vh - 40px)',
        maxHeight: 'calc(100vh - 40px)',
        backgroundColor: '#fff',
        borderRadius: '20px',
        boxShadow: '0 20px 60px rgba(15,15,30,0.45)',
        zIndex: 11000,
        transform: open ? 'translateY(0)' : 'translateY(12px)',
        opacity: open ? 1 : 0,
        pointerEvents: open ? 'auto' : 'none',
        transition: 'opacity 0.25s ease, transform 0.25s ease',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
      }}
    >
        {renderContent && (
          <>
            <Box sx={{
              padding: '18px',
              background: 'linear-gradient(150deg, #eef2ff 0%, rgba(238,242,255,0.75) 50%, #f8fafc 100%)',
              borderBottom: '1px solid #e2e8f0',
              position: 'relative',
              overflow: 'hidden',
            }}>
              <Box
                sx={{
                  position: 'absolute',
                  inset: 0,
                  background: 'radial-gradient(circle at top right, rgba(99,102,241,0.25), transparent 45%)',
                  pointerEvents: 'none',
                }}
              />
              <Box sx={{ position: 'relative', zIndex: 1 }}>
                <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.2 }}>
                    <Typography variant="h6" sx={{ fontSize: '18px', fontWeight: 800, color: '#0f172a', letterSpacing: '-0.02em' }}>
                      Profile Details
                    </Typography>
                    {expiresAt && (
                      <SummaryStat
                        label="Expiration"
                        value={formatDateTime(expiresAt)}
                        icon="⏱️"
                        tooltip={`Expiration time in ${Intl.DateTimeFormat().resolvedOptions().timeZone}`}
                      />
                    )}
                  </Box>
                  <IconButton
                    size="small"
                    aria-label="Close profile details"
                    onClick={onClose}
                    sx={{
                      color: '#0f172a',
                      backgroundColor: 'rgba(255,255,255,0.9)',
                      border: '1px solid rgba(148,163,184,0.4)',
                      '&:hover': {
                        backgroundColor: '#fff',
                      },
                    }}
                  >
                    <CloseRoundedIcon fontSize="small" />
                  </IconButton>
                </Box>

                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.5 }}>
                  <Avatar
                    sx={{
                      width: 48,
                      height: 48,
                      bgcolor: getTierColor(tier),
                      color: tier?.toLowerCase() === 'platinum' ? '#1f2937' : '#fff',
                      fontSize: '18px',
                      fontWeight: 700,
                      boxShadow: '0 10px 20px rgba(15,23,42,0.15)',
                    }}
                  >
                    {getInitials(data?.full_name)}
                  </Avatar>
                  <Box sx={{ flex: 1 }}>
                  <Typography variant="h6" sx={{ fontSize: '16px', fontWeight: 800, color: '#0f172a', lineHeight: 1.1 }}>
                    {data?.full_name || 'Demo User'}
                  </Typography>
                  {data?.contact_info?.email && (
                    <Typography sx={{ fontSize: '11px', color: '#475569', fontWeight: 600 }}>
                      {data.contact_info.email}
                    </Typography>
                  )}
                    <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 0.8, mt: 1 }}>
                      <Chip
                        label={tier}
                        size="small"
                        sx={{
                          backgroundColor: getTierColor(tier),
                          color: tier?.toLowerCase() === 'platinum' ? '#1f2937' : '#111827',
                          fontSize: '10px',
                          fontWeight: 700,
                          height: '22px',
                        }}
                      />
                      {ssnLast4 && (
                        <Chip
                          label={`SSN · ***${ssnLast4}`}
                          size="small"
                          sx={{
                            backgroundColor: 'rgba(59,130,246,0.15)',
                            color: '#1d4ed8',
                            fontSize: '10px',
                            fontWeight: 700,
                            height: '22px',
                          }}
                        />
                      )}
                      {institutionName && (
                        <Chip
                          label={
                            companyCodeLast4
                              ? `${institutionName} · Co ***${companyCodeLast4}`
                              : institutionName
                          }
                          size="small"
                          sx={{
                            backgroundColor: 'rgba(15,118,110,0.12)',
                            color: '#0f766e',
                            fontSize: '10px',
                            fontWeight: 700,
                            height: '22px',
                          }}
                        />
                      )}
                    </Box>
                  </Box>
                </Box>

              </Box>
            </Box>

            <Box
              sx={{
                padding: '12px 20px 10px',
                borderBottom: '1px solid #e2e8f0',
                background: 'linear-gradient(135deg, rgba(248,250,252,0.95), rgba(238,242,255,0.9))',
              }}
            >
              <Box
                sx={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))',
                  gap: '10px',
                }}
              >
                {tabs.map((tab) => {
                  const isActive = activeTab === tab.id;
                  const { icon = '•', accent = '#6366f1' } = TAB_META[tab.id] || {};
                  return (
                    <Box
                      key={tab.id}
                      component="button"
                      type="button"
                      onClick={() => setActiveTab(tab.id)}
                      sx={{
                        border: '1px solid',
                        borderColor: isActive ? `${accent}66` : 'rgba(148,163,184,0.4)',
                        borderRadius: '14px',
                        background: isActive
                          ? `linear-gradient(135deg, ${accent}, ${accent}dd)`
                          : 'rgba(148,163,184,0.15)',
                        color: isActive ? '#fff' : '#0f172a',
                        fontSize: '11px',
                        fontWeight: 600,
                        letterSpacing: '0.04em',
                        padding: '8px 12px',
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        cursor: 'pointer',
                        boxShadow: isActive
                          ? `0 10px 18px ${accent}33`
                          : 'inset 0 1px 0 rgba(255,255,255,0.6)',
                        transition: 'transform 0.2s ease, box-shadow 0.2s ease',
                        textTransform: 'uppercase',
                        backgroundSize: '200% 200%',
                        '&:hover': {
                          transform: 'translateY(-1px)',
                          boxShadow: isActive
                            ? `0 14px 24px ${accent}55`
                            : '0 6px 12px rgba(15,23,42,0.15)',
                        },
                      }}
                    >
                      <Box component="span" sx={{ fontSize: '13px' }}>
                        {icon}
                      </Box>
                      {tab.label}
                    </Box>
                  );
                })}
              </Box>
            </Box>

            <Box
              ref={contentRef}
              sx={{
                flex: 1,
                padding: '20px',
                overflowY: 'auto',
                overscrollBehavior: 'contain',
                scrollBehavior: 'smooth',
                WebkitOverflowScrolling: 'touch',
                display: 'flex',
                flexDirection: 'column',
                gap: 2.5,
              }}
            >
              {activeTabContent}
              {safetyNotice && (
                <Box
                  sx={{
                    marginTop: '8px',
                    padding: '12px 16px',
                    borderRadius: '8px',
                    background: '#fef2f2',
                    border: '1px solid #fecaca',
                    color: '#b91c1c',
                    fontSize: '11px',
                    fontWeight: 600,
                    textAlign: 'center',
                  }}
                >
                  {safetyNotice}
                </Box>
              )}
            </Box>
          </>
        )}
      </Box>
    );

  return createPortal(panel, document.body);
};

export default ProfileDetailsPanel;
