#!/bin/bash

# Define the path to your shell profiles
zshrc_path="$HOME/.zshrc"
bashrc_path="$HOME/.bashrc"

echo "🚀 Setting up development environment..."

# Add local bin to PATH
echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$zshrc_path"
echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$bashrc_path"

# Source the current path
export PATH="$HOME/.local/bin:$PATH"

echo "📦 Installing Bicep CLI..."
# Install Bicep CLI
curl -Lo bicep https://github.com/Azure/bicep/releases/latest/download/bicep-linux-x64
chmod +x ./bicep
sudo mv ./bicep /usr/local/bin/bicep

echo "🐍 Setting up Python environment with uv..."
# Sync Python dependencies using uv and pyproject.toml
uv sync --dev

echo "🔧 Installing pre-commit hooks..."
# Install pre-commit hooks
uv run pre-commit install

echo "✅ Verifying tool installations..."
# Verify installations
echo "Azure CLI version:"
az version --output table 2>/dev/null || echo "❌ Azure CLI not found"

echo "Terraform version:"
terraform version 2>/dev/null || echo "❌ Terraform not found"

echo "Azure Developer CLI version:"
azd version 2>/dev/null || echo "❌ Azure Developer CLI not found"

echo "Bicep version:"
bicep --version 2>/dev/null || echo "❌ Bicep not found"

echo "Python environment:"
uv run python --version

echo "🎉 Development environment setup complete!"

# Display helpful commands
echo ""
echo "📋 Useful commands:"
echo "  uv run rtagent                 # Run the application"
echo "  uv run pytest                 # Run tests"
echo "  uv run hatch run lint          # Run linting"
echo "  uv run hatch run format        # Format code"
echo "  uv run hatch run quality       # Run all quality checks"
echo "  az login                       # Login to Azure"
echo "  azd init                       # Initialize Azure Developer CLI"
echo "  terraform init                 # Initialize Terraform"
echo "  bicep build main.bicep         # Build Bicep template"