import React, { useEffect, useState, useRef } from 'react';
import styled, { keyframes, css } from 'styled-components';

/* ---------- Animations & Noise Overlay ---------- */
const floatAnim = keyframes`
  0%,100% { transform: translateY(0); }
  50%     { transform: translateY(-8px); }
`;
const pulseAnim = keyframes`
  0%,100% { transform: scale(1); }
  50%     { transform: scale(1.12); }
`;
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

/* ---------- Main Sphere Styles ---------- */
const BASE_SIZE = 144;
const SIZE = Math.round(BASE_SIZE * 1.2); // ~173px
const Sphere = styled.div`
  position: relative;
  width: ${SIZE}px;
  height: ${SIZE}px;
  border-radius: 50%;
  background:
    radial-gradient(circle at 40% 30%, rgba(255,255,255,0.7), transparent 60%),
    radial-gradient(circle at 30% 30%, ${p => p.light} 0%, ${p => p.dark} 90%);
  ${noiseOverlay};
  box-shadow:
    inset 0 6px 14px rgba(255,255,255,0.3),
    0 10px 20px rgba(0,0,0,0.3);
  ${p => p.speaking && css`
    animation:
      ${floatAnim} 3s ease-in-out infinite,
      ${pulseAnim} 0.6s ease-in-out infinite;
  `}
  transform:
    scale(${p => 1 + p.volume * 0.25})
    translateY(${p => -5 * p.volume}px);
  transition: transform 0.1s ease-out;
`;

/* ---------- Vertical Floating Function-Call Bubble ---------- */
const floatOut = keyframes`
  0% {
    transform: translate(-50%, -50%) scale(0.8);
    opacity: 1;
  }
  50% {
    transform: translate(-50%, -100%) scale(1);
    opacity: 0.8;
  }
  100% {
    transform: translate(-50%, -100%) scale(1);
    opacity: 0;
  }
`;
const FunctionCallBubble = styled.div`
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  max-width: 120px;
  padding: 8px 12px;
  background: rgba(200, 200, 200, 0.9);
  color: #111;
  border-radius: 12px;
  font-size: 0.8rem;
  font-weight: 500;
  pointer-events: none;
  animation: ${floatOut} 6s ease-in-out forwards;

  /* chat-tail arrow */
  &::after {
    content: '';
    position: absolute;
    bottom: -6px;
    left: 16px;
    border-width: 6px;
    border-style: solid;
    border-color: rgba(200,200,200,0.9) transparent transparent transparent;
  }
`;

/* ---------- Center Label (“Agent” / “User”) ---------- */
const Label = styled.div`
  position: absolute;
  top: 50%; left: 50%;
  transform: translate(-50%, -50%);
  color: #FFF;
  font-weight: 600;
  font-size: 1.2rem;
  pointer-events: none;
  text-shadow: 0 0 8px rgba(0,0,0,0.7);
`;

/* ---------- VoiceSphere Component ---------- */
export default function VoiceSphere({
  speaker       = 'Assistant',
  active        = false,
  functionCalls = [],
  resetKey      = null,
}) {
  const [volume, setVolume]   = useState(0);
  const [micSpeaking, setMic] = useState(false);
  const canvasRef             = useRef(null);

  useEffect(() => {
    if (!active) {
      setVolume(0);
      setMic(false);
    }
  }, [active, resetKey]);

  useEffect(() => {
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(stream => {
        const ctx      = new AudioContext();
        const analyser = ctx.createAnalyser(); analyser.fftSize = 256;
        const data     = new Uint8Array(analyser.frequencyBinCount);
        ctx.createMediaStreamSource(stream).connect(analyser);
        const tick = () => {
          analyser.getByteTimeDomainData(data);
          let sum = 0;
          for (const v of data) { const n = v/128 - 1; sum += n*n; }
          const rms = Math.sqrt(sum/data.length);
          setVolume(rms);
          setMic(rms > 0.02);
          requestAnimationFrame(tick);
        };
        tick();
      })
      .catch(() => console.warn('Mic access denied'));
  }, []);

  useEffect(() => {
    if (speaker !== 'Assistant') return;
    const canvas = canvasRef.current;
    const ctx    = canvas.getContext('2d');
    const W = canvas.width, H = canvas.height;
    const nodes = Array.from({ length: 30 }, () => ({ x:Math.random()*W, y:Math.random()*H, vx:(Math.random()-0.5)*0.6, vy:(Math.random()-0.5)*0.6 }));
    function draw() {
      ctx.clearRect(0,0,W,H);
      nodes.forEach(n => { n.x+=n.vx; n.y+=n.vy; if(n.x<0||n.x>W)n.vx*=-1; if(n.y<0||n.y>H)n.vy*=-1; });
      ctx.strokeStyle='rgba(150,150,150,0.6)'; ctx.lineWidth=1.2;
      nodes.forEach((n,i)=>{ for(let j=i+1;j<nodes.length;j++){ const m=nodes[j]; const dx=n.x-m.x, dy=n.y-m.y; const dist=Math.hypot(dx,dy); if(dist<W/3){ ctx.globalAlpha=1-dist/(W/3); ctx.beginPath(); ctx.moveTo(n.x,n.y); ctx.lineTo(m.x,m.y); ctx.stroke(); } } });
      ctx.fillStyle='rgba(120,120,120,0.9)'; nodes.forEach(n=>{ctx.beginPath();ctx.arc(n.x,n.y,3,0,2*Math.PI);ctx.fill();});
      requestAnimationFrame(draw);
    }
    draw();
  }, [resetKey, speaker]);

  const themes = { User:{ light:'#94A3B8', dark:'#334155' }, Assistant:{ light:'#bfdbfe', dark:'#3b82f6' } };
  const { light, dark } = themes[speaker] || themes.Assistant;
  const speaking = micSpeaking || active;

  return (
    <Sphere light={light} dark={dark} volume={volume} speaking={speaking}>
      {speaker==='Assistant' && (
        <canvas ref={canvasRef} width={SIZE} height={SIZE} style={{position:'absolute',top:0,left:0,borderRadius:'50%',pointerEvents:'none'}}/>
      )}
      {speaker==='Assistant' && functionCalls.map(f => (
        <FunctionCallBubble key={f.id}>{f.name}</FunctionCallBubble>
      ))}
      <Label>{speaker==='User' ? 'User' : 'Agent'}</Label>
    </Sphere>
  );
}
