import os
import asyncio
import streamlit as st
from openai import AsyncAzureOpenAI

from realtime.client import RealtimeClient
from realtime.tools import tools

from uuid import uuid4
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("StreamlitRealtimeApp")

# Initialize OpenAI Client
client = AsyncAzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_API_KEY"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
    azure_deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
    api_version="2024-10-01-preview"
)

# Global system prompt
system_prompt = """Provide helpful and empathetic support responses to customer inquiries for ShopMe...

[TRUNCATED for brevity, you'd paste your full prompt here]

"""

# Helper function to initialize RealtimeClient
async def setup_openai_realtime():
    """
    Instantiate and configure the RealtimeClient with tools and event handlers.
    """
    openai_realtime = RealtimeClient(system_prompt=system_prompt)
    st.session_state["track_id"] = str(uuid4())
    st.session_state["openai_realtime"] = openai_realtime

    async def handle_conversation_updated(event):
        # Optional: handle streaming audio here if Streamlit supports it
        pass

    async def handle_item_completed(event):
        try:
            item = event.get("item")
            if item:
                transcript = item.get("formatted", {}).get("transcript", "")
                if transcript:
                    st.chat_message("assistant").markdown(transcript)
        except Exception as e:
            logger.error(f"Error in handle_item_completed: {e}")

    async def handle_conversation_interrupt(event):
        st.session_state["track_id"] = str(uuid4())

    async def handle_input_audio_transcription_completed(event):
        item = event.get("item")
        delta = event.get("delta")
        if delta and 'transcript' in delta:
            transcript = delta['transcript']
            if transcript:
                st.chat_message("user").markdown(transcript)

    async def handle_error(event):
        logger.error(event)

    openai_realtime.on('conversation.updated', handle_conversation_updated)
    openai_realtime.on('conversation.item.completed', handle_item_completed)
    openai_realtime.on('conversation.interrupted', handle_conversation_interrupt)
    openai_realtime.on('conversation.item.input_audio_transcription.completed', handle_input_audio_transcription_completed)
    openai_realtime.on('error', handle_error)

    # Register tools
    coros = [openai_realtime.add_tool(tool_def, tool_handler) for tool_def, tool_handler in tools]
    await asyncio.gather(*coros)

# ---- Streamlit Main App ----

st.set_page_config(page_title="ShopMe Support - Realtime", page_icon="🎧")

st.title("🎧 ShopMe Realtime Support")

# Session setup
if "openai_realtime" not in st.session_state:
    st.session_state["openai_realtime"] = None

# Button to start audio connection
if st.button("🔗 Connect to Realtime API"):
    with st.spinner("Connecting..."):
        if st.session_state["openai_realtime"] is None:
            asyncio.run(setup_openai_realtime())
        openai_realtime: RealtimeClient = st.session_state["openai_realtime"]
        if not openai_realtime.is_connected():
            asyncio.run(openai_realtime.connect())
            st.success("Connected to Realtime API!")
        else:
            st.info("Already connected.")

# Chat input
user_message = st.chat_input("Type your message or use the audio below...")

if user_message:
    openai_realtime: RealtimeClient = st.session_state.get("openai_realtime")
    if openai_realtime and openai_realtime.is_connected():
        asyncio.run(openai_realtime.send_user_message_content([{
            "type": "input_text",
            "text": user_message
        }]))
    else:
        st.error("Please connect first by clicking 'Connect to Realtime API'.")

# Audio input
st.subheader("🎙️ Record your voice (optional)")
audio_file = st.file_uploader("Upload a WAV/PCM16 Audio file for transcription:", type=["wav", "pcm"])

if audio_file is not None:
    audio_bytes = audio_file.read()
    openai_realtime: RealtimeClient = st.session_state.get("openai_realtime")
    if openai_realtime and openai_realtime.is_connected():
        asyncio.run(openai_realtime.append_input_audio(audio_bytes))
        asyncio.run(openai_realtime.create_response())
    else:
        st.error("Please connect first by clicking 'Connect to Realtime API'.")

# Disconnect button
if st.button("🔌 Disconnect"):
    openai_realtime: RealtimeClient = st.session_state.get("openai_realtime")
    if openai_realtime and openai_realtime.is_connected():
        asyncio.run(openai_realtime.disconnect())
        st.success("Disconnected from Realtime API.")
    else:
        st.info("No active connection.")

