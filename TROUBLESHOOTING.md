# Troubleshooting Guide

> **📘 Full Documentation:** For detailed solutions with step-by-step commands, see the [complete troubleshooting guide](docs/operations/troubleshooting.md).

Quick solutions for the most common issues when deploying and running the Real-Time Voice Agent.

---

## Deployment & Provisioning

### `azd` authentication fails with tenant/subscription mismatch

**Error:** `failed to resolve user '...' access to subscription`

**Fix:**

```bash
# Check your current Azure CLI login
az account show

# Re-authenticate azd with the correct tenant
azd auth logout
azd auth login --tenant-id <your-tenant-id-from-above>
```

---

### `jq: command not found` during provisioning

**Fix:** Install jq for your platform:

```bash
# macOS
brew install jq

# Ubuntu/Debian
sudo apt-get install jq

# Windows
winget install jqlang.jq
```

---

### Pre-provision script fails with Docker errors

**Fix:**
1. Ensure Docker Desktop is running: `docker ps`
2. On Windows, use **Git Bash** or **WSL** instead of PowerShell
3. Reset if needed: `docker system prune -a`

---

### `MissingSubscriptionRegistration` for Azure providers

**Error:** `The subscription is not registered to use namespace 'Microsoft.Communication'`

**Fix:**
```bash
# Register required providers
az provider register --namespace Microsoft.Communication
az provider register --namespace Microsoft.App
az provider register --namespace Microsoft.CognitiveServices
az provider register --namespace Microsoft.DocumentDB
az provider register --namespace Microsoft.Cache
az provider register --namespace Microsoft.ContainerRegistry

# Check status (wait for "Registered")
az provider show --namespace Microsoft.Communication --query "registrationState"
```

---

### Terraform state lock errors

**Fix:**

```bash
cd infra/terraform
terraform force-unlock <lock-id>

# Or clean and retry
rm -rf .terraform terraform.tfstate*
azd provision
```

---

## ACS & Phone Numbers

### Phone number prompt during deployment

When prompted for a phone number:

- **Option 1:** Enter an existing ACS phone number (E.164 format: `+15551234567`)
- **Option 2:** Skip for now if testing non-telephony features

**To get a phone number:**

1. Azure Portal → Communication Services → Phone numbers → **+ Get**
2. Select country/region and number type
3. Re-run `azd provision` and enter the number

---

### Outbound calls not working

1. Verify ACS connection string is set
2. Check webhook URL is publicly accessible (use `devtunnel` for local dev)
3. Review container logs: `az containerapp logs show --name <app> --resource-group <rg>`

---

## Backend & Runtime

### FastAPI server won't start

```bash
# Check port availability
lsof -ti:8010 | xargs kill -9

# Reinstall dependencies
uv sync

# Run with debug logging
uv run uvicorn apps.artagent.backend.main:app --reload --port 8010 --log-level debug
```

---

### Container Apps unhealthy or restart loop

```bash
# Check authentication
az account show

# View deployment logs
azd logs

# Nuclear option - clean redeploy
azd down --force --purge
azd up
```

---

### Environment variables not propagating

```bash
# Check azd environment
azd env get-values

# Verify container config
az containerapp show --name <app> --resource-group <rg> --query "properties.template.containers[0].env"

# Re-deploy with updated values
azd env set <VAR_NAME> "<value>"
azd deploy
```

---

## Quick Diagnostic Commands

```bash
# Health check
make health_check

# Monitor backend
make monitor_backend_deployment

# Test WebSocket
wscat -c ws://localhost:8010/ws/call/test-id

# Check connectivity
curl -v http://localhost:8010/health
```

---

## Need More Help?

- **Full Troubleshooting Guide:** [docs/operations/troubleshooting.md](docs/operations/troubleshooting.md)
- **Prerequisites:** [docs/getting-started/prerequisites.md](docs/getting-started/prerequisites.md)
- **Deployment Guide:** [docs/deployment/](docs/deployment/)
- **Issues:** [GitHub Issues](https://github.com/Azure-Samples/art-voice-agent-accelerator/issues)
