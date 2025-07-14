import React, { useEffect, useState, useRef } from 'react';
import styled, { keyframes, css } from 'styled-components';

/* float + pulse as before */
const floatAnim = keyframes`
  0%,100% { transform: translateY(0); }
  50%     { transform: translateY(-8px); }
`;
const pulseAnim = keyframes`
  0%,100% { transform: scale(1); }
  50%     { transform: scale(1.12); }
`;

/* subtle noise */
const noiseOverlay = css`
  &::before {
    content: '';
    position: absolute; top:0; left:0;
    width:100%; height:100%;
    background-image: url("data:image/svg+xml;utf8,\
<svg xmlns='http://www.w3.org/2000/svg'>\
<filter id='noise'><feTurbulence type='fractalNoise' baseFrequency='1.2' numOctaves='2'/></filter>\
<rect width='100%' height='100%' filter='url(%23noise)'/></svg>");
    opacity: 0.04;
    pointer-events: none;
  }
`;

/* glossy, highlighted sphere */
const Sphere = styled.div`
  position: relative;
  width: 120px;
  height: 120px;
  border-radius: 50%;
  background: 
    /* specular highlight */
    radial-gradient(circle at 40% 30%, rgba(255,255,255,0.7), transparent 60%),
    /* main color gradient */
    radial-gradient(circle at 30% 30%, ${p => p.light} 0%, ${p => p.dark} 90%);
  ${noiseOverlay};

  /* deeper shadows for depth */
  box-shadow:
    inset 0 6px 14px rgba(255,255,255,0.3),
    0 10px 20px rgba(0,0,0,0.3);

  /* only float & pulse when speaking */
  ${p => p.speaking && css`
    animation:
      ${floatAnim} 3s ease-in-out infinite,
      ${pulseAnim} 0.6s ease-in-out infinite;
  `}

  /* micro-wobble from mic volume */
  transform:
    scale(${p => 1 + p.volume * 0.25})
    translateY(${p => -5 * p.volume}px);
  transition: transform 0.1s ease-out;
`;

export default function VoiceSphere({
  speaker = 'Assistant',
  active  = false
}) {
  const [volume, setVolume]     = useState(0);
  const [micSpeaking, setMic]   = useState(false);
  const audioRef                = useRef(null);

  useEffect(() => {
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(stream => {
        const ctx      = new AudioContext();
        const analyser = ctx.createAnalyser();
        analyser.fftSize = 256;
        const data     = new Uint8Array(analyser.frequencyBinCount);
        ctx.createMediaStreamSource(stream).connect(analyser);

        const tick = () => {
          analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (let v of data) {
            const n = v/128 - 1;
            sum += n*n;
          }
          const rms = Math.sqrt(sum/data.length);
          setVolume(rms);
          setMic(rms > 0.02);
          requestAnimationFrame(tick);
        };
        tick();
      })
      .catch(() => console.warn('Mic access denied'));
  }, []);

  const themes = {
    User:      { light: '#6ee7b7', dark: '#10b981' },
    Assistant: { light: '#bfdbfe', dark: '#3b82f6' }
  };
  const { light, dark } = themes[speaker] || themes.Assistant;

  const speaking = micSpeaking || active;

  return (
    <Sphere
      ref={audioRef}
      light={light}
      dark={dark}
      volume={volume}
      speaking={speaking}
    />
  );
}
