# from fastapi import Request, WebSocket, HTTPException
# from .shared import validate_jwt_token
# from settings import EVENTGRID_ISSUER, EVENTGRID_AUDIENCE, EVENTGRID_JWKS_URL

# def validate_eventgrid_auth(auth_header: str) -> dict:
#     if not auth_header or not auth_header.startswith("Bearer "):
#         raise HTTPException(401, "Missing/invalid Authorization header")
#     token = auth_header.split()[1]
#     return validate_jwt_token(token, EVENTGRID_JWKS_URL, EVENTGRID_ISSUER, EVENTGRID_AUDIENCE)