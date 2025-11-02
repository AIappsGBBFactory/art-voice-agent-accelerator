import React, { useState, useEffect, useRef } from 'react';

/**
 * UserSwitcher Component
 * 
 * Displays current user profile and allows switching between demo users.
 * Positioned above the ARTAgent chat interface in the header.
 */
const UserSwitcher = ({ 
  currentUser, 
  availableUsers, 
  onUserSwitch, 
  isLoading 
}) => {
  const [isOpen, setIsOpen] = useState(false);
  const dropdownRef = useRef(null);

  // Close dropdown when clicking outside
  useEffect(() => {
    const handleClickOutside = (event) => {
      if (dropdownRef.current && !dropdownRef.current.contains(event.target)) {
        setIsOpen(false);
      }
    };

    if (isOpen) {
      document.addEventListener('mousedown', handleClickOutside);
    }
    
    return () => {
      document.removeEventListener('mousedown', handleClickOutside);
    };
  }, [isOpen]);

  const tierColors = {
    Member: {
      bg: '#64748b',
      light: '#e2e8f0',
      text: '#475569'
    },
    Gold: {
      bg: '#eab308',
      light: '#fef3c7',
      text: '#854d0e'
    },
    Platinum: {
      bg: '#a855f7',
      light: '#f3e8ff',
      text: '#6b21a8'
    }
  };

  // Don't render until users are loaded (they load when WebSocket connects)
  if (!currentUser) {
    return null;
  }

  const currentTierColor = tierColors[currentUser.loyalty_tier] || tierColors.Member;

  return (
    <div style={styles.container} ref={dropdownRef}>
      {/* Current User Button */}
      <button
        onClick={() => setIsOpen(!isOpen)}
        disabled={isLoading}
        style={{
          ...styles.userButton,
          cursor: isLoading ? 'wait' : 'pointer',
          opacity: isLoading ? 0.7 : 1
        }}
        onMouseEnter={(e) => {
          if (!isLoading) {
            e.currentTarget.style.transform = 'translateY(-1px)';
            e.currentTarget.style.boxShadow = '0 4px 16px rgba(0, 0, 0, 0.12), 0 2px 4px rgba(0, 0, 0, 0.06)';
          }
        }}
        onMouseLeave={(e) => {
          e.currentTarget.style.transform = 'translateY(0)';
          e.currentTarget.style.boxShadow = '0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.04)';
        }}
      >
        {/* Avatar Emoji */}
        <div style={{
          ...styles.avatar,
          background: `linear-gradient(135deg, ${currentTierColor.bg}, ${currentTierColor.light})`
        }}>
          <span style={styles.avatarEmoji}>{currentUser.avatar_emoji || '👤'}</span>
        </div>

        {/* User Info */}
        <div style={styles.userInfo}>
          <span style={styles.userName}>{currentUser.full_name}</span>
          <span style={{
            ...styles.userTier,
            color: currentTierColor.text
          }}>
            {currentUser.loyalty_tier} Member
          </span>
        </div>

        {/* Dropdown Arrow */}
        <span style={{
          ...styles.arrow,
          transform: isOpen ? 'rotate(180deg)' : 'rotate(0deg)'
        }}>
          ▾
        </span>
      </button>

      {/* Dropdown Menu */}
      {isOpen && availableUsers && availableUsers.length > 0 && (
        <div style={styles.dropdown}>
          {availableUsers.map((user) => {
            const tierColor = tierColors[user.loyalty_tier] || tierColors.Member;
            const isCurrentUser = user.user_id === currentUser.user_id;

            return (
              <div
                key={user.user_id}
                onClick={() => {
                  if (!isCurrentUser && !isLoading) {
                    onUserSwitch(user);
                    setIsOpen(false);
                  }
                }}
                style={{
                  ...styles.dropdownItem,
                  backgroundColor: isCurrentUser ? '#f8fafc' : 'transparent',
                  cursor: isCurrentUser || isLoading ? 'default' : 'pointer',
                  opacity: isLoading ? 0.6 : 1
                }}
                onMouseEnter={(e) => {
                  if (!isCurrentUser && !isLoading) {
                    e.currentTarget.style.backgroundColor = '#f8fafc';
                  }
                }}
                onMouseLeave={(e) => {
                  if (!isCurrentUser) {
                    e.currentTarget.style.backgroundColor = 'transparent';
                  }
                }}
              >
                {/* Avatar */}
                <div style={{
                  ...styles.dropdownAvatar,
                  background: `linear-gradient(135deg, ${tierColor.bg}, ${tierColor.light})`
                }}>
                  <span style={styles.avatarEmoji}>{user.avatar_emoji || '👤'}</span>
                </div>

                {/* User Details */}
                <div style={styles.dropdownUserInfo}>
                  <div style={styles.dropdownUserName}>
                    {user.full_name}
                    {isCurrentUser && (
                      <span style={styles.checkmark}>✓</span>
                    )}
                  </div>
                  <div style={styles.dropdownUserMeta}>
                    <span style={{
                      ...styles.tierBadge,
                      backgroundColor: tierColor.light,
                      color: tierColor.text
                    }}>
                      {user.loyalty_tier}
                    </span>
                    <span style={styles.location}>{user.location}</span>
                  </div>
                  {user.style_summary && (
                    <div style={styles.styleSummary}>
                      {user.style_summary}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};

const styles = {
  container: {
    position: 'relative',
    zIndex: 1000,
  },

  userButton: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
    padding: '8px 14px',
    backgroundColor: 'rgba(255, 255, 255, 0.95)',
    backdropFilter: 'blur(10px)',
    border: '0.5px solid rgba(0, 0, 0, 0.1)',
    borderRadius: '14px',
    fontFamily: '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif',
    fontSize: '13px',
    color: '#1e293b',
    transition: 'all 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
    boxShadow: '0 2px 8px rgba(0, 0, 0, 0.08), 0 1px 2px rgba(0, 0, 0, 0.04)',
    minWidth: '200px',
  },

  avatar: {
    width: '36px',
    height: '36px',
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },

  avatarEmoji: {
    fontSize: '18px',
  },

  userInfo: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-start',
    flex: 1,
  },

  userName: {
    fontWeight: 600,
    fontSize: '14px',
    color: '#1e293b',
  },

  userTier: {
    fontSize: '11px',
    fontWeight: 500,
    marginTop: '2px',
  },

  arrow: {
    fontSize: '12px',
    color: '#64748b',
    transition: 'transform 0.2s ease',
  },

  dropdown: {
    position: 'absolute',
    top: 'calc(100% + 8px)',
    right: 0,
    backgroundColor: 'rgba(255, 255, 255, 0.98)',
    backdropFilter: 'blur(20px)',
    border: '0.5px solid rgba(0, 0, 0, 0.1)',
    borderRadius: '14px',
    boxShadow: '0 10px 40px rgba(0, 0, 0, 0.15), 0 4px 12px rgba(0, 0, 0, 0.08)',
    minWidth: '300px',
    maxHeight: '400px',
    overflowY: 'auto',
    animation: 'fadeIn 0.2s cubic-bezier(0.4, 0, 0.2, 1)',
  },

  dropdownItem: {
    display: 'flex',
    alignItems: 'center',
    gap: '12px',
    padding: '12px 16px',
    borderBottom: '0.5px solid rgba(0, 0, 0, 0.06)',
    transition: 'all 0.15s cubic-bezier(0.4, 0, 0.2, 1)',
  },

  dropdownAvatar: {
    width: '44px',
    height: '44px',
    borderRadius: '50%',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: 0,
  },

  dropdownUserInfo: {
    display: 'flex',
    flexDirection: 'column',
    gap: '4px',
    flex: 1,
  },

  dropdownUserName: {
    fontSize: '14px',
    fontWeight: 600,
    color: '#1e293b',
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
  },

  checkmark: {
    color: '#0284c7',
    fontSize: '16px',
    fontWeight: 'bold',
  },

  dropdownUserMeta: {
    display: 'flex',
    alignItems: 'center',
    gap: '8px',
    fontSize: '11px',
  },

  tierBadge: {
    padding: '2px 8px',
    borderRadius: '6px',
    fontSize: '10px',
    fontWeight: 600,
  },

  location: {
    color: '#64748b',
  },

  styleSummary: {
    fontSize: '11px',
    color: '#94a3b8',
    fontStyle: 'italic',
  },
};

// Add keyframe animations via CSS
const styleSheet = document.createElement('style');
styleSheet.textContent = `
  @keyframes fadeIn {
    from {
      opacity: 0;
      transform: translateY(-8px);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }
`;
document.head.appendChild(styleSheet);

export default UserSwitcher;
