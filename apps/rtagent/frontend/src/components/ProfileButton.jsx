import React, { useState } from 'react';
import {
  Avatar,
  Typography,
  Chip,
  Box,
  Divider,
} from '@mui/material';
import {
  Person as PersonIcon,
  Security as SecurityIcon,
  AccountBalance as AccountBalanceIcon,
  Schedule as ScheduleIcon,
} from '@mui/icons-material';

/* ------------------------------------------------------------------ *
 *  PROFILE DETAIL ROW COMPONENT
 * ------------------------------------------------------------------ */
const ProfileDetailRow = ({ icon, label, value, multiline = false }) => (
  <Box sx={{
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '6px 0',
    minHeight: '24px'
  }}>
    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
      {icon && <Box sx={{ color: '#64748b', fontSize: '14px' }}>{icon}</Box>}
      <Typography sx={{
        fontWeight: 600,
        color: '#64748b',
        fontSize: '11px',
        textTransform: 'uppercase',
        letterSpacing: '0.5px'
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
      whiteSpace: multiline ? 'normal' : 'nowrap'
    }}>
      {value || '—'}
    </Typography>
  </Box>
);

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
    gap: 1
  }}>
    {icon && <span>{icon}</span>}
    {children}
  </Typography>
);

/* ------------------------------------------------------------------ *
 *  PROFILE BUTTON COMPONENT WITH MATERIAL UI
 * ------------------------------------------------------------------ */
const ProfileButton = ({ profile, sessionId, onMenuClose, onCreateProfile }) => {
  const [panelOpen, setPanelOpen] = useState(false);

  const handleClick = () => {
    if (!profile) {
      // If no profile, trigger profile creation
      onCreateProfile?.();
      return;
    }
    setPanelOpen(!panelOpen);
  };

  const handlePanelClose = () => {
    setPanelOpen(false);
    onMenuClose?.();
  };

  // Utility functions
  const formatCurrency = (value) => {
    if (value === null || value === undefined) return '—';
    return new Intl.NumberFormat('en-US', { 
      style: 'currency', 
      currency: 'USD',
      minimumFractionDigits: 0,
      maximumFractionDigits: 0
    }).format(value);
  };

  const formatCurrencyWithCents = (value) => {
    if (value === null || value === undefined) return '—';
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD',
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
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

  const resolveRelationshipTier = (profileData) => {
    return (
      profileData?.relationship_tier ||
      profileData?.customer_intelligence?.relationship_context?.relationship_tier ||
      profileData?.customer_intelligence?.relationship_context?.tier ||
      '—'
    );
  };

  const getInitials = (name) => {
    if (!name) return 'U';
    return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0, 2);
  };

  const getTierColor = (tier) => {
    switch(tier?.toLowerCase()) {
      case 'platinum': return '#e5e7eb';
      case 'gold': return '#fbbf24';
      case 'silver': return '#9ca3af';
      case 'bronze': return '#d97706';
      default: return '#6b7280';
    }
  };

  // No profile state - show "New Demo Profile" button
  if (!profile) {
    return (
      <>
        <Box 
          onClick={handleClick}
          sx={{ 
            position: 'absolute',
            top: '56px', // Align with logged-in profile button
            right: '16px', // Align with logged-in profile button
            padding: '8px 16px',
            borderRadius: '18px',
            background: 'linear-gradient(135deg, rgba(99, 102, 241, 0.9) 0%, rgba(79, 70, 229, 0.95) 100%)',
            backdropFilter: 'blur(12px)',
            border: '1px solid rgba(255, 255, 255, 0.15)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            cursor: 'pointer',
            transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
            zIndex: 100,
            boxShadow: '0 4px 12px rgba(99, 102, 241, 0.3), 0 2px 6px rgba(0, 0, 0, 0.1)',
            '&:hover': {
              background: 'linear-gradient(135deg, rgba(99, 102, 241, 1) 0%, rgba(79, 70, 229, 1) 100%)',
              transform: 'translateY(-2px) scale(1.02)',
              boxShadow: '0 8px 20px rgba(99, 102, 241, 0.4), 0 4px 10px rgba(0, 0, 0, 0.15)',
              border: '1px solid rgba(255, 255, 255, 0.2)',
            },
            '&:active': {
              transform: 'translateY(-1px) scale(1.01)',
            }
          }}
        >
          <Typography sx={{ 
            fontSize: '11px', 
            fontWeight: 600, 
            color: '#fff',
            letterSpacing: '0.3px',
            textTransform: 'uppercase'
          }}>
            New Demo Profile
          </Typography>
        </Box>
      </>
    );
  }

  const profileData = profile.profile;
  if (!profileData) {
    return null;
  }
  const transactions = profile.transactions ?? [];
  const interactionPlan = profile.interactionPlan ?? null;
  const entryId = profile.entryId;
  const expiresAt = profile.expiresAt ?? profile.expires_at;
  const tier = resolveRelationshipTier(profileData);
  const ssnLast4 = profileData?.verification_codes?.ssn4 || '----';
  const verificationCodes = profileData?.verification_codes ?? {};
  const institutionName = profileData?.institution_name || 'Demo Institution';
  const companyCode = profileData?.company_code;
  const companyCodeLast4 = profileData?.company_code_last4 || companyCode?.slice?.(-4) || '----';

  return (
    <>
      {/* Compact Profile Button */}
      <Box 
        onClick={handleClick}
        sx={{ 
          position: 'absolute',
          top: '56px',
          right: '16px',
          display: 'flex',
          alignItems: 'center',
          gap: '6px',
          padding: '6px 10px',
          borderRadius: '20px',
          background: 'linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%)',
          border: '2px solid #e2e8f0',
          cursor: 'pointer',
          transition: 'all 0.2s ease',
          zIndex: 100,
          boxShadow: '0 2px 8px rgba(0,0,0,0.1)',
          maxWidth: '160px',
          '&:hover': {
            background: 'linear-gradient(135deg, #e2e8f0 0%, #cbd5e1 100%)',
            transform: 'scale(1.02)',
            boxShadow: '0 4px 12px rgba(0,0,0,0.15)'
          }
        }}
      >
        <Avatar 
          sx={{ 
            width: 24, 
            height: 24, 
            bgcolor: getTierColor(tier),
            color: tier?.toLowerCase() === 'platinum' ? '#1f2937' : '#fff',
            fontSize: '10px',
            fontWeight: 600
          }}
        >
          {getInitials(profileData?.full_name)}
        </Avatar>
        <Box sx={{ overflow: 'hidden', minWidth: 0 }}>
          <Typography 
            sx={{ 
              fontSize: '11px',
              fontWeight: 600,
              color: '#1f2937',
              lineHeight: 1.2,
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap'
            }}
          >
            {profileData?.full_name || 'Demo User'}
          </Typography>
          <Typography 
            sx={{ 
              fontSize: '9px',
              color: '#64748b',
              lineHeight: 1,
              fontFamily: 'monospace'
            }}
          >
            ***{ssnLast4}
          </Typography>
        </Box>
      </Box>

      {/* Side Panel Overlay */}
      {panelOpen && (
        <Box
          sx={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.4)',
            zIndex: 9999,
            backdropFilter: 'blur(4px)'
          }}
          onClick={handlePanelClose}
        />
      )}

      {/* Side Panel */}
      <Box
        sx={{
          position: 'fixed',
          top: 0,
          right: panelOpen ? 0 : '-400px',
          width: '400px',
          height: '100vh',
          backgroundColor: '#fff',
          boxShadow: '-8px 0 32px rgba(0,0,0,0.15)',
          zIndex: 10000,
          transition: 'right 0.3s ease',
          display: 'flex',
          flexDirection: 'column',
          overflow: 'hidden'
        }}
      >
        {/* Panel Header */}
        <Box sx={{
          padding: '24px',
          background: 'linear-gradient(135deg, #f8fafc 0%, #e2e8f0 100%)',
          borderBottom: '1px solid #e2e8f0'
        }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6" sx={{ fontSize: '18px', fontWeight: 700, color: '#1f2937' }}>
            Profile Details
          </Typography>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            <Box
              onClick={handlePanelClose}
              sx={{
                width: '32px',
                  height: '32px',
                  borderRadius: '50%',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  cursor: 'pointer',
                  transition: 'all 0.2s ease',
                  '&:hover': {
                    backgroundColor: 'rgba(0,0,0,0.1)'
                  }
                }}
              >
                <Typography sx={{ fontSize: '18px', color: '#64748b' }}>×</Typography>
              </Box>
            </Box>
          </Box>
          
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
            <Avatar 
              sx={{ 
                width: 56, 
                height: 56, 
                bgcolor: getTierColor(tier),
                color: tier?.toLowerCase() === 'platinum' ? '#1f2937' : '#fff',
                fontSize: '20px',
                fontWeight: 700
              }}
            >
              {getInitials(profileData?.full_name)}
            </Avatar>
            <Box>
              <Typography variant="h6" sx={{ fontSize: '16px', fontWeight: 700, color: '#1f2937', lineHeight: 1.2 }}>
                {profileData?.full_name || 'Demo User'}
              </Typography>
              <Chip 
                label={tier}
                size="small"
                sx={{ 
                  backgroundColor: getTierColor(tier),
                  color: tier?.toLowerCase() === 'platinum' ? '#1f2937' : '#fff',
                  fontSize: '10px',
                  fontWeight: 600,
                  height: '20px',
                  mt: 0.5
                }}
              />
            </Box>
          </Box>
        </Box>

        {/* Panel Content */}
        <Box
          sx={{
            flex: 1,
            padding: '24px',
            overflowY: 'auto',
            display: 'flex',
            flexDirection: 'column',
            gap: 3,
          }}
        >
          <Box
            sx={{
              borderRadius: '16px',
              background: 'linear-gradient(135deg, rgba(248, 113, 113, 0.12) 0%, rgba(249, 115, 22, 0.08) 100%)',
              border: '1px solid rgba(248, 113, 113, 0.25)',
              padding: '18px',
              display: 'flex',
              flexDirection: 'column',
              gap: 1.5,
            }}
          >
            <Box sx={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 2, flexWrap: 'wrap' }}>
              <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 1.5 }}>
                <SecurityIcon sx={{ fontSize: '22px', color: '#b91c1c', mt: '2px' }} />
                <Box>
                  <Typography sx={{ fontSize: '12px', fontWeight: 700, color: '#b91c1c', letterSpacing: '0.6px', textTransform: 'uppercase' }}>
                    Verification Tokens
                  </Typography>
                  <Typography sx={{ fontSize: '11px', color: '#ea580c' }}>
                    Regenerated for each demo profile and auto-expire with this session.
                  </Typography>
                </Box>
              </Box>
              <Chip
                label={`SSN • ${ssnLast4}`}
                sx={{
                  background: 'linear-gradient(135deg, #f97316, #ef4444)',
                  color: '#fff',
                  fontWeight: 700,
                  letterSpacing: '0.4px',
                }}
              />
            </Box>
            <Box sx={{ display: 'flex', flexWrap: 'wrap', gap: 1 }}>
              <Chip
                label={`Institution • ${institutionName}`}
                sx={{
                  backgroundColor: '#f1f5f9',
                  color: '#1f2937',
                  fontWeight: 600,
                }}
              />
              <Chip
                label={`Employee • ${verificationCodes.employee_id4 || '----'}`}
                sx={{
                  backgroundColor: '#f1f5f9',
                  color: '#1f2937',
                  fontWeight: 600,
                }}
              />
              <Chip
                label={`Phone • ${verificationCodes.phone4 || '----'}`}
                sx={{
                  backgroundColor: '#f1f5f9',
                  color: '#1f2937',
                  fontWeight: 600,
                }}
              />
              <Chip
                label={`Company Code • ${companyCodeLast4}`}
                sx={{
                  backgroundColor: '#f1f5f9',
                  color: '#1f2937',
                  fontWeight: 600,
                }}
              />
            </Box>
            <Typography sx={{ fontSize: '11px', color: '#475569', fontWeight: 600, mt: 1 }}>
              Institution: {institutionName}
            </Typography>
            <Typography sx={{ fontSize: '10px', color: '#b91c1c', fontWeight: 600 }}>
              Demo use only — do not capture or reuse outside this sandbox.
            </Typography>
          </Box>

          <Divider sx={{ my: 0 }} />

          <Box>
            <SectionTitle icon="🪪">Identity Snapshot</SectionTitle>
            <ProfileDetailRow icon={<PersonIcon />} label="Company Code" value={profileData?.company_code} />
            <ProfileDetailRow icon={<SecurityIcon />} label="Authorization Level" value={toTitleCase(profileData?.authorization_level)} />
            <ProfileDetailRow icon={<SecurityIcon />} label="Preferred MFA" value={toTitleCase(profileData?.contact_info?.preferred_mfa_method)} />
            <ProfileDetailRow icon={<SecurityIcon />} label="MFA Threshold" value={formatCurrency(profileData?.mfa_required_threshold)} />
            <ProfileDetailRow label="Demo Entry" value={entryId} />
          </Box>

          <Divider sx={{ my: 0 }} />

          <Box>
            <SectionTitle icon="📞">Contact</SectionTitle>
            <ProfileDetailRow label="Email" value={profileData?.contact_info?.email} multiline />
            <ProfileDetailRow label="Phone" value={profileData?.contact_info?.phone} />
          </Box>

          <Divider sx={{ my: 0 }} />

          <Box>
            <SectionTitle icon="📊">Account Signals</SectionTitle>
            <ProfileDetailRow icon={<AccountBalanceIcon />} label="Current Balance" value={formatCurrency(profileData?.customer_intelligence?.account_status?.current_balance)} />
            <ProfileDetailRow icon={<AccountBalanceIcon />} label="YTD Volume" value={formatCurrency(profileData?.customer_intelligence?.account_status?.ytd_transaction_volume)} />
            <ProfileDetailRow label="Account Health" value={formatNumber(profileData?.customer_intelligence?.account_status?.account_health_score)} />
            <ProfileDetailRow label="Login Frequency" value={toTitleCase(profileData?.customer_intelligence?.account_status?.login_frequency)} />
            <ProfileDetailRow icon={<ScheduleIcon />} label="Last Login" value={formatDate(profileData?.customer_intelligence?.account_status?.last_login)} />
            <ProfileDetailRow icon={<AccountBalanceIcon />} label="Lifetime Value" value={formatCurrency(profileData?.customer_intelligence?.relationship_context?.lifetime_value)} />
          </Box>

          {interactionPlan && (
            <>
              <Divider sx={{ my: 0 }} />
              <Box>
                <SectionTitle icon="🗓️">Interaction Plan</SectionTitle>
                <ProfileDetailRow label="Primary Channel" value={toTitleCase(interactionPlan.primary_channel)} />
                <ProfileDetailRow label="Fallback Channel" value={toTitleCase(interactionPlan.fallback_channel)} />
                <ProfileDetailRow label="MFA Required" value={interactionPlan.mfa_required ? 'Yes' : 'No'} />
                <ProfileDetailRow label="Notification" value={interactionPlan.notification_message} multiline />
              </Box>
            </>
          )}

          <Divider sx={{ my: 0 }} />

          <Box>
            <SectionTitle icon="💳">Recent Transactions</SectionTitle>
            {transactions.length ? (
              <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
                {transactions.map((txn) => (
                  <Box
                    key={txn.transaction_id}
                    sx={{
                      border: '1px solid #e2e8f0',
                      borderRadius: '10px',
                      padding: '10px 12px',
                      backgroundColor: '#f8fafc',
                    }}
                  >
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 0.5 }}>
                      <Typography sx={{ fontWeight: 600, color: '#1f2937', fontSize: '12px' }}>
                        {txn.merchant}
                      </Typography>
                      <Typography sx={{ fontWeight: 600, color: '#0f172a', fontSize: '12px' }}>
                        {formatCurrencyWithCents(txn.amount)}
                      </Typography>
                    </Box>
                    <Typography sx={{ color: '#64748b', fontSize: '11px' }}>
                      {formatDateTime(txn.timestamp)} • {toTitleCase(txn.category)}
                    </Typography>
                    <Typography sx={{ color: '#0ea5e9', fontSize: '10px', fontWeight: 600, mt: 0.5 }}>
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
          </Box>

          <Box>
            <SectionTitle icon="⌛">Demo Timeline</SectionTitle>
            <ProfileDetailRow label="Issued" value={formatDateTime(profileData?.created_at)} />
            <ProfileDetailRow label="Session" value={sessionId} />
            <ProfileDetailRow label="Expires" value={formatDateTime(expiresAt)} />
          </Box>

          {profile.safetyNotice && (
            <Box sx={{
              marginTop: '8px',
              padding: '12px 16px',
              borderRadius: '8px',
              background: '#fef2f2',
              border: '1px solid #fecaca',
              color: '#b91c1c',
              fontSize: '11px',
              fontWeight: 600,
              textAlign: 'center'
            }}>
              {profile.safetyNotice}
            </Box>
          )}
        </Box>
      </Box>
    </>
  );
};

export default ProfileButton;
