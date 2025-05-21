import wave
import pyaudio
import asyncio
from typing import Optional
from usecases.acs_gpt4o_transcribe.app.utils_transcribe import choose_audio_device
import os


class AudioRecorder:
    """
    Async audio recorder using PyAudio.
    Allows independent recording (to memory and .wav) and streaming (for STT).
    """

    def __init__(
        self,
        rate: int,
        channels: int,
        format_: int,
        chunk: int,
        device_index: Optional[int] = None,
    ):
        self.rate = rate
        self.channels = channels
        self.format = format_
        self.chunk = chunk
        self.device_index = (
            device_index if device_index is not None else choose_audio_device()
        )
        self.p = pyaudio.PyAudio()
        self.stream = None
        self.frames = []
        self.audio_queue: asyncio.Queue[bytes] = asyncio.Queue()
        self._loop = asyncio.get_event_loop()
        self._running = False

    def start(self) -> None:
        """
        Start the audio stream and begin capturing to the queue.
        """

        def callback(in_data, frame_count, time_info, status):
            self.frames.append(in_data)
            self._loop.call_soon_threadsafe(self.audio_queue.put_nowait, in_data)
            return (None, pyaudio.paContinue)

        self.stream = self.p.open(
            format=self.format,
            channels=self.channels,
            rate=self.rate,
            input=True,
            input_device_index=self.device_index,
            frames_per_buffer=self.chunk,
            stream_callback=callback,
        )
        self._running = True
        self.stream.start_stream()

    def stop(self) -> None:
        """
        Stop and close the stream, release audio resources.
        """
        self._running = False
        if self.stream is not None:
            self.stream.stop_stream()
            self.stream.close()
        self.p.terminate()

    def save_wav(self, filename: str) -> None:
        """
        Save the recorded audio to a .wav file.
        Ensures there is audio data before saving.
        Creates the output directory if it does not exist.
        """
        if not self.frames:
            print("⚠️ No audio recorded. Nothing to save.")
            return
        directory = os.path.dirname(filename)
        if directory and not os.path.exists(directory):
            os.makedirs(directory, exist_ok=True)
        wf = wave.open(filename, "wb")
        wf.setnchannels(self.channels)
        wf.setsampwidth(self.p.get_sample_size(self.format))
        wf.setframerate(self.rate)
        wf.writeframes(b"".join(self.frames))
        wf.close()
        print(f"🎙️ Audio saved to {filename}")
