import React, { useState } from 'react';
import { 
  Avatar, 
  Typography, 
  Chip, 
  Box, 
  Divider
} from '@mui/material';
import { 
  Person as PersonIcon, 
  Security as SecurityIcon,
  AccountBalance as AccountBalanceIcon,
  Schedule as ScheduleIcon
} from '@mui/icons-material';

/* ------------------------------------------------------------------ *
 *  PROFILE DETAIL ROW COMPONENT
 * ------------------------------------------------------------------ */
const ProfileDetailRow = ({ icon, label, value }) => (
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
      maxWidth: '180px',
      overflow: 'hidden',
      textOverflow: 'ellipsis',
      whiteSpace: 'nowrap'
    }}>
      {value || '—'}
    </Typography>
  </Box>
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

  const formatUpper = (str) => {
    if (!str) return '—';
    return str.toUpperCase();
  };

  const resolveRelationshipTier = (profileData) => {
    return profileData?.customer_intelligence?.relationship_context?.tier || '—';
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
  const tier = resolveRelationshipTier(profileData);
  const ssnLast4 = profileData?.verification_codes?.ssn4 || '----';

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

        {/* SSN Notice */}
        <Box sx={{
          display: 'flex',
          justifyContent: 'center',
          padding: '16px 24px',
          background: 'linear-gradient(135deg, rgba(239, 68, 68, 0.05) 0%, rgba(249, 115, 22, 0.05) 100%)'
        }}>
          <Chip
            icon={<SecurityIcon sx={{ fontSize: '14px !important' }} />}
            label={`Demo SSN Last 4: ${ssnLast4}`}
            sx={{
              background: 'linear-gradient(135deg, #f97316, #ef4444)',
              color: '#fff',
              fontWeight: 700,
              fontSize: '11px',
              letterSpacing: '0.5px'
            }}
          />
        </Box>

        {/* Panel Content */}
        <Box sx={{ flex: 1, padding: '24px', overflowY: 'auto' }}>
          <ProfileDetailRow icon={<PersonIcon />} label="Company Code" value={profileData?.company_code} />
          <ProfileDetailRow icon={<SecurityIcon />} label="Preferred MFA" value={formatUpper(profileData?.contact_info?.preferred_mfa_method)} />
          <ProfileDetailRow icon={<SecurityIcon />} label="MFA Threshold" value={formatCurrency(profileData?.mfa_required_threshold)} />
          
          <Divider sx={{ my: 3 }} />
          
          <ProfileDetailRow label="Email" value={profileData?.contact_info?.email} />
          <ProfileDetailRow label="Phone" value={profileData?.contact_info?.phone} />
          
          <Divider sx={{ my: 3 }} />
          
          <ProfileDetailRow icon={<AccountBalanceIcon />} label="Current Balance" value={formatCurrency(profileData?.customer_intelligence?.account_status?.current_balance)} />
          <ProfileDetailRow icon={<AccountBalanceIcon />} label="YTD Volume" value={formatCurrency(profileData?.customer_intelligence?.account_status?.ytd_transaction_volume)} />
          <ProfileDetailRow label="Account Health" value={formatNumber(profileData?.customer_intelligence?.account_status?.account_health_score)} />
          <ProfileDetailRow label="Login Frequency" value={profileData?.customer_intelligence?.account_status?.login_frequency} />
          <ProfileDetailRow icon={<ScheduleIcon />} label="Last Login" value={formatDate(profileData?.customer_intelligence?.account_status?.last_login)} />
          <ProfileDetailRow icon={<AccountBalanceIcon />} label="Lifetime Value" value={formatCurrency(profileData?.customer_intelligence?.relationship_context?.lifetime_value)} />
          
          <Divider sx={{ my: 3 }} />
          
          <Typography variant="body2" sx={{ fontSize: '11px', color: '#64748b', fontWeight: 600, mb: 2 }}>
            VERIFICATION CODES
          </Typography>
          <Typography variant="body2" sx={{ fontSize: '12px', color: '#1f2937', mb: 3 }}>
            SSN {profileData?.verification_codes?.ssn4 || '----'} • Employee {profileData?.verification_codes?.employee_id4 || '----'} • Phone {profileData?.verification_codes?.phone4 || '----'}
          </Typography>
          
          <ProfileDetailRow label="Session" value={sessionId} />
          <ProfileDetailRow 
            label="Expires" 
            value={profile.expiresAt ? new Date(profile.expiresAt).toLocaleString(undefined, {
              dateStyle: "medium",
              timeStyle: "short",
            }) : '—'} 
          />
          
          {profile.safetyNotice && (
            <Box sx={{
              marginTop: '20px',
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