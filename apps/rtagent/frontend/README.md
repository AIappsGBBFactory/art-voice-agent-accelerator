# Real-Time Voice Agent Frontend

React-based voice interface for Azure Communication Services with WebSocket real-time communication.

## Quick Start

### Prerequisites
- Node.js 18+
- Backend running on `http://localhost:8000`

### Setup
```bash
npm install
npm run dev  # Available at http://localhost:5173
```

### Production
```bash
npm run build
npm run preview
```

## Architecture

### Single Component Design
Monolithic architecture with all functionality in `RealTimeVoiceApp.jsx`:

```
frontend/
├── src/
│   ├── main.jsx              # React entry point
│   ├── App.jsx               # App wrapper
│   └── components/
│       └── RealTimeVoiceApp.jsx  # Complete voice application
├── package.json
├── vite.config.js
└── .env                      # Environment configuration
```

### Core Components
All components defined inline in `RealTimeVoiceApp.jsx`:
- **BackendIndicator** - Connection health monitoring
- **WaveformVisualization** - Audio-reactive visual feedback
- **ChatBubble** - Message display with timestamps
- **HelpButton** - User assistance modal
- **BackendStatisticsButton** - Backend metrics display

## Features

- **Real-time Voice Processing** - WebAudio API integration
- **WebSocket Communication** - Live backend connectivity
- **Azure Communication Services** - Phone call integration
- **Health Monitoring** - Backend status indicators
- **Fixed-width Interface** - 768px professional design

## Configuration

### Environment Variables
```bash
# .env
VITE_BACKEND_BASE_URL=http://localhost:8000
```

### Backend Integration
- Health: `/api/v1/readiness`
- WebSocket: `/api/v1/ws/call/{call_id}`
- Calls: `/api/v1/calls/`

## Dependencies

- **React 19** - Core framework
- **Vite** - Build tool
- **Azure Communication Services** - Voice calling
- **Microsoft Cognitive Services** - Speech SDK
- **ReactFlow** - Visualization
- **Lucide React** - Icons

## Development

### Commands
```bash
npm run dev      # Development server
npm run build    # Production build
npm run preview  # Preview build
```

### Browser Requirements
- WebAudio API support
- WebSocket support

## Deployment

Static build deployment:
```bash
npm run build  # Generates /dist folder
```

Deploy `/dist` to any static hosting service (Vercel, Netlify, Azure Static Web Apps).

## UI Components

**Main Interface**:
- 768px fixed width
- Voice controls (start/stop, phone)
- Real-time waveform animation
- Message bubbles with timestamps
- Backend health status
- Help system modal
