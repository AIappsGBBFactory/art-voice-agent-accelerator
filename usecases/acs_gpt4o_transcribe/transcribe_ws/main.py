import asyncio
import logging
import json
import base64
import os
from aiohttp import web, WSMsgType
import websockets
from datetime import datetime

# ---------- CONFIGURATION ----------
from usecases.acs_gpt4o_transcribe.transcribe_ws.settings import (
    AZURE_WS_URL,
    AZURE_HEADERS,
    SESSION_CONFIG,
)

LOG_AUDIO = False  # Set to True to log every base64 audio packet to disk

if hasattr(asyncio, "WindowsSelectorEventLoopPolicy"):
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

logger = logging.getLogger("transcribe-relay")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
routes = web.RouteTableDef()


# ---------- UTILITIES ----------
def log_audio_frame(b64_data: str, client_id: str):
    if not LOG_AUDIO:
        return
    out_dir = "audio_logs"
    os.makedirs(out_dir, exist_ok=True)
    filename = f"{out_dir}/{client_id}_{datetime.utcnow().isoformat()}.pcm"
    with open(filename, "ab") as f:
        f.write(base64.b64decode(b64_data))


def generate_client_id():
    return f"client_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}"


# ---------- ROUTES ----------
@routes.get("/health")
async def health(request):
    return web.json_response({"status": "ok"})


@routes.get("/transcribe")
async def transcribe_ws(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    client_id = generate_client_id()
    logger.info(f"[{client_id}] Connected from {request.remote}")

    azure_ws = None
    try:
        # Connect to AOAI
        azure_ws = await websockets.connect(
            AZURE_WS_URL,
            additional_headers=AZURE_HEADERS,
            max_queue=16,
        )
        logger.info(f"[{client_id}] Connected to Azure STT WS")

        # 1. Only send the session config!
        await azure_ws.send(json.dumps(SESSION_CONFIG))
        logger.info(f"[{client_id}] Sent session config")

        # 2. Relay tasks (no audio_start!)
        async def client_to_azure():
            async for msg in ws:
                b64 = None
                if msg.type == WSMsgType.BINARY:
                    b64 = base64.b64encode(msg.data).decode()
                elif msg.type == WSMsgType.TEXT:
                    try:
                        j = json.loads(msg.data)
                        if "audio" in j:
                            b64 = j["audio"]
                    except Exception:
                        logger.warning(f"[{client_id}] Received bad TEXT: {msg.data}")
                        return
                if b64:
                    log_audio_frame(b64, client_id)
                    await azure_ws.send(
                        json.dumps({"type": "input_audio_buffer.append", "audio": b64})
                    )
                elif msg.type == WSMsgType.ERROR:
                    logger.error(f"[{client_id}] Browser WS error: {ws.exception()}")
                    break

        async def azure_to_client():
            async for message in azure_ws:
                logger.debug(f"[{client_id}] AzureWS → Client: {message[:100]}...")
                await ws.send_str(message)

        relay_tasks = [
            asyncio.create_task(client_to_azure()),
            asyncio.create_task(azure_to_client()),
        ]
        done, pending = await asyncio.wait(
            relay_tasks, return_when=asyncio.FIRST_COMPLETED
        )
        for task in pending:
            task.cancel()
        logger.info(f"[{client_id}] Relay finished (one side closed)")

    except Exception as e:
        logger.exception(f"[{client_id}] Error in /transcribe relay: {e}")
    finally:
        if azure_ws:
            await azure_ws.close()
        await ws.close()
        logger.info(f"[{client_id}] Disconnected /transcribe WS")
    return ws


# --------- APP SETUP ---------
app = web.Application()
app.add_routes(routes)
app.router.add_route("OPTIONS", "/{tail:.*}", lambda req: web.Response())

# For gunicorn/uvicorn/production: expose as 'app'
if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=8089)
