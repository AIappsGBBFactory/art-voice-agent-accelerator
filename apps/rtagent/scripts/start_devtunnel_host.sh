#!/bin/bash

# ============================================================
# Script: start_devtunnel_host.sh
# Purpose: Host the Azure Dev Tunnel on port 8080.
# ============================================================

: """
🧠 Azure Dev Tunnels – Get Started

This script helps you host an Azure Dev Tunnel for your local FastAPI server.

1. 📦 Prerequisite: Azure CLI must be installed.
   ➤ https://learn.microsoft.com/en-us/cli/azure/install-azure-cli

2. 🧪 First time setup? Run:
   ➤ az extension add --name dev-tunnel

3. 🌐 If tunnel hasn't been created yet, this script will create it:
   ➤ devtunnel create demo-backend --allow-anonymous
   ➤ devtunnel port create demo-backend --port-number 8080 --protocol http

4. 🚀 This script hosts the tunnel:
   ➤ devtunnel host demo-backend

5. 🔗 Once running, copy the generated URL (e.g., https://<id>.dev.tunnels.azure.com)

6. 📝 Then set:
   ➤ backend/.env → BASE_URL=<your-public-url>
   ➤ ACS (Azure Communication Services) → Voice Callback URL = <your-public-url>/api/callback

💬 Dev Tunnels forward HTTP/WebSocket traffic, enabling outbound PSTN calls and remote testing 
    without firewall/NAT changes. Ideal for local development of voice-enabled agents.
"""

set -e

PORT=8080
TUNNEL_NAME="demo-backend"

function check_devtunnel_installed() {
    if ! command -v devtunnel >/dev/null 2>&1; then
        echo "Error: 'devtunnel' CLI tool is not available in your PATH."
        echo "Make sure the Azure CLI dev-tunnel extension is installed:"
        echo "    az extension add --name dev-tunnel"
        exit 1
    fi
}

function create_tunnel_if_needed() {
    echo "Checking if tunnel '$TUNNEL_NAME' exists..."
    
    # Check if tunnel exists
    if ! devtunnel show $TUNNEL_NAME >/dev/null 2>&1; then
        echo "Creating tunnel '$TUNNEL_NAME' with anonymous access..."
        devtunnel create $TUNNEL_NAME --allow-anonymous
        
        echo "Adding port $PORT to tunnel..."
        devtunnel port create $TUNNEL_NAME --port-number $PORT --protocol http
        
        echo "Tunnel '$TUNNEL_NAME' created successfully!"
    else
        echo "Tunnel '$TUNNEL_NAME' already exists."
    fi
}

function host_tunnel() {
    echo "Hosting Azure Dev Tunnel '$TUNNEL_NAME' on port $PORT"
    devtunnel host $TUNNEL_NAME
}

check_devtunnel_installed
create_tunnel_if_needed
host_tunnel
