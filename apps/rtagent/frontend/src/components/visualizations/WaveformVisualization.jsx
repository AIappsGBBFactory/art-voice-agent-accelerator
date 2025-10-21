import { useEffect, useRef, useState } from 'react';
import { styles } from '../AppStyles';

const WAVEFORM_WIDTH = 750;
const WAVEFORM_HEIGHT = 100;
const SECONDARY_SCALE = 0.6;
const PRIMARY_STROKE_WIDTH = 3;
const SECONDARY_STROKE_WIDTH = 2;
const POINT_COUNT = 100;

const colorsBySpeaker = {
  User: {
    baseColor: '#ef4444',
    opacity: 0.8,
  },
  Assistant: {
    baseColor: '#6366f1',
    opacity: 0.75,
  },
  Tool: {
    baseColor: '#8b5cf6',
    opacity: 0.7,
  },
};

const defaultWaveColor = {
  baseColor: '#38bdf8',
  opacity: 0.6,
};

const getSpeakerColor = (speaker) => colorsBySpeaker[speaker] || defaultWaveColor;

const WaveformVisualization = ({ speaker, audioLevel = 0, outputAudioLevel = 0 }) => {
  const [waveOffset, setWaveOffset] = useState(0);
  const [amplitude, setAmplitude] = useState(5);
  const animationRef = useRef();

  useEffect(() => {
    const animate = () => {
      setWaveOffset((prev) => (prev + (speaker ? 1.2 : 0.6)) % 1000);

      setAmplitude(() => {
        if (audioLevel > 0.01) {
          const scaledLevel = audioLevel * 36;
          const smoothVariation = Math.sin(Date.now() * 0.0015) * (scaledLevel * 0.6);
          return Math.max(12, scaledLevel + smoothVariation);
        }

        if (outputAudioLevel > 0.01) {
          const scaledLevel = outputAudioLevel * 32;
          const smoothVariation = Math.sin(Date.now() * 0.0014) * (scaledLevel * 0.3);
          return Math.max(10, scaledLevel + smoothVariation);
        }

        if (speaker) {
          const time = Date.now() * 0.0016;
          const baseAmplitude = 14;
          const rhythmicVariation = Math.sin(time) * 6;
          return baseAmplitude + rhythmicVariation;
        }

        const time = Date.now() * 0.0008;
        const breathingAmplitude = 3 + Math.sin(time) * 1.5;
        return breathingAmplitude;
      });

      animationRef.current = requestAnimationFrame(animate);
    };

    animationRef.current = requestAnimationFrame(animate);

    return () => {
      if (animationRef.current) {
        cancelAnimationFrame(animationRef.current);
      }
    };
  }, [speaker, audioLevel, outputAudioLevel]);

  const generateWavePath = (frequency, amplitudeScale = 1) => {
    const centerY = WAVEFORM_HEIGHT / 2;
    let path = `M 0 ${centerY}`;

    for (let i = 0; i <= POINT_COUNT; i += 1) {
      const x = (i / POINT_COUNT) * WAVEFORM_WIDTH;
      const y = centerY + Math.sin(x * frequency + waveOffset * 0.1) * (amplitude * amplitudeScale);
      path += ` L ${x} ${y}`;
    }

    return path;
  };

  const renderWaves = () => {
    const { baseColor, opacity } = getSpeakerColor(speaker);

    return [
      <path
        key="wave1"
        d={generateWavePath(0.018)}
        stroke={baseColor}
        strokeWidth={speaker ? PRIMARY_STROKE_WIDTH : PRIMARY_STROKE_WIDTH - 1}
        fill="none"
        opacity={opacity}
        strokeLinecap="round"
      />,
      <path
        key="wave2"
        d={generateWavePath(0.022, SECONDARY_SCALE)}
        stroke={baseColor}
        strokeWidth={speaker ? SECONDARY_STROKE_WIDTH : SECONDARY_STROKE_WIDTH - 0.5}
        fill="none"
        opacity={opacity * 0.5}
        strokeLinecap="round"
      />,
    ];
  };

  return (
    <div style={styles.waveformContainer}>
      <svg style={styles.waveformSvg} viewBox={`0 0 ${WAVEFORM_WIDTH} 80`} preserveAspectRatio="xMidYMid meet">
        {renderWaves()}
      </svg>
      {window.location.hostname === 'localhost' && (
        <div
          style={{
            position: 'absolute',
            bottom: '-25px',
            left: '50%',
            transform: 'translateX(-50%)',
            fontSize: '10px',
            color: '#666',
            whiteSpace: 'nowrap',
          }}
        >
          Input: {(audioLevel * 100).toFixed(1)}% | Amp: {amplitude.toFixed(1)}
        </div>
      )}
    </div>
  );
};

export default WaveformVisualization;
