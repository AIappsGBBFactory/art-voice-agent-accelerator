# from jwt import PyJWKClient, decode, InvalidTokenError
# from fastapi import HTTPException

# def validate_jwt_token(token: str, jwks_url: str, issuer: str, audience: str) -> dict:
#     try:
#         jwks_client = PyJWKClient(jwks_url)
#         signing_key = jwks_client.get_signing_key_from_jwt(token)
#         return decode(
#             token,
#             signing_key.key,
#             algorithms=["RS256"],
#             issuer=issuer,
#             audience=audience,
#         )
#     except InvalidTokenError as e:
#         raise HTTPException(status_code=401, detail=f"Invalid token: {e}")
#     except Exception as e:
#         raise HTTPException(status_code=500, detail=f"Token validation error: {e}")