<!-- markdownlint-disable MD033 -->

# **🎙️ RTMedAgent: Real-Time Voice Intelligence for Healthcare Workflows**

> This project is **part of the [HLS Ignited Program](https://github.com/microsoft/aihlsIgnited)**, a series of hands-on accelerators designed to democratize AI in healthcare. The program supports providers and payers in building transformative solutions using **Azure AI Services**. Explore other accelerators and discover how AI is reshaping care delivery.

## Table of Contents

- [Overview](#overview)
- [The Healthcare Call Center Challenge](#the-healthcare-call-center-challenge)
- [Solution Architecture](#solution-architecture)
- [Getting Started](#getting-started)
    - [Labs](#labs)
    - [Use Cases](#use-cases)
- [Deployment](#deployment)
- [Resources](#resources)
- [Important Disclaimer](#important-disclaimer)

## Overview

<img src="utils/images/medagent.png" align="right" height="200" style="float:right; height:200px;" />

**RTMedAgent** is a real-time voice agent that enables healthcare organizations to deliver **empathetic and intelligent voice-first experiences** using a cascade of **Azure AI services**. Built for patient-facing support scenarios, the system simulates a smart and responsive voice agent capable of assisting users with everyday healthcare tasks.

### Core Technologies

- **Azure Speech-to-Text** for real-time transcription  
- **Azure AI Search** for semantic understanding and intent recognition  
- **Azure Text-to-Speech** to generate human-like responses  
- **Azure OpenAI with Function Calling and Streaming Output** to dynamically trigger backend actions  
- **WebSocket architecture** to ensure low-latency, two-way voice interaction  

### Healthcare Use Cases

This intelligent voice agent assists with common healthcare workflows including:
- Appointment scheduling
- Prescription refills
- Medication guidance
- Prior authorization evaluations

All interactions maintain high standards for safety, privacy, and clarity.

## The Healthcare Call Center Challenge

> "Healthcare call centers spend, on average, 43% of their annual operating budget on labor costs but only 0.6% on technologies to prevent agent burnout and turnover"  
> — *[The State of Healthcare Call Centers, Hyro](https://assets-002.noviams.com/novi-file-uploads/pac/PDFs-and-Documents/Industry_Partners/Hyro_-_The_State_of_Healthcare_Call_Centers_2023_Report-fa539649.pdf?utm_source=chatgpt.com)*

### Key Challenges

Healthcare call centers face significant operational challenges:

- **High Turnover**: Average call center agent turnover rates range between 30%–45% (QATC study)
- **Staff Burnout**: Limited technology investment leads to agent exhaustion
- **Operational Costs**: High labor costs impact overall budget efficiency
- **Service Quality**: Attrition affects patient satisfaction and care continuity

### AI-Driven Solution

By embracing AI-driven tools like RTMedAgent, healthcare organizations can:
- Enhance operational efficiency
- Reduce staff turnover and burnout
- Improve patient satisfaction
- Optimize resource allocation

## Solution Architecture

![Architecture Diagram](utils/images/arch.png)

The RTMedAgent system orchestrates multiple Azure services into a seamless voice-to-voice experience:

1. **Audio Ingestion**: Stream audio through browser-based WebSocket connection
2. **Speech-to-Text**: Convert live audio into transcribed text using Azure Speech services
3. **AI Processing**: Process patient intent and route queries using Azure OpenAI with Function Calling
4. **Text-to-Speech**: Generate natural, empathetic voice responses in real-time chunks
5. **Safety & Monitoring**: Ensure responsible AI through Azure AI Studio evaluation and monitoring

## Getting Started

### Labs

🧪 **[RTMedAgent Labs](labs/README.md)**

**Building Your Voice-to-Voice Agent with Azure AI Speech and AOAI**
- 📓 [Notebook - Building a Voice-to-Voice Agent with Azure AI Speech](labs/01-build-your-audio-agent.ipynb)

Follow this step-by-step guide to:
- Create a voice-to-voice agent using Azure AI Speech services and Azure OpenAI
- Configure speech recognition and integrate external tools
- Generate human-like responses for real-time interactions

*Perfect for newcomers to Azure AI Speech and Azure OpenAI real-time capabilities.*

### Use Cases

#### 📝 [Voice-to-Voice Experience with RTMedAgent](rtagents/browser_RTMedAgent/README.md)

**Web-Powered AI Assistant for Healthcare**

This use case demonstrates real-time, AI-powered healthcare conversations that transform natural patient voice interactions into structured, actionable outcomes through seamless service orchestration.

*Experienced AI engineers can jump directly to this section or the deployment guide.*

## Deployment

📄 **[Deployment Guide](docs/DeploymentGuide.md)**

For comprehensive instructions covering:
- Infrastructure provisioning
- Application deployment
- SSL certificate configuration
- Production setup best practices

## Resources

### Azure AI Documentation

- **[Azure AI Foundry](https://azure.microsoft.com/en-us/products/ai-foundry/)** – Comprehensive platform for developing and deploying custom AI apps and APIs responsibly
- **[Azure AI Speech Documentation](https://learn.microsoft.com/en-us/azure/ai-services/speech-service/)** – Official documentation covering Speech-to-Text, Text-to-Speech, and Speech Translation capabilities
- **[Azure AI Speech Samples](https://github.com/Azure-Samples/cognitive-services-speech-sdk)** – Sample projects and code snippets for Azure AI Speech SDK

## Important Disclaimer

> [!IMPORTANT]  
> This software is provided for demonstration purposes only. It is not intended to be relied upon for any production workload. The creators of this software make no representations or warranties of any kind, express or implied, about the completeness, accuracy, reliability, suitability, or availability of the software or related content. Any reliance placed on such information is strictly at your own risk.