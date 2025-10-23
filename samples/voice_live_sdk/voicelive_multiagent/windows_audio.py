# windows_audio.py
from __future__ import annotations

import asyncio
import base64
import logging
import queue
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Optional

try:
    import pyaudio
    HAS_PYAUDIO = True
except Exception:
    HAS_PYAUDIO = False

logger = logging.getLogger(__name__)

class WindowsAudioProcessor:
    """
    Minimal, robust Windows-friendly audio processor for VoiceLive:
    - Mic capture → base64 PCM16 → connection.input_audio_buffer.append()
    - Playback ← RESPONSE_AUDIO_DELTA bytes → speakers
    - Clean shutdown & overflow/underflow handling
    """

    def __init__(self, connection):
        if not HAS_PYAUDIO:
            raise RuntimeError("pyaudio not installed; audio unavailable")

        self.connection = connection
        self.audio = pyaudio.PyAudio()

        self.format = pyaudio.paInt16
        self.channels = 1
        self.rate = 24000
        self.chunk_size = 1024

        self.is_capturing = False
        self.is_playing = False
        self._shutdown = threading.Event()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

        self.input_stream = None
        self.output_stream = None

        self._capture_t: Optional[threading.Thread] = None
        self._send_t: Optional[threading.Thread] = None
        self._play_t: Optional[threading.Thread] = None
        self.executor = ThreadPoolExecutor(max_workers=2)

        self.audio_send_q: "queue.Queue[str]" = queue.Queue(maxsize=64)
        self.audio_play_q: "queue.Queue[bytes]" = queue.Queue(maxsize=128)

    # ---------- Capture ----------

    async def start_capture(self):
        if self.is_capturing or self._shutdown.is_set():
            return
        self.loop = asyncio.get_running_loop()
        self.is_capturing = True

        dev = None
        try:
            dev = self.audio.get_default_input_device_info()
        except Exception:
            # fallback: first device with input channels
            for i in range(self.audio.get_device_count()):
                info = self.audio.get_device_info_by_index(i)
                if info.get("maxInputChannels", 0) > 0:
                    dev = info
                    break
        if not dev:
            raise RuntimeError("No audio input device available")

        self.input_stream = self.audio.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            input_device_index=dev.get("index"),
            frames_per_buffer=self.chunk_size,
            start=True,
        )

        self._capture_t = threading.Thread(target=self._capture_loop, name="Capture", daemon=True)
        self._capture_t.start()

        self._send_t = threading.Thread(target=self._send_loop, name="CaptureSend", daemon=True)
        self._send_t.start()

        logger.info("Audio capture started @ %s Hz", self.rate)

    def _capture_loop(self):
        while self.is_capturing and not self._shutdown.is_set():
            try:
                data = self.input_stream.read(self.chunk_size, exception_on_overflow=False)
                b64 = base64.b64encode(data).decode("utf-8")
                try:
                    self.audio_send_q.put(b64, timeout=0.05)
                except queue.Full:
                    # drop frame
                    pass
            except Exception as e:
                logger.warning("Capture read error: %s", e)
                break
        logger.info("Capture loop ended")

    def _send_loop(self):
        while self.is_capturing and not self._shutdown.is_set():
            try:
                b64 = self.audio_send_q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                if self.loop and not self.loop.is_closed():
                    asyncio.run_coroutine_threadsafe(
                        self.connection.input_audio_buffer.append(audio=b64), self.loop
                    )
            except Exception as e:
                logger.debug("Send error (ignored): %s", e)
        logger.info("Capture send loop ended")

    async def stop_capture(self):
        if not self.is_capturing:
            return
        self.is_capturing = False
        try:
            if self._capture_t and self._capture_t.is_alive():
                self._capture_t.join(timeout=1.0)
            if self._send_t and self._send_t.is_alive():
                self._send_t.join(timeout=1.0)
        finally:
            if self.input_stream:
                try:
                    self.input_stream.stop_stream()
                except Exception:
                    pass
                try:
                    self.input_stream.close()
                except Exception:
                    pass
                self.input_stream = None
        logger.info("Audio capture stopped")

    # ---------- Playback ----------

    async def start_playback(self):
        if self.is_playing or self._shutdown.is_set():
            return
        self.is_playing = True

        dev = None
        try:
            dev = self.audio.get_default_output_device_info()
        except Exception:
            # fallback: first device with output channels
            for i in range(self.audio.get_device_count()):
                info = self.audio.get_device_info_by_index(i)
                if info.get("maxOutputChannels", 0) > 0:
                    dev = info
                    break
        if not dev:
            raise RuntimeError("No audio output device available")

        self.output_stream = self.audio.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            output=True,
            output_device_index=dev.get("index"),
            frames_per_buffer=self.chunk_size,
            start=True,
        )

        self._play_t = threading.Thread(target=self._play_loop, name="Playback", daemon=True)
        self._play_t.start()
        logger.info("Audio playback started")

    def _play_loop(self):
        while self.is_playing and not self._shutdown.is_set():
            try:
                data = self.audio_play_q.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                self.output_stream.write(data)
            except Exception as e:
                logger.debug("Playback write error: %s", e)
                break
        logger.info("Playback loop ended")

    async def queue_audio(self, audio_bytes: bytes):
        if not self.is_playing or self._shutdown.is_set():
            return
        try:
            self.audio_play_q.put(audio_bytes, timeout=0.05)
        except queue.Full:
            # drop frame
            pass

    async def stop_playback(self):
        if not self.is_playing:
            return
        self.is_playing = False
        try:
            if self._play_t and self._play_t.is_alive():
                self._play_t.join(timeout=1.0)
        finally:
            if self.output_stream:
                try:
                    self.output_stream.stop_stream()
                except Exception:
                    pass
                try:
                    self.output_stream.close()
                except Exception:
                    pass
                self.output_stream = None
        # drain queue
        while not self.audio_play_q.empty():
            try:
                self.audio_play_q.get_nowait()
            except queue.Empty:
                break
        logger.info("Audio playback stopped")

    # ---------- Cleanup ----------

    async def cleanup(self):
        self._shutdown.set()
        await self.stop_capture()
        await self.stop_playback()
        try:
            self.executor.shutdown(wait=True)
        except Exception:
            pass
        try:
            self.audio.terminate()
        except Exception:
            pass
        logger.info("Audio cleaned up")
