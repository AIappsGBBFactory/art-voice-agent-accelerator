import { useCallback, useRef } from 'react';

const WORKLET_SOURCE = `
  class PcmSink extends AudioWorkletProcessor {
    constructor() {
      super();
      this.queue = [];
      this.samplesProcessed = 0;
      this.port.onmessage = (e) => {
        const data = e.data || {};
        if (data.type === 'push' && data.payload) {
          this.queue.push({
            buffer: data.payload,
            messageId: data.messageId || null,
            offset: 0,
          });
        } else if (data.type === 'clear') {
          this.queue = [];
          this.samplesProcessed = 0;
          this.port.postMessage({ type: 'cleared' });
        }
      };
    }
    process(inputs, outputs) {
      const out = outputs[0][0];
      let i = 0;
      while (i < out.length) {
        if (this.queue.length === 0) {
          for (; i < out.length; i++) out[i] = 0;
          break;
        }
        const chunk = this.queue[0];
        const buffer = chunk.buffer;
        const start = chunk.offset || 0;
        const remain = buffer.length - start;
        if (remain <= 0) {
          this.queue.shift();
          continue;
        }
        const toCopy = Math.min(remain, out.length - i);
        out.set(buffer.subarray(start, start + toCopy), i);
        i += toCopy;
        chunk.offset = start + toCopy;
        this.samplesProcessed += toCopy;
        if (chunk.messageId) {
          this.port.postMessage({
            type: 'played',
            messageId: chunk.messageId,
            samples: toCopy,
          });
        }
        if (chunk.offset >= buffer.length) {
          this.queue.shift();
        }
      }
      return true;
    }
  }
  registerProcessor('pcm-sink', PcmSink);
`;

const createAudioContext = () => new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });

/**
 * Provides reusable helpers for real-time microphone capture and PCM playback.
 */
export const useAudioStreams = ({ appendLog, onAudioLevel, onAudioFrame } = {}) => {
  const audioContextRef = useRef(null);
  const processorRef = useRef(null);
  const analyserRef = useRef(null);
  const micStreamRef = useRef(null);
  const playbackAudioContextRef = useRef(null);
  const pcmSinkRef = useRef(null);
  const workletMessageHandlerRef = useRef(null);

  const initializeAudioPlayback = useCallback(async () => {
    if (playbackAudioContextRef.current) {
      return playbackAudioContextRef.current;
    }

    try {
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const workletBlob = new Blob([WORKLET_SOURCE], { type: 'text/javascript' });
      await audioCtx.audioWorklet.addModule(URL.createObjectURL(workletBlob));

      const sink = new AudioWorkletNode(audioCtx, 'pcm-sink', {
        numberOfInputs: 0,
        numberOfOutputs: 1,
        outputChannelCount: [1],
      });

      sink.connect(audioCtx.destination);
      sink.port.onmessage = (event) => {
        const handler = workletMessageHandlerRef.current;
        if (handler) {
          handler(event.data);
        }
      };

      await audioCtx.resume();

      playbackAudioContextRef.current = audioCtx;
      pcmSinkRef.current = sink;

      if (appendLog) {
        appendLog('🔊 Audio playback initialized');
      }
      console.info('AudioWorklet playback system initialized, context sample rate:', audioCtx.sampleRate);
      return audioCtx;
    } catch (error) {
      console.error('Failed to initialize audio playback:', error);
      if (appendLog) {
        appendLog('❌ Audio playback init failed');
      }
      throw error;
    }
  }, [appendLog]);

  const setWorkletMessageHandler = useCallback((handler) => {
    workletMessageHandlerRef.current = handler;
    if (pcmSinkRef.current) {
      pcmSinkRef.current.port.onmessage = (event) => {
        if (handler) {
          handler(event.data);
        }
      };
    }
  }, []);

  const startMicrophone = useCallback(async () => {
    if (audioContextRef.current) {
      return audioContextRef.current;
    }

    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    micStreamRef.current = stream;

    const audioCtx = createAudioContext();
    audioContextRef.current = audioCtx;

    const source = audioCtx.createMediaStreamSource(stream);
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 256;
    analyser.smoothingTimeConstant = 0.3;
    analyserRef.current = analyser;
    source.connect(analyser);

    const bufferSize = 512;
    const processor = audioCtx.createScriptProcessor(bufferSize, 1, 1);
    processorRef.current = processor;
    analyser.connect(processor);

    processor.onaudioprocess = (evt) => {
      const float32 = evt.inputBuffer.getChannelData(0);
      if (!float32) {
        return;
      }

      let sum = 0;
      for (let i = 0; i < float32.length; i += 1) {
        sum += float32[i] * float32[i];
      }
      const rms = Math.sqrt(sum / float32.length);
      const level = Math.min(1, rms * 10);
      if (typeof onAudioLevel === 'function') {
        onAudioLevel(level);
      }

      if (typeof onAudioFrame === 'function') {
        const int16 = new Int16Array(float32.length);
        for (let i = 0; i < float32.length; i += 1) {
          const s = Math.max(-1, Math.min(1, float32[i]));
          int16[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        onAudioFrame({
          float32,
          int16,
          chunkTimestamp: Date.now(),
          level,
        });
      }
    };

    source.connect(processor);
    processor.connect(audioCtx.destination);

    return audioCtx;
  }, [onAudioFrame, onAudioLevel]);

  const stopMicrophone = useCallback(() => {
    const processor = processorRef.current;
    if (processor) {
      try {
        processor.disconnect();
      } catch (error) {
        console.warn('Processor disconnect failed', error);
      }
      processorRef.current = null;
    }

    const audioCtx = audioContextRef.current;
    if (audioCtx) {
      try {
        audioCtx.close();
      } catch (error) {
        console.warn('AudioContext close failed', error);
      }
      audioContextRef.current = null;
    }

    const stream = micStreamRef.current;
    if (stream) {
      stream.getTracks().forEach((track) => track.stop());
      micStreamRef.current = null;
    }

    const analyser = analyserRef.current;
    if (analyser) {
      try {
        analyser.disconnect();
      } catch (error) {
        console.warn('Analyser disconnect failed', error);
      }
      analyserRef.current = null;
    }
  }, []);

  const stopPlayback = useCallback(() => {
    const sink = pcmSinkRef.current;
    if (sink) {
      try {
        sink.disconnect();
      } catch (error) {
        console.warn('PCM sink disconnect failed', error);
      }
      pcmSinkRef.current = null;
    }

    const audioCtx = playbackAudioContextRef.current;
    if (audioCtx) {
      try {
        audioCtx.close();
      } catch (error) {
        console.warn('Playback context close failed', error);
      }
      playbackAudioContextRef.current = null;
    }
  }, []);

  return {
    initializeAudioPlayback,
    startMicrophone,
    stopMicrophone,
    stopPlayback,
    setWorkletMessageHandler,
    playbackAudioContextRef,
    pcmSinkRef,
  };
};
