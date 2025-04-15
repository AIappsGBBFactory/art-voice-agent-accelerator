import asyncio
import os
from uuid import uuid4

import chainlit as cl
from dotenv import load_dotenv

from src.realtime_client.client import RealtimeClient
from src.realtime_copy.tools import tools
from voiceagents.testagent.instructions import SYSTEM_PROMPT

# Load environment variables
load_dotenv()

# Configure logging
from chainlit.logger import logger

session_config_path = "voiceagents/testagent/session_config.yaml"

async def setup_openai_realtime(system_prompt: str):
    """Instantiate and configure the OpenAI Realtime Client."""
    openai_realtime = RealtimeClient(system_prompt=system_prompt, session_config_path=session_config_path)
    cl.user_session.set("track_id", str(uuid4()))

    async def handle_conversation_updated(event):
        """Stream audio back to the client during conversation updates."""
        delta = event.get("delta")
        if delta and "audio" in delta:
            await cl.context.emitter.send_audio_chunk(
                cl.OutputAudioChunk(
                    mimeType="pcm16",
                    data=delta["audio"],
                    track=cl.user_session.get("track_id")
                )
            )

    async def handle_item_completed(event):
        """Send the final transcription to the chat once an item is completed."""
        item = event.get("item", {})
        transcript = item.get("formatted", {}).get("transcript", "")
        if transcript:
            await cl.Message(content=transcript).send()

    async def handle_conversation_interrupt(event):
        """Handle conversation interruptions gracefully."""
        cl.user_session.set("track_id", str(uuid4()))
        await cl.context.emitter.send_audio_interrupt()

    async def handle_input_audio_transcription_completed(event):
        """Send interim transcription as user messages."""
        delta = event.get("delta", {})
        transcript = delta.get("transcript")
        if transcript:
            await cl.Message(author="You", type="user_message", content=transcript).send()

    async def handle_error(event):
        """Log errors."""
        logger.error(f"Realtime client error: {event}")

    # Register event handlers
    openai_realtime.on('conversation.updated', handle_conversation_updated)
    openai_realtime.on('conversation.item.completed', handle_item_completed)
    openai_realtime.on('conversation.interrupted', handle_conversation_interrupt)
    openai_realtime.on('conversation.item.input_audio_transcription.completed', handle_input_audio_transcription_completed)
    openai_realtime.on('error', handle_error)

    # Attach to user session
    cl.user_session.set("openai_realtime", openai_realtime)

    # Add tools
    tasks = [openai_realtime.add_tool(tool_def, tool_handler) for tool_def, tool_handler in tools]
    await asyncio.gather(*tasks)

@cl.on_chat_start
async def start():
    """Start a new chat session."""
    await cl.Message(content="Hi, Welcome to ShopMe. How can I help you? Press `P` to talk!").send()
    await setup_openai_realtime(system_prompt=SYSTEM_PROMPT + "\n\nCustomer ID: 12121")

@cl.on_message
async def on_message(message: cl.Message):
    """Handle incoming text messages."""
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime and openai_realtime.is_connected():
        await openai_realtime.send_user_message_content([
            {"type": "input_text", "text": message.content}
        ])
    else:
        await cl.Message(content="⚡ Please activate voice mode before sending messages!").send()

@cl.on_audio_start
async def on_audio_start():
    """Handle the start of a voice session."""
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    try:
        if openai_realtime:
            await openai_realtime.connect()
            logger.info("Connected to OpenAI Realtime")
            return True
    except Exception as e:
        await cl.ErrorMessage(content=f"🚨 Failed to connect to Realtime API: {e}").send()
    return False

@cl.on_audio_chunk
async def on_audio_chunk(chunk: cl.InputAudioChunk):
    """Handle incoming audio chunks."""
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime and openai_realtime.is_connected():
        await openai_realtime.append_input_audio(chunk.data)
        # (Optional) Add a tiny sleep to smooth WebSocket flow
        await asyncio.sleep(0.002)
    else:
        logger.info("RealtimeClient is not connected.")

@cl.on_audio_end
@cl.on_chat_end
@cl.on_stop
async def on_end():
    """Handle the end of a session (chat or audio)."""
    openai_realtime: RealtimeClient = cl.user_session.get("openai_realtime")
    if openai_realtime and openai_realtime.is_connected():
        await openai_realtime.disconnect()
