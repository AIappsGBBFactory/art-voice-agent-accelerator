import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './components/App.jsx'
import abstractBg from './assets/abstract.jpg'
import logger, { configureLogLevel } from './utils/logger.js'
import { initTelemetry, setAuthenticatedUser } from './utils/telemetry.js'
import { fetchAuthenticatedUser } from './utils/auth.js'

// Set background image dynamically for proper Vite asset handling
document.body.style.backgroundImage = `url(${abstractBg})`

configureLogLevel(import.meta.env?.VITE_APP_LOG_LEVEL ?? import.meta.env?.VITE_LOG_LEVEL)
logger.info('[ARTAgent] Frontend bootstrapping')

// Initialize browser telemetry early, then bind the signed-in operator (if
// EasyAuth is enabled) so telemetry is attributed to a stable user across
// sessions. Both are best-effort and never block rendering.
initTelemetry()
fetchAuthenticatedUser()
  .then((user) => {
    if (user) setAuthenticatedUser(user)
  })
  .catch(() => {})

createRoot(document.getElementById('root')).render(
  <StrictMode>
    <App />
  </StrictMode>,
)