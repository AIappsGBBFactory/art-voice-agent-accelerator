"""
auth_utils.py
=============
Utilities for debugging Azure AD authentication and JWT tokens for APIM policy evaluation.
"""

import base64
import json
import logging
import os
from typing import Dict, Optional

from azure.identity import DefaultAzureCredential, ManagedIdentityCredential

logger = logging.getLogger(__name__)


def decode_jwt_payload(token: str) -> Optional[Dict]:
    """
    Decode JWT token payload for debugging purposes.
    Note: This only decodes the payload, it doesn't verify the signature.
    """
    try:
        # JWT structure: header.payload.signature
        parts = token.split(".")
        if len(parts) != 3:
            return None

        # Decode the payload (second part)
        payload = parts[1]

        # Add padding if needed (JWT base64 encoding doesn't use padding)
        padding = 4 - len(payload) % 4
        if padding != 4:
            payload += "=" * padding

        # Decode base64
        decoded_bytes = base64.urlsafe_b64decode(payload)
        payload_json = json.loads(decoded_bytes.decode("utf-8"))

        return payload_json

    except Exception as e:
        logger.error(f"Failed to decode JWT payload: {e}")
        return None


def get_token_info_for_debugging(credential) -> Dict:
    """
    Get token information for debugging APIM policy issues.
    """
    try:
        # Get token for Cognitive Services scope
        token = credential.get_token("https://cognitiveservices.azure.com/.default")

        # Decode the JWT payload
        payload = decode_jwt_payload(token.token)

        info = {
            "token_expires_on": token.expires_on,
            "has_token": bool(token.token),
            "token_length": len(token.token) if token.token else 0,
        }

        if payload:
            # Extract key claims that APIM policies typically check
            info.update(
                {
                    "aud": payload.get("aud", "Not found"),  # Audience
                    "iss": payload.get("iss", "Not found"),  # Issuer
                    "sub": payload.get("sub", "Not found"),  # Subject
                    "appid": payload.get("appid", "Not found"),  # Application ID
                    "oid": payload.get("oid", "Not found"),  # Object ID
                    "tid": payload.get("tid", "Not found"),  # Tenant ID
                    "scp": payload.get("scp", "Not found"),  # Scopes
                    "roles": payload.get("roles", "Not found"),  # Roles
                    "exp": payload.get("exp", "Not found"),  # Expiration
                    "iat": payload.get("iat", "Not found"),  # Issued at
                }
            )

        return info

    except Exception as e:
        logger.error(f"Failed to get token info: {e}")
        return {"error": str(e)}


def validate_azure_openai_auth_setup() -> Dict:
    """
    Validate Azure OpenAI authentication setup for APIM compatibility.
    """
    validation_results = {
        "environment_variables": {},
        "credential_chain": [],
        "token_validation": {},
        "recommendations": [],
    }

    # Check environment variables
    env_vars = {
        "AZURE_CLIENT_ID": os.getenv("AZURE_CLIENT_ID"),
        "AZURE_TENANT_ID": os.getenv("AZURE_TENANT_ID"),
        "AZURE_CLIENT_SECRET": os.getenv("AZURE_CLIENT_SECRET"),
        "AZURE_OPENAI_ENDPOINT": os.getenv("AZURE_OPENAI_ENDPOINT"),
        "AZURE_OPENAI_KEY": os.getenv("AZURE_OPENAI_KEY"),
    }

    validation_results["environment_variables"] = {
        k: "Set" if v else "Not set" for k, v in env_vars.items()
    }

    # Test credential chain
    try:
        if env_vars["AZURE_CLIENT_ID"]:
            # Try user-assigned managed identity
            try:
                credential = ManagedIdentityCredential(
                    client_id=env_vars["AZURE_CLIENT_ID"]
                )
                token_info = get_token_info_for_debugging(credential)
                validation_results["credential_chain"].append(
                    {
                        "type": "ManagedIdentityCredential (user-assigned)",
                        "status": "Success",
                        "token_info": token_info,
                    }
                )
            except Exception as e:
                validation_results["credential_chain"].append(
                    {
                        "type": "ManagedIdentityCredential (user-assigned)",
                        "status": f"Failed: {str(e)}",
                    }
                )

        # Try DefaultAzureCredential
        try:
            credential = DefaultAzureCredential()
            token_info = get_token_info_for_debugging(credential)
            validation_results["credential_chain"].append(
                {
                    "type": "DefaultAzureCredential",
                    "status": "Success",
                    "token_info": token_info,
                }
            )
        except Exception as e:
            validation_results["credential_chain"].append(
                {"type": "DefaultAzureCredential", "status": f"Failed: {str(e)}"}
            )

    except Exception as e:
        validation_results["credential_chain"].append(
            {"error": f"Credential chain validation failed: {str(e)}"}
        )

    # Generate recommendations
    recommendations = []

    if not env_vars["AZURE_CLIENT_ID"]:
        recommendations.append(
            "Set AZURE_CLIENT_ID to use user-assigned managed identity for more predictable JWT claims"
        )

    if not env_vars["AZURE_TENANT_ID"]:
        recommendations.append(
            "Set AZURE_TENANT_ID for explicit tenant specification in JWT tokens"
        )

    if env_vars["AZURE_OPENAI_KEY"]:
        recommendations.append(
            "Consider using managed identity instead of API key for better APIM policy integration"
        )

    # Check token claims for APIM compatibility
    successful_tokens = [
        chain["token_info"]
        for chain in validation_results["credential_chain"]
        if chain.get("status") == "Success" and "token_info" in chain
    ]

    if successful_tokens:
        token = successful_tokens[0]  # Use the first successful token

        if token.get("aud") != "https://cognitiveservices.azure.com":
            recommendations.append(
                "JWT audience claim should be 'https://cognitiveservices.azure.com' for Azure OpenAI"
            )

        if "appid" not in token or token.get("appid") == "Not found":
            recommendations.append(
                "JWT token missing 'appid' claim - ensure service principal or managed identity is properly configured"
            )

        if "scp" not in token or token.get("scp") == "Not found":
            recommendations.append(
                "JWT token missing 'scp' (scopes) claim - verify token scope includes required permissions"
            )

    validation_results["recommendations"] = recommendations

    return validation_results


def create_apim_debug_headers() -> Dict[str, str]:
    """
    Create headers that can help debug APIM policy evaluation.
    """
    headers = {
        "X-Debug-Auth": "true",
        "X-Auth-Method": "azure-ad",
        "X-Token-Scope": "https://cognitiveservices.azure.com/.default",
    }

    # Add client ID if available
    client_id = os.getenv("AZURE_CLIENT_ID")
    if client_id:
        headers["X-Client-ID"] = client_id

    # Add tenant ID if available
    tenant_id = os.getenv("AZURE_TENANT_ID")
    if tenant_id:
        headers["X-Tenant-ID"] = tenant_id

    return headers


def validate_token_for_apim(credential) -> Dict:
    """
    Validate token for APIM policy compatibility.
    """
    try:
        token = credential.get_token("https://cognitiveservices.azure.com/.default")
        token_info = get_token_info_for_debugging(credential)

        validation = {
            "status": "valid",
            "token_claims": token_info,
            "apim_compatibility": [],
        }

        # Check required claims for APIM
        required_claims = ["aud", "iss", "appid", "tid"]
        missing_claims = []

        for claim in required_claims:
            if claim not in token_info or token_info[claim] == "Not found":
                missing_claims.append(claim)

        if missing_claims:
            validation["apim_compatibility"].append(
                f"Missing claims: {', '.join(missing_claims)}"
            )

        # Check audience
        if token_info.get("aud") != "https://cognitiveservices.azure.com":
            validation["apim_compatibility"].append("Incorrect audience claim")

        # Check if token has required scopes
        scopes = token_info.get("scp", "")
        if not scopes or scopes == "Not found":
            validation["apim_compatibility"].append("Missing or empty scope claims")

        if validation["apim_compatibility"]:
            validation["status"] = "warning"

        return validation

    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "apim_compatibility": ["Token validation failed"],
        }


async def debug_jwt_token() -> Dict:
    """
    Debug JWT token for APIM policy evaluation.
    Returns comprehensive token debugging information.
    """
    debug_info = {
        "token_status": "unknown",
        "credential_chain": [],
        "token_info": {},
        "validation_results": {},
    }

    try:
        # Test credential chain
        credentials = [
            ("ManagedIdentityCredential", ManagedIdentityCredential()),
            ("DefaultAzureCredential", DefaultAzureCredential()),
        ]

        # Add user-assigned managed identity if configured
        client_id = os.getenv("AZURE_CLIENT_ID")
        if client_id:
            credentials.insert(
                0,
                (
                    f"ManagedIdentityCredential({client_id})",
                    ManagedIdentityCredential(client_id=client_id),
                ),
            )

        successful_credential = None

        for cred_name, credential in credentials:
            try:
                token = credential.get_token(
                    "https://cognitiveservices.azure.com/.default"
                )
                token_info = get_token_info_for_debugging(credential)

                debug_info["credential_chain"].append(
                    {"name": cred_name, "status": "Success", "token_info": token_info}
                )

                if successful_credential is None:
                    successful_credential = credential
                    debug_info["token_info"] = token_info
                    debug_info["token_status"] = "valid"

            except Exception as e:
                debug_info["credential_chain"].append(
                    {"name": cred_name, "status": "Failed", "error": str(e)}
                )

        # Validate token for APIM compatibility
        if successful_credential:
            debug_info["validation_results"] = validate_token_for_apim(
                successful_credential
            )
        else:
            debug_info["token_status"] = "failed"
            debug_info["validation_results"] = {
                "status": "failed",
                "error": "No valid credentials found",
            }

    except Exception as e:
        debug_info["token_status"] = "error"
        debug_info["error"] = str(e)
        logger.error(f"JWT token debugging failed: {e}")

    return debug_info
