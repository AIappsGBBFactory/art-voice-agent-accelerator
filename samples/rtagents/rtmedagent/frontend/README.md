# 🏥 RT Medical Agent Frontend

A modern React-based frontend for the Real-Time Insurance Agent, featuring voice-enabled conversations, visual conversation mapping, and multi-channel communication support.

## 🚀 Quick Start

### Prerequisites

Before running the frontend, ensure you have:

- **Node.js**: Version 18 or higher
- **Azure Speech Services**: Key and region for speech-to-text/text-to-speech
- **Backend Service**: RTInsuranceAgent backend running (typically on port 8010)

### Installation & Setup

1. **Install Dependencies**
   ```bash
   npm install
   ```

2. **Configure Environment Variables**
   
   Copy the sample environment file and configure it:
   ```bash
   cp .env.sample .env
   ```
   
   Edit `.env` with your actual values:
   ```env
   # Azure Speech Services Configuration
   VITE_AZURE_SPEECH_KEY=your-azure-speech-key-here
   VITE_AZURE_REGION=eastus
   
   # Backend Configuration
   VITE_BACKEND_BASE_URL=http://localhost:8010
   ```

3. **Start the Development Server**
   ```bash
   npm run dev
   ```
   
   The application will be available at [http://localhost:5173](http://localhost:5173)

## 🏗️ Architecture & Communication Flow

### Frontend Components

- **App.jsx**: Main application component orchestrating all interactions
- **ChatSection**: Real-time conversation display with streaming message support
- **PhoneWidget**: Visual phone interface with call controls and animations
- **MindMap**: Interactive conversation flow visualization using ReactFlow
- **ControlBar**: Voice controls and settings panel
- **LogsPanel**: Technical logging and debugging information

### Communication Architecture

```
Frontend (React) ←→ WebSocket ←→ Backend (FastAPI) ←→ Azure Services
```

#### 1. **WebSocket Connection** (`/realtime` endpoint)
- **Outbound**: Text messages as `{ text: "user input" }`
- **Inbound**: Multiple message types:
  - `assistant_streaming`: Real-time GPT response chunks
  - `assistant`: Complete assistant responses
  - `status`: System status messages
  - `tool_*`: Tool execution updates
  - Binary audio data for text-to-speech playback

#### 2. **Speech Integration**
- **Speech-to-Text**: Microsoft Cognitive Services Speech SDK
- **Text-to-Speech**: Audio chunks streamed via WebSocket from backend
- **Real-time Processing**: Continuous speech recognition with voice activity detection

#### 3. **Data Flow**

**User Voice Input:**
1. Browser captures audio via Speech SDK
2. Azure Speech Services converts to text
3. Text sent to backend via WebSocket
4. Backend processes with GPT and tools
5. Response streamed back with TTS audio

**Assistant Response:**
1. Backend generates response using Azure OpenAI
2. Streaming text chunks sent to frontend
3. TTS audio generated and streamed as binary
4. Frontend plays audio and updates conversation UI
5. Mind map visualization updated with conversation flow

### Key Features

- **🎤 Voice Interaction**: Hands-free conversation with push-to-talk and continuous modes
- **📱 Phone UI**: Realistic phone interface with call animations and visual feedback
- **🧠 Mind Mapping**: Dynamic visualization of conversation flow and context
- **🔄 Real-time Streaming**: Live text and audio streaming for natural conversations
- **📊 Technical Logging**: Comprehensive logging for debugging and monitoring
- **🌐 Multi-channel Support**: WebSocket and Azure Communication Services integration

## 🛠️ Development

### Available Scripts

- `npm run dev`: Start development server with hot reload
- `npm run build`: Build for production
- `npm run preview`: Preview production build locally
- `npm run lint`: Run ESLint for code quality

### Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `VITE_AZURE_SPEECH_KEY` | Azure Speech Services authentication | `abc123...` |
| `VITE_AZURE_REGION` | Azure region for Speech Services | `eastus`, `westus2` |
| `VITE_BACKEND_BASE_URL` | Backend API base URL | `http://localhost:8010` |

> **Note**: The WebSocket URL is automatically constructed by replacing `http/https` with `ws/wss` from the base URL.

### Tech Stack

- **Frontend Framework**: React 19 with Vite
- **WebSocket**: Native WebSocket API with custom hooks
- **Speech**: Microsoft Cognitive Services Speech SDK
- **Visualization**: ReactFlow for mind mapping
- **Communication**: Azure Communication Services SDK
- **Styling**: CSS-in-JS with custom animations

## 🔧 Troubleshooting

### Common Issues

1. **WebSocket Connection Fails**
   - Verify backend is running on correct port
   - Check CORS settings in backend
   - Ensure `VITE_BACKEND_BASE_URL` is correct

2. **Speech Recognition Not Working**
   - Verify Azure Speech Services key and region
   - Check browser microphone permissions
   - Ensure HTTPS for production deployments

3. **Audio Playback Issues**
   - Check browser audio permissions
   - Verify TTS audio format compatibility
   - Monitor WebSocket binary message reception

### Debugging

Enable detailed logging by checking the "Show Logs" option in the UI. This displays:
- WebSocket connection status
- Message flow (text and binary)
- Speech recognition events
- Audio playback status
- Error messages and stack traces
