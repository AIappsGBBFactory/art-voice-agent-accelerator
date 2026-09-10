import { memo, useCallback, useId } from 'react';
import { Alert, Box, Slider, Stack, Typography } from '@mui/material';

const VoiceLiveGenerationControls = memo(function VoiceLiveGenerationControls({ model, onChange }) {
  const id = useId();
  const temperature = model?.temperature ?? 0.7;
  const maxTokens = model?.max_completion_tokens ?? model?.max_tokens ?? 4096;
  const setTemperature = useCallback((_, value) => {
    onChange({ ...model, temperature: value });
  }, [model, onChange]);
  const setMaxTokens = useCallback((_, value) => {
    onChange({ ...model, max_tokens: value, max_completion_tokens: null });
  }, [model, onChange]);

  return (
    <Stack spacing={2}>
      <Alert severity="info">
        VoiceLive manages its endpoint; BYOM selects an external model connection.
        Temperature and output-token limits are supported session settings. Top P,
        verbosity, and reasoning controls are not VoiceLive session parameters.
      </Alert>
      <Box>
        <Stack direction="row" justifyContent="space-between">
          <Typography id={`${id}-temperature`} variant="body2">Temperature</Typography>
          <Typography variant="body2" color="text.secondary">{temperature}</Typography>
        </Stack>
        <Slider aria-labelledby={`${id}-temperature`} value={temperature}
          onChange={setTemperature} min={0} max={1} step={0.05}
          marks={[{ value: 0, label: 'Focused' }, { value: 0.7, label: '0.7' }, { value: 1, label: 'Creative' }]} />
      </Box>
      <Box>
        <Stack direction="row" justifyContent="space-between">
          <Typography id={`${id}-tokens`} variant="body2">Output token limit</Typography>
          <Typography variant="body2" color="text.secondary">{maxTokens.toLocaleString()}</Typography>
        </Stack>
        <Slider aria-labelledby={`${id}-tokens`} value={maxTokens}
          onChange={setMaxTokens} min={256} max={16384} step={256}
          marks={[{ value: 1024, label: '1K' }, { value: 4096, label: '4K' }, { value: 16384, label: '16K' }]} />
      </Box>
    </Stack>
  );
});

export default VoiceLiveGenerationControls;
