import React, { useState } from 'react';

/**
 * Elegant health status indicator component
 * Shows overall system status with expandable details
 */
const HealthStatusIndicator = ({ 
  healthStatus, 
  readinessStatus, 
  overallStatus, 
  onRefresh,
  compact = false 
}) => {
  const [isExpanded, setIsExpanded] = useState(false);

  // Status indicator styles
  const getStatusColor = (status) => {
    if (status === 'healthy' || status === 'ready') return '#22C55E';
    if (status === 'warning') return '#F59E0B';
    return '#EF4444';
  };

  const getOverallColor = () => {
    if (overallStatus.isHealthy) return '#22C55E';
    if (overallStatus.hasWarnings) return '#F59E0B';
    return '#EF4444';
  };

  const formatTime = (timestamp) => {
    if (!timestamp) return 'Never';
    const date = new Date(timestamp);
    return date.toLocaleTimeString();
  };

  const formatDuration = (ms) => {
    if (ms === null || ms === undefined) return 'N/A';
    return `${ms.toFixed(1)}ms`;
  };

  if (compact) {
    return (
      <div style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 6,
        padding: '4px 8px',
        borderRadius: 6,
        background: 'rgba(255,255,255,0.1)',
        fontSize: '0.8rem',
        cursor: 'pointer',
      }}
      onClick={() => setIsExpanded(!isExpanded)}
      >
        <div style={{
          width: 8,
          height: 8,
          borderRadius: '50%',
          background: getOverallColor(),
          boxShadow: `0 0 4px ${getOverallColor()}`,
        }} />
        <span>
          {overallStatus.isHealthy ? 'Healthy' : 
           overallStatus.hasWarnings ? 'Warning' : 'Error'}
        </span>
      </div>
    );
  }

  return (
    <div style={{
      background: 'rgba(255,255,255,0.05)',
      borderRadius: 12,
      padding: 16,
      border: `1px solid ${getOverallColor()}33`,
    }}>
      {/* Header */}
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        marginBottom: isExpanded ? 16 : 0,
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <div style={{
            width: 12,
            height: 12,
            borderRadius: '50%',
            background: getOverallColor(),
            boxShadow: `0 0 8px ${getOverallColor()}`,
            animation: overallStatus.isHealthy ? 'none' : 'led 2s infinite',
          }} />
          <h4 style={{ margin: 0, fontSize: '1rem' }}>
            System Status: {overallStatus.isHealthy ? 'Healthy' : 
                           overallStatus.hasWarnings ? 'Warning' : 'Critical'}
          </h4>
        </div>
        
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={onRefresh}
            style={{
              background: 'rgba(255,255,255,0.1)',
              border: 'none',
              borderRadius: 6,
              padding: '6px 12px',
              color: '#E5E7EB',
              cursor: 'pointer',
              fontSize: '0.8rem',
            }}
          >
            🔄 Refresh
          </button>
          <button
            onClick={() => setIsExpanded(!isExpanded)}
            style={{
              background: 'rgba(255,255,255,0.1)',
              border: 'none',
              borderRadius: 6,
              padding: '6px 12px',
              color: '#E5E7EB',
              cursor: 'pointer',
              fontSize: '0.8rem',
            }}
          >
            {isExpanded ? '▲' : '▼'}
          </button>
        </div>
      </div>

      {/* Quick Status Line */}
      {!isExpanded && (
        <div style={{
          fontSize: '0.8rem',
          color: '#9CA3AF',
          display: 'flex',
          gap: 16,
        }}>
          <span>Health: {healthStatus.isHealthy ? '✅' : '❌'}</span>
          <span>Readiness: {readinessStatus.status === 'ready' ? '✅' : '❌'}</span>
          <span>Last: {formatTime(healthStatus.lastChecked)}</span>
        </div>
      )}

      {/* Expanded Details */}
      {isExpanded && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
          {/* Basic Health */}
          <div style={{
            background: 'rgba(0,0,0,0.2)',
            borderRadius: 8,
            padding: 12,
          }}>
            <h5 style={{ margin: '0 0 8px 0', color: '#F3F4F6' }}>Basic Health</h5>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: '0.85rem' }}>
              <div>Status: <span style={{ color: getStatusColor(healthStatus.isHealthy ? 'healthy' : 'unhealthy') }}>
                {healthStatus.isHealthy ? 'Healthy' : 'Unhealthy'}
              </span></div>
              <div>Response Time: {formatDuration(healthStatus.responseTime)}</div>
              <div>Last Check: {formatTime(healthStatus.lastChecked)}</div>
              {healthStatus.error && (
                <div style={{ gridColumn: '1 / -1', color: '#EF4444' }}>
                  Error: {healthStatus.error}
                </div>
              )}
            </div>
          </div>

          {/* Readiness Details */}
          <div style={{
            background: 'rgba(0,0,0,0.2)',
            borderRadius: 8,
            padding: 12,
          }}>
            <h5 style={{ margin: '0 0 8px 0', color: '#F3F4F6' }}>Readiness Checks</h5>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontSize: '0.85rem', marginBottom: 12 }}>
              <div>Overall: <span style={{ color: getStatusColor(readinessStatus.status) }}>
                {readinessStatus.status || 'Unknown'}
              </span></div>
              <div>Response Time: {formatDuration(readinessStatus.responseTime)}</div>
              <div>Last Check: {formatTime(readinessStatus.lastChecked)}</div>
            </div>

            {/* Component Checks */}
            {readinessStatus.checks.length > 0 && (
              <div>
                <h6 style={{ margin: '8px 0', color: '#D1D5DB', fontSize: '0.8rem' }}>Components:</h6>
                <div style={{ display: 'grid', gap: 6 }}>
                  {readinessStatus.checks.map((check, i) => (
                    <div key={i} style={{
                      display: 'flex',
                      justifyContent: 'space-between',
                      alignItems: 'center',
                      padding: '6px 8px',
                      borderRadius: 4,
                      background: 'rgba(255,255,255,0.05)',
                      fontSize: '0.8rem',
                    }}>
                      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                        <div style={{
                          width: 6,
                          height: 6,
                          borderRadius: '50%',
                          background: getStatusColor(check.status),
                        }} />
                        {check.component}
                      </span>
                      <span style={{ color: '#9CA3AF' }}>
                        {formatDuration(check.check_time_ms)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {readinessStatus.error && (
              <div style={{ 
                marginTop: 8, 
                padding: 8, 
                borderRadius: 4, 
                background: 'rgba(239, 68, 68, 0.1)',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                color: '#EF4444',
                fontSize: '0.8rem',
              }}>
                Error: {readinessStatus.error}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};

export default HealthStatusIndicator;
