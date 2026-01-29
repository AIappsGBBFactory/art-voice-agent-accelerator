# Development & Testing Samples

This directory contains notebooks and scripts for testing deployed infrastructure components.

## Notebooks

### `test_speech_containers.ipynb`

Tests the Azure Speech containers (STT & TTS) deployed on Azure Container Instances.

**Features:**
- **Auto-loads configuration from Azure App Configuration** (deployed via `azd provision`)
- Health checks for container `/status` and `/ready` endpoints
- STT testing via Azure Speech SDK (WebSocket)
- TTS testing via HTTP REST API and SDK
- List available voices in container
- Raw WebSocket connection test
- Latency benchmarking
- Fallback to environment variables for local development

**Prerequisites:**
```bash
pip install azure-cognitiveservices-speech azure-appconfiguration-provider azure-identity aiohttp websockets
```

**Quick Start (Recommended - App Configuration):**
```bash
# Set App Config endpoint (from azd env)
export AZURE_APPCONFIG_ENDPOINT=$(azd env get-value AZURE_APPCONFIG_ENDPOINT)

# Optional: specify environment label (defaults to "dev")
export AZURE_APPCONFIG_LABEL="dev"

# Login to Azure (required for App Config access)
az login
```

The notebook will automatically load these keys from App Configuration:
- `azure/speech-containers/enabled`
- `azure/speech-containers/stt-endpoint`
- `azure/speech-containers/tts-endpoint`
- `azure/speech-containers/api-key`

**Alternative: Environment Variables (for local dev):**
```bash
export SPEECH_USE_CONTAINERS="true"
export STT_CONTAINER_ENDPOINT="ws://localhost:5000"
export TTS_CONTAINER_ENDPOINT="http://localhost:5001"
export SPEECH_CONTAINER_API_KEY="<your-api-key>"
```

## Local Container Testing

For local testing without Azure deployment:

```bash
# Pull containers
docker pull mcr.microsoft.com/azure-cognitive-services/speechservices/speech-to-text:latest
docker pull mcr.microsoft.com/azure-cognitive-services/speechservices/neural-text-to-speech:latest

# Run STT (port 5000)
docker run --rm -it -p 5000:5000 --memory 16g --cpus 8 \
  mcr.microsoft.com/azure-cognitive-services/speechservices/speech-to-text:latest \
  Eula=accept Billing=$BILLING ApiKey=$API_KEY

# Run TTS (port 5001)
docker run --rm -it -p 5001:5000 --memory 16g --cpus 8 \
  mcr.microsoft.com/azure-cognitive-services/speechservices/neural-text-to-speech:latest \
  Eula=accept Billing=$BILLING ApiKey=$API_KEY
```
