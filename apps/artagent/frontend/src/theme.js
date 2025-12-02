// theme.js - Dynamic UI theming based on environment variables
// This allows easy rebranding for different clients/demos

/**
 * Get theme configuration from environment variables
 * Supports color customization, branding, and logo configuration
 */
const getThemeConfig = () => {
  // Primary brand color (used for buttons, accents)
  const primaryColor = import.meta.env.VITE_PRIMARY_COLOR || '#67d8ef';
  
  // Secondary brand color
  const secondaryColor = import.meta.env.VITE_SECONDARY_COLOR || '#3b82f6';
  
  // Header gradient colors
  const headerGradientStart = import.meta.env.VITE_HEADER_GRADIENT_START || '#ffffff';
  const headerGradientEnd = import.meta.env.VITE_HEADER_GRADIENT_END || '#f8fafc';
  
  // Institution/Company name (displayed in header)
  const institutionName = import.meta.env.VITE_INSTITUTION_NAME || 'ARTAgent';
  
  // App display title (shown in UI header - separate from institution name)
  const appTitle = import.meta.env.VITE_APP_TITLE || 'AI Voice Assistant';
  
  // Agent/Assistant name
  const agentName = import.meta.env.VITE_AGENT_NAME || 'Voice Assistant';
  
  // Logo URL (if provided, will replace text logo)
  const logoUrl = import.meta.env.VITE_LOGO_URL || null;
  
  // App subtitle/tagline
  const appSubtitle = import.meta.env.VITE_APP_SUBTITLE || '';
  
  // App icon/emoji (set to empty string to hide)
  const appIcon = import.meta.env.VITE_APP_ICON !== undefined && import.meta.env.VITE_APP_ICON !== '' 
    ? import.meta.env.VITE_APP_ICON 
    : '🎙️';
  
  // Chat bubble color for assistant messages
  const assistantBubbleColor = import.meta.env.VITE_ASSISTANT_BUBBLE_COLOR || primaryColor;

  return {
    primaryColor,
    secondaryColor,
    headerGradientStart,
    headerGradientEnd,
    institutionName,
    appTitle,
    agentName,
    logoUrl,
    appSubtitle,
    appIcon,
    assistantBubbleColor,
    
    // Computed styles
    assistantBubbleGradient: `linear-gradient(135deg, ${assistantBubbleColor}, ${adjustColor(assistantBubbleColor, -10)})`,
    headerGradient: `linear-gradient(180deg, ${headerGradientStart} 0%, ${headerGradientEnd} 100%)`,
    primaryGradient: `linear-gradient(135deg, ${primaryColor}, ${adjustColor(primaryColor, -15)})`,
  };
};

/**
 * Adjust color brightness (simple hex color adjustment)
 * @param {string} color - Hex color (e.g., '#67d8ef')
 * @param {number} percent - Percentage to adjust (-100 to 100)
 */
function adjustColor(color, percent) {
  // Remove # if present
  const hex = color.replace('#', '');
  
  // Convert to RGB
  const num = parseInt(hex, 16);
  const r = Math.max(0, Math.min(255, ((num >> 16) & 0xff) + Math.round(2.55 * percent)));
  const g = Math.max(0, Math.min(255, ((num >> 8) & 0xff) + Math.round(2.55 * percent)));
  const b = Math.max(0, Math.min(255, (num & 0xff) + Math.round(2.55 * percent)));
  
  // Convert back to hex
  return `#${((r << 16) | (g << 8) | b).toString(16).padStart(6, '0')}`;
}

/**
 * Get rgba version of hex color
 */
const hexToRgba = (hex, alpha = 1) => {
  const cleanHex = hex.replace('#', '');
  const num = parseInt(cleanHex, 16);
  const r = (num >> 16) & 0xff;
  const g = (num >> 8) & 0xff;
  const b = num & 0xff;
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

// Export theme singleton with utility functions
export const theme = {
  ...getThemeConfig(),
  hexToRgba,
  adjustColor,
};

// Default export
export default theme;
