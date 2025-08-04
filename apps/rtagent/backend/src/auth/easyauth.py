# import base64, json
# from fastapi import Request, HTTPException

# def get_easyauth_identity(request: Request) -> dict:
#     encoded = request.headers.get("x-ms-client-principal")
#     if not encoded:
#         raise HTTPException(status_code=401, detail="Missing EasyAuth header")
#     try:
#         return json.loads(base64.b64decode(encoded).decode("utf-8"))
#     except Exception:
#         raise HTTPException(status_code=400, detail="Invalid EasyAuth header")