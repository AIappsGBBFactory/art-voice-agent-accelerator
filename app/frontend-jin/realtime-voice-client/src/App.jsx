import React, { useEffect, useRef, useState } from 'react';
import { AudioConfig, SpeechConfig, SpeechRecognizer } from 'microsoft-cognitiveservices-speech-sdk';

const WS_URL = 'ws://localhost:8010/realtime'; // Update as needed
const AZURE_SPEECH_KEY = '<speech key>';
const AZURE_REGION = '<speech region>>';

export default function RealTimeVoiceApp() {
  const [transcript, setTranscript] = useState('');
  const [log, setLog] = useState('');
  const [recording, setRecording] = useState(false);
  const socketRef = useRef(null);
  const recognizerRef = useRef(null);

  useEffect(() => {
    return () => stopRecognition();
  }, []);

  const appendLog = (message) => {
    setLog(prev => prev + `\n${new Date().toLocaleTimeString()} - ${message}`);
  };

  const startRecognition = async () => {
    const speechConfig = SpeechConfig.fromSubscription(AZURE_SPEECH_KEY, AZURE_REGION);
    speechConfig.speechRecognitionLanguage = 'en-US';
    const audioConfig = AudioConfig.fromDefaultMicrophoneInput();

    const recognizer = new SpeechRecognizer(speechConfig, audioConfig);
    recognizerRef.current = recognizer;

    recognizer.recognizing = (s, e) => {
      setTranscript(prev => prev + '\r' + e.result.text);
    };

    recognizer.recognized = (s, e) => {
      if (e.result.reason === 0) return;
      const text = e.result.text;
      setTranscript(prev => prev + '\nUser: ' + text);
      appendLog('Final transcript received: ' + text);
      sendToBackend(text);
    };

    recognizer.startContinuousRecognitionAsync();
    setRecording(true);
    appendLog('Microphone access and recognition started.');

    const socket = new WebSocket(WS_URL);
    socket.binaryType = 'arraybuffer';
    socketRef.current = socket;

    socket.onopen = () => appendLog('WebSocket connection established.');

    socket.onmessage = async (event) => {
      if (typeof event.data === 'string') {
        if (event.data.includes('processing_started')) {
          appendLog('Backend started processing GPT response.');
        } else if (event.data.includes('interrupt')) {
          appendLog('Backend reported interrupt.');
        } else {
          setTranscript(prev => prev + '\nGPT: ' + event.data);
          appendLog('Received GPT chunk.');
        }
      } else {
        const audioCtx = new AudioContext();
        const arrayBuffer = await event.data.arrayBuffer();
        const audioBuffer = await audioCtx.decodeAudioData(arrayBuffer);
        const source = audioCtx.createBufferSource();
        source.buffer = audioBuffer;
        source.connect(audioCtx.destination);
        source.start();
        appendLog('Received and played audio chunk.');
      }
    };
  };

  const stopRecognition = () => {
    if (recognizerRef.current) {
      recognizerRef.current.stopContinuousRecognitionAsync();
    }
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send('__INTERRUPT__');
      socketRef.current.close();
      appendLog('Sent interrupt to backend and closed WebSocket.');
    }
    setRecording(false);
    appendLog('Stopped recognition.');
  };

  const sendToBackend = (text) => {
    // Stop any ongoing audio playback
    if (window.speechSynthesis) {
      window.speechSynthesis.cancel();
    }

    // Notify backend to cancel any ongoing process
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ cancel: true }));
    }

    // Send the new transcript to the backend
    if (socketRef.current && socketRef.current.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ text }));
      appendLog('Sent transcript to backend.');
    }
  };

  return (
    <div style={{ padding: 20, fontFamily: 'Arial, sans-serif' }}>
      <h1>Real-Time Voice Chat (React + Azure Speech)</h1>
      <button onClick={recording ? stopRecognition : startRecognition}>
        {recording ? 'Stop' : 'Start Talking'}
      </button>

      <h2>Transcript</h2>
      <pre style={{ whiteSpace: 'pre-wrap', backgroundColor: '#f4f4f4', padding: '1em', borderRadius: '5px', border: '1px solid #ccc', color: '#222' }}>{transcript}</pre>

      <h2>Logs</h2>
      <pre style={{ whiteSpace: 'pre-wrap', backgroundColor: '#fef9e7', padding: '1em', borderRadius: '5px', border: '1px solid #ccc', color: '#333' }}>{log}</pre>
    </div>
  );
}
