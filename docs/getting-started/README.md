# :material-rocket: Quick Start Guide

!!! success "Ready in 15 Minutes"
    Get your Real-Time Voice Agent running with Azure Speech Services in just a few steps.

## :material-check-circle: Prerequisites

=== "System Requirements"
    - **Python**: 3.11 or higher
    - **Operating System**: Windows 10+, macOS 10.15+, or Linux
    - **Memory**: Minimum 4GB RAM (8GB recommended)
    - **Network**: Internet connectivity for Azure services

=== "Azure Requirements"
    - **Azure Subscription**: [Create one for free](https://azure.microsoft.com/free/) if you don't have one
    - **Azure CLI**: [Install Azure CLI](https://learn.microsoft.com/en-us/cli/azure/install-azure-cli) for resource management
    
    !!! tip "Microsoft Learn Resources"
        - **[Azure Free Account Setup](https://learn.microsoft.com/en-us/azure/cost-management-billing/manage/create-free-services)** - Step-by-step account creation
        - **[Azure CLI Fundamentals](https://learn.microsoft.com/en-us/cli/azure/get-started-with-azure-cli)** - Essential CLI commands

## :material-microsoft-azure: Azure Speech Services Setup

!!! note "Required Azure Resource"
    Azure Speech Services provides the neural text-to-speech and speech recognition capabilities.

### Step 1: Create Speech Services Resource

=== "Azure Portal"
    1. Navigate to [Azure Portal](https://portal.azure.com)
    2. Click **"Create a resource"**
    3. Search for **"Speech Services"**
    4. Select your subscription and resource group
    5. Choose a region (e.g., `East US`, `West Europe`)
    6. Select pricing tier:
        - **F0**: Free tier (good for testing)
        - **S0**: Standard tier (production workloads)

=== "Azure CLI"
    ```bash title="Create Speech Services with Azure CLI"
    # Set your variables
    RESOURCE_GROUP="rg-voice-agent"
    SPEECH_NAME="speech-voice-agent"
    LOCATION="eastus"
    
    # Create resource group
    az group create --name $RESOURCE_GROUP --location $LOCATION
    
    # Create Speech Services resource
    az cognitiveservices account create \
        --name $SPEECH_NAME \
        --resource-group $RESOURCE_GROUP \
        --kind SpeechServices \
        --sku S0 \
        --location $LOCATION
    ```

!!! info "Microsoft Learn Resources"

    - **[Create Speech Services Resource](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/overview#create-a-speech-resource-in-the-azure-portal)** - Detailed setup guide
    - **[Speech Services Pricing](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-services-quotas-and-limits)** - Understand costs and limits

### Step 2: Get Your Credentials

=== "From Azure Portal"
    After creating the resource:
    
    1. Navigate to your Speech Services resource
    2. Go to **"Keys and Endpoint"** in the left menu
    3. Copy **Key 1** (or Key 2) 
    4. Note the **Region** where you created the resource
    5. (Optional) Copy the **Resource ID** for managed identity authentication

=== "From Azure CLI"
    ```bash title="Get Speech Services credentials"
    # Get the access key
    az cognitiveservices account keys list \
        --name $SPEECH_NAME \
        --resource-group $RESOURCE_GROUP
    
    # Get the endpoint and region
    az cognitiveservices account show \
        --name $SPEECH_NAME \
        --resource-group $RESOURCE_GROUP \
        --query "{endpoint:endpoint,location:location}"
    ```

!!! warning "Keep Your Keys Secure"
    Never commit API keys to version control. Use environment variables or Azure Key Vault for production.

## :material-download: Installation

### Step 1: Clone the Repository

```bash title="Clone and navigate to the project"
git clone https://github.com/Azure-Samples/art-voice-agent-accelerator.git
cd art-voice-agent-accelerator
```

### Step 2: Python Environment Setup

!!! tip "Virtual Environment Recommended"
    Always use a virtual environment to avoid dependency conflicts.

=== "Using venv"
    ```bash title="Create and activate virtual environment"
    # Create virtual environment
    python -m venv audioagent
    
    # Activate virtual environment
    source audioagent/bin/activate  # Linux/macOS
    # audioagent\Scripts\activate  # Windows
    ```

=== "Using conda"
    ```bash title="Create conda environment"
    # Create conda environment with Python 3.11
    conda create -n audioagent python=3.11
    
    # Activate environment
    conda activate audioagent
    ```

### Step 3: Install Dependencies

```bash title="Install required packages"
# Core dependencies
pip install -r requirements.txt

# Development dependencies (optional)
pip install -r requirements-dev.txt
```

!!! failure "Installation Issues?"
    If you encounter dependency conflicts:
    
    ```bash
    # Upgrade pip first
    python -m pip install --upgrade pip
    
    # Install with verbose output for debugging
    pip install -r requirements.txt -v
    ```

### Step 4: Environment Configuration

!!! danger "Security Best Practice"
    Never commit `.env` files with real credentials to version control. Use `.env.example` as a template.

=== "Quick Setup"
    ```bash title="Copy and configure environment file"
    # Copy environment template
    cp .env.example .env
    
    # Edit with your preferred editor
    nano .env  # or code .env, vim .env, etc.
    ```

=== "Environment Variables"
    ```bash title="Required environment variables"
    # Azure Speech Services (Required)
    AZURE_SPEECH_KEY=your-speech-key-here
    AZURE_SPEECH_REGION=eastus
    
    # Optional: Custom endpoint
    AZURE_SPEECH_ENDPOINT=https://your-custom-endpoint.cognitiveservices.azure.com
    
    # Optional: For managed identity (production)
    AZURE_SPEECH_RESOURCE_ID=/subscriptions/xxx/resourceGroups/xxx/providers/Microsoft.CognitiveServices/accounts/xxx
    
    # Optional: Audio playback control
    TTS_ENABLE_LOCAL_PLAYBACK=true
    ```

=== "Production Config"
    ```bash title="Production environment variables"
    # Use managed identity instead of API keys
    AZURE_SPEECH_KEY=""  # Leave empty for managed identity
    AZURE_SPEECH_REGION=eastus
    AZURE_SPEECH_RESOURCE_ID=/subscriptions/xxx/resourceGroups/xxx/providers/Microsoft.CognitiveServices/accounts/xxx
    USE_MANAGED_IDENTITY=true
    
    # Enhanced security
    TTS_ENABLE_LOCAL_PLAYBACK=false  # Headless deployment
    LOG_LEVEL=INFO
    ENVIRONMENT=production
    ```

!!! info "Microsoft Learn Resources"

    - **[Azure Managed Identity](https://learn.microsoft.com/en-us/azure/active-directory/managed-identities-azure-resources/overview)** - Credential-less authentication
    - **[Azure Key Vault](https://learn.microsoft.com/en-us/azure/key-vault/general/overview)** - Secure secret management

## :material-flask: Testing Your Setup

!!! success "Quick Verification"
    Run these tests to ensure everything is working correctly.

### Step 1: Environment Test

```bash title="Test Azure Speech Services connection"
# Navigate to the project directory
cd art-voice-agent-accelerator

# Run the connection test
python -c "
from src.speech.text_to_speech import SpeechSynthesizer
import os
print('Testing Azure Speech Services connection...')
synthesizer = SpeechSynthesizer(
    key=os.getenv('AZURE_SPEECH_KEY'),
    region=os.getenv('AZURE_SPEECH_REGION')
)
if synthesizer.validate_configuration():
    print('✅ Azure Speech Services connection successful')
else:
    print('❌ Connection failed - check your credentials')
"
```

### Step 2: Text-to-Speech Test

=== "Basic TTS Test"
    ```python title="Test TTS functionality" linenums="1"
    from src.speech.text_to_speech import SpeechSynthesizer
    import os
    
    # Initialize synthesizer
    synthesizer = SpeechSynthesizer(
        key=os.getenv('AZURE_SPEECH_KEY'),
        region=os.getenv('AZURE_SPEECH_REGION'),
        voice="en-US-JennyMultilingualNeural"
    )
    
    # Test synthesis
    try:
        audio_data = synthesizer.synthesize_speech(
            "Hello! Your voice agent is working perfectly.",
            style="chat",
            rate="+10%"
        )
        
        if audio_data:
            print(f"✅ TTS Test: SUCCESS - Generated {len(audio_data)} bytes")
            
            # Save test audio
            with open("test_output.wav", "wb") as f:
                f.write(audio_data)
            print("💾 Audio saved to test_output.wav")
        else:
            print("❌ TTS Test: FAILED - No audio data generated")
    except Exception as e:
        print(f"❌ TTS Test: ERROR - {e}")
    ```

=== "Streaming Test"
    ```python title="Test real-time streaming"
    # Test streaming frames
    frames = synthesizer.synthesize_to_base64_frames(
        "This is a streaming audio test",
        sample_rate=16000
    )
    
    print(f"✅ Generated {len(frames)} streaming frames")
    for i, frame in enumerate(frames[:3]):  # Show first 3 frames
        print(f"Frame {i}: {frame[:50]}...")
    ```

### Step 3: Audio Playback Test (Optional)

```python title="Test local audio playback"
# Only run if TTS_ENABLE_LOCAL_PLAYBACK=true
import os
if os.getenv('TTS_ENABLE_LOCAL_PLAYBACK', '').lower() == 'true':
    synthesizer.start_speaking_text(
        "Testing local audio playback!",
        voice="en-US-AriaNeural",
        style="excited"
    )
    print("🔊 Audio should be playing through your speakers")
else:
    print("🔇 Local playback disabled - test skipped")
```

## :material-arrow-right: Next Steps

!!! success "You're Ready!"
    Congratulations! Your Real-Time Voice Agent is now set up and running.

### Learning Path

=== "Developers"
    **Start Building Your Voice Agent**:
    
    1. **[Configuration Guide](configuration.md)** - Advanced configuration options
    2. **[API Reference](../api/README.md)** - Complete API documentation
    3. **[Architecture Overview](../architecture/README.md)** - Understand the system design
    4. **[Examples & Samples](../examples/README.md)** - Practical implementation examples
    
    **Microsoft Learn Resources**:
    
    - **[Build Speech Apps with Azure](https://learn.microsoft.com/en-us/training/paths/build-speech-applications/)** - Complete learning path
    - **[Speech Service SDK Quickstart](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/get-started-speech-to-text)** - Deep dive tutorials

=== "Architects"
    **Design Your Solution**:
    
    1. **[Data Flow Patterns](../architecture/data-flows.md)** - Processing pipeline architecture
    2. **[Azure Integration Patterns](../architecture/integrations.md)** - Service integration strategies
    3. **[Communication Services](../architecture/acs-flows.md)** - Telephony and WebRTC flows
    4. **[Load Testing Guide](../operations/load-testing.md)** - Scale and performance planning
    
    **Microsoft Learn Resources**:
    - **[Azure Architecture Center](https://learn.microsoft.com/en-us/azure/architecture/)** - Architecture patterns and best practices
    - **[Well-Architected Framework](https://learn.microsoft.com/en-us/azure/well-architected/)** - Design principles for Azure solutions

=== "Operations"
    **Deploy and Monitor**:
    
    1. **[Production Deployment](../deployment/production.md)** - Production deployment strategies
    2. **[Monitoring & Observability](../operations/monitoring.md)** - Application monitoring setup
    3. **[CI/CD Pipeline](../deployment/cicd.md)** - Automated deployment workflows
    4. **[Troubleshooting Guide](../operations/troubleshooting.md)** - Common issues and solutions
    
    **Microsoft Learn Resources**:
    - **[Azure Monitor](https://learn.microsoft.com/en-us/training/paths/manage-azure-monitor/)** - Monitoring and diagnostics
    - **[Azure DevOps](https://learn.microsoft.com/en-us/training/paths/evolve-your-devops-practices/)** - CI/CD best practices


### Community & Support

!!! info "Get Help & Share Knowledge"
    - **[GitHub Issues](https://github.com/Azure-Samples/art-voice-agent-accelerator/issues)** - Report bugs and request features
    - **[Discussions](https://github.com/Azure-Samples/art-voice-agent-accelerator/discussions)** - Community Q&A
    - **[Microsoft Q&A](https://learn.microsoft.com/en-us/answers/topics/azure-speech.html)** - Official Microsoft support forum
    - **[Azure Speech Discord](https://discord.gg/azure-speech)** - Real-time community chat

---

*Happy building! Your voice-powered applications await.* :material-microphone:

## :material-tools: Troubleshooting

!!! warning "Common Issues"
    Here are the most frequent setup problems and their solutions.

### Authentication Issues

=== "Invalid API Key"
    **Error**: `401 Unauthorized` or `403 Forbidden`
    
    **Solutions**:
    ```bash title="Verify your credentials"
    # Check if your key is valid
    az cognitiveservices account keys list \
        --name your-speech-resource \
        --resource-group your-resource-group
    
    # Test the key with curl
    curl -X POST "https://YOUR_REGION.tts.speech.microsoft.com/cognitiveservices/v1" \
         -H "Ocp-Apim-Subscription-Key: YOUR_KEY" \
         -H "Content-Type: application/ssml+xml" \
         -H "X-Microsoft-OutputFormat: audio-16khz-128kbitrate-mono-mp3" \
         --data-raw "<speak version='1.0' xml:lang='en-US'><voice xml:lang='en-US' xml:gender='Female' name='en-US-JennyNeural'>Hello World!</voice></speak>"
    ```

=== "Wrong Region"
    **Error**: `ResourceNotFound` or connection timeouts
    
    **Solution**: Verify your region matches your resource location:
    ```bash title="Check resource region"
    az cognitiveservices account show \
        --name your-speech-resource \
        --resource-group your-resource-group \
        --query "location"
    ```

### Installation Issues

=== "Python Version"
    **Error**: Version compatibility issues
    
    **Solution**:
    ```bash title="Verify Python version"
    python --version  # Should be 3.11+
    
    # Create fresh environment with correct version
    python -m venv audioagent
    source audioagent/bin/activate
    pip install -r requirements.txt
    ```

=== "Import Errors"
    **Error**: `ModuleNotFoundError`
    
    **Solution**:
    ```bash title="Check installation"
    # Ensure all dependencies installed
    pip install -r requirements.txt
    
    # Test import
    python -c "import src.speech.text_to_speech; print('✅ Import successful')"
    ```

### Network & Hardware Issues

=== "Network Connectivity"
    **Issues**: Connection timeouts, SSL errors
    
    **Requirements**:
    - Outbound HTTPS (port 443) access to Azure endpoints
    - Firewall rules allowing `*.cognitiveservices.azure.com`
    - Check proxy settings if in corporate environment

=== "Audio Hardware"
    **Issue**: No audio output or distorted sound
    
    **Solution**:
    ```python title="Check audio environment"
    from src.speech.text_to_speech import _is_headless
    print(f"Headless environment: {_is_headless()}")
    
    # Test system audio (macOS)
    # say "Audio test"
    ```

!!! info "Microsoft Learn Resources"
    - **[Speech Services Troubleshooting](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/troubleshooting)** - Official troubleshooting guide
    - **[Network Requirements](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/speech-container-howto#the-host-computer)** - Connectivity requirements