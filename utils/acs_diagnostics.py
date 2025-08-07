#!/usr/bin/env python3
"""
Azure Communication Services (ACS) Diagnostics and Fix Tool

This script helps diagnose and resolve ACS authentication and permission issues.
It checks the current ACS configuration, credentials, and provides guidance on resolving common issues.
"""

import json
import logging
import os

from azure.communication.callautomation import CallAutomationClient
from azure.core.exceptions import ClientAuthenticationError, HttpResponseError
from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

# Set up logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


class AcsDiagnostics:
    def __init__(self):
        self.acs_connection_string = os.getenv("ACS_CONNECTION_STRING")
        self.acs_endpoint = os.getenv("ACS_ENDPOINT")
        self.source_phone_number = os.getenv("ACS_SOURCE_PHONE_NUMBER")
        self.callback_url = os.getenv("BASE_URL")
        self.backend_url = os.getenv("BACKEND_APP_SERVICE_URL")

        self.credential = self._get_credential()

    def _get_credential(self):
        """Get the appropriate Azure credential."""
        try:
            # Try managed identity first if we're in Azure
            if os.getenv("WEBSITE_SITE_NAME") or os.getenv("CONTAINER_APP_NAME"):
                logger.info(
                    "Using ManagedIdentityCredential for Azure-hosted environment"
                )
                return ManagedIdentityCredential()
        except Exception as e:
            logger.debug(f"ManagedIdentityCredential not available: {e}")

        logger.info("Using DefaultAzureCredential")
        return DefaultAzureCredential()

    def check_environment_variables(self):
        """Check if all required environment variables are set."""
        logger.info("🔍 Checking environment variables...")

        required_vars = {
            "ACS_CONNECTION_STRING": self.acs_connection_string,
            "ACS_ENDPOINT": self.acs_endpoint,
            "ACS_SOURCE_PHONE_NUMBER": self.source_phone_number,
            "BASE_URL": self.callback_url,
        }

        missing_vars = []
        for var_name, var_value in required_vars.items():
            if not var_value:
                missing_vars.append(var_name)
                logger.warning(f"❌ {var_name} is not set")
            else:
                if var_name == "ACS_CONNECTION_STRING":
                    # Don't log the full connection string for security
                    logger.info(
                        f"✅ {var_name} is set (endpoint: {var_value.split(';')[0] if ';' in var_value else 'unknown'})"
                    )
                else:
                    logger.info(f"✅ {var_name}: {var_value}")

        if missing_vars:
            logger.error(
                f"❌ Missing required environment variables: {', '.join(missing_vars)}"
            )
            return False

        return True

    def test_acs_authentication(self):
        """Test ACS authentication."""
        logger.info("🔐 Testing ACS authentication...")

        try:
            # Try connection string first if available
            if self.acs_connection_string:
                logger.info("Testing with connection string...")
                client = CallAutomationClient.from_connection_string(
                    self.acs_connection_string
                )
            elif self.acs_endpoint:
                logger.info("Testing with managed identity...")
                # Ensure endpoint has proper format
                if not self.acs_endpoint.startswith("https://"):
                    endpoint = f"https://{self.acs_endpoint}"
                else:
                    endpoint = self.acs_endpoint
                client = CallAutomationClient(
                    endpoint=endpoint, credential=self.credential
                )
            else:
                logger.error(
                    "❌ Neither ACS_CONNECTION_STRING nor ACS_ENDPOINT is available"
                )
                return False

            # Test basic client functionality
            logger.info("✅ ACS client created successfully")
            return True

        except ClientAuthenticationError as e:
            logger.error(f"❌ Authentication failed: {e}")
            return False
        except Exception as e:
            logger.error(f"❌ Failed to create ACS client: {e}")
            return False

    def validate_phone_number_format(self):
        """Validate phone number format."""
        logger.info("📞 Validating phone number format...")

        if not self.source_phone_number:
            logger.error("❌ ACS_SOURCE_PHONE_NUMBER is not set")
            return False

        # Check E.164 format
        if not self.source_phone_number.startswith("+"):
            logger.error(
                f"❌ Phone number must start with '+': {self.source_phone_number}"
            )
            return False

        # Remove '+' and check if remaining is digits
        number_part = self.source_phone_number[1:]
        if not number_part.isdigit():
            logger.error(
                f"❌ Phone number contains non-digit characters: {self.source_phone_number}"
            )
            return False

        if len(number_part) < 10 or len(number_part) > 15:
            logger.error(
                f"❌ Phone number length invalid (should be 10-15 digits): {self.source_phone_number}"
            )
            return False

        logger.info(f"✅ Phone number format is valid: {self.source_phone_number}")
        return True

    def check_callback_url(self):
        """Check if callback URL is properly configured."""
        logger.info("🌐 Checking callback URL configuration...")

        if not self.callback_url:
            logger.error("❌ BASE_URL is not set")
            return False

        if not self.callback_url.startswith("https://"):
            logger.warning(f"⚠️ Callback URL should use HTTPS: {self.callback_url}")

        # Check if it's a localhost or dev tunnel URL
        if (
            "localhost" in self.callback_url
            or "devtunnels" in self.callback_url
            or "127.0.0.1" in self.callback_url
        ):
            logger.warning(
                "⚠️ Using development URL. Ensure it's accessible from Azure Communication Services."
            )

        logger.info(f"✅ Callback URL: {self.callback_url}")
        return True

    def suggest_fixes(self):
        """Suggest fixes for common ACS issues."""
        logger.info("\n🔧 ACS Configuration Fix Suggestions:")

        # 1. Connection String Issues
        if not self.acs_connection_string:
            logger.info("\n1. Missing ACS Connection String:")
            logger.info("   Get your connection string from Azure Portal:")
            logger.info(
                "   az communication list-key --name <acs-resource-name> --resource-group <rg-name>"
            )
            logger.info(
                "   Then set: ACS_CONNECTION_STRING=endpoint=https://...;accesskey=..."
            )

        # 2. Managed Identity Issues
        if not self.acs_connection_string and self.acs_endpoint:
            logger.info("\n2. Managed Identity Configuration:")
            logger.info(
                "   Ensure your application has a managed identity and proper permissions:"
            )
            logger.info("   az role assignment create \\")
            logger.info("     --assignee <managed-identity-principal-id> \\")
            logger.info("     --role 'Communication Service Contributor' \\")
            logger.info("     --scope <acs-resource-id>")

        # 3. Phone Number Issues
        logger.info("\n3. Phone Number Configuration:")
        logger.info("   Ensure your phone number is:")
        logger.info("   • Purchased through Azure Communication Services")
        logger.info("   • In E.164 format (e.g., +1234567890)")
        logger.info("   • Assigned to your ACS resource")
        logger.info(
            "   Check with: az communication phonenumber list --connection-string '<connection-string>'"
        )

        # 4. Callback URL Issues
        logger.info("\n4. Callback URL Configuration:")
        logger.info("   Ensure your callback URL:")
        logger.info("   • Is publicly accessible from Azure")
        logger.info("   • Uses HTTPS in production")
        logger.info("   • Has a valid SSL certificate")
        logger.info("   • Can handle POST requests with ACS event data")

        # 5. Common 403 Error Fixes
        logger.info("\n5. Common 403 Error Fixes:")
        logger.info("   DiagCode 403#510403 typically means:")
        logger.info("   • Invalid or expired access key")
        logger.info("   • Insufficient permissions on ACS resource")
        logger.info("   • Phone number not properly configured")
        logger.info("   • ACS resource in different region than expected")

    def create_acs_test_call_config(self):
        """Create a test configuration for ACS calls."""
        logger.info("\n🧪 Creating test call configuration...")

        test_config = {
            "source_number": self.source_phone_number,
            "callback_url": (
                f"{self.callback_url}/api/acs-callback" if self.callback_url else None
            ),
            "websocket_url": (
                f"{self.callback_url.replace('https://', 'wss://').replace('http://', 'ws://')}/ws/transcription"
                if self.callback_url
                else None
            ),
            "acs_connection_string": (
                "***hidden***" if self.acs_connection_string else None
            ),
            "acs_endpoint": (
                f"https://{self.acs_endpoint}"
                if self.acs_endpoint and not self.acs_endpoint.startswith("https://")
                else self.acs_endpoint
            ),
        }

        logger.info("Test configuration:")
        for key, value in test_config.items():
            if value:
                logger.info(f"  {key}: {value}")
            else:
                logger.warning(f"  {key}: ❌ NOT SET")

        return test_config

    def run_diagnostics(self):
        """Run all diagnostic checks."""
        logger.info("🚀 Starting ACS Diagnostics...")
        logger.info("=" * 50)

        # Check environment variables
        env_check = self.check_environment_variables()

        # Test authentication
        auth_check = self.test_acs_authentication()

        # Validate phone number
        phone_check = self.validate_phone_number_format()

        # Check callback URL
        callback_check = self.check_callback_url()

        # Create test configuration
        self.create_acs_test_call_config()

        # Provide suggestions
        self.suggest_fixes()

        # Summary
        logger.info("\n📋 Diagnostic Summary:")
        logger.info(f"   Environment Variables: {'✅' if env_check else '❌'}")
        logger.info(f"   Authentication: {'✅' if auth_check else '❌'}")
        logger.info(f"   Phone Number: {'✅' if phone_check else '❌'}")
        logger.info(f"   Callback URL: {'✅' if callback_check else '❌'}")

        if all([env_check, auth_check, phone_check, callback_check]):
            logger.info("\n🎉 All checks passed! Your ACS configuration looks good.")
        else:
            logger.info("\n⚠️ Some issues found. Please review the suggestions above.")

        return all([env_check, auth_check, phone_check, callback_check])


def main():
    """Main function to run diagnostics."""
    print("Azure Communication Services Diagnostics Tool")
    print("=" * 50)

    diagnostics = AcsDiagnostics()
    success = diagnostics.run_diagnostics()

    return 0 if success else 1


if __name__ == "__main__":
    exit(main())
