/**
 * Application Configuration Constants
 * 
 * Central configuration for API endpoints and environment variables
 */

// Simple placeholder that gets replaced at container startup, with fallback for local dev
const backendPlaceholder = '__BACKEND_URL__';

const baseBackendUrl = backendPlaceholder.startsWith('__') 
  ? import.meta.env.VITE_BACKEND_BASE_URL || 'http://localhost:8080'
  : backendPlaceholder;

export const API_BASE_URL = `${baseBackendUrl}/api/v1`;

export const WS_URL = baseBackendUrl.replace(/^https?/, "wss");

// Application metadata
export const APP_CONFIG = {
  name: "Real-Time Voice App",
  subtitle: "AI-powered voice interaction platform",
  version: "1.0.0"
};
