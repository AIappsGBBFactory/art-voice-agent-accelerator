import { memo } from 'react';
import {
  Accordion, AccordionDetails, AccordionSummary, Box, MenuItem, Stack, TextField, Typography,
} from '@mui/material';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import { authoringSelectProps } from '../styles/authoringStyles.js';

const ScenarioDetailsEditor = memo(function ScenarioDetailsEditor({
  config, onChange, jsonDrafts, jsonErrors, onJsonChange, disabled,
}) {
  const set = (field, value) => onChange({ ...config, [field]: value });
  return (
    <Stack spacing={2} component="fieldset" disabled={disabled} sx={{ m: 0, p: 0, border: 0, minWidth: 0 }}>
      <TextField label="Scenario name" size="small" value={config.name}
        slotProps={{ input: { readOnly: true } }}
        helperText="Updates this scenario for your session; the original template stays unchanged." />
      <TextField label="Scenario purpose" size="small" value={config.description || ''} multiline minRows={2} maxRows={5}
        slotProps={{ htmlInput: { maxLength: 512 } }}
        onChange={(event) => set('description', event.target.value)} />
      <Box sx={{ display: 'grid', gridTemplateColumns: 'minmax(0, 100px) minmax(0, 1fr)', gap: 1.5 }}>
        <TextField label="Icon" size="small" value={config.icon || ''} slotProps={{ htmlInput: { maxLength: 8 } }}
          onChange={(event) => set('icon', event.target.value)} />
        <TextField label="New handoff style" size="small" select value={config.handoff_type || 'announced'}
          slotProps={{ select: authoringSelectProps }} onChange={(event) => set('handoff_type', event.target.value)}>
          <MenuItem value="announced">Announced</MenuItem>
          <MenuItem value="discrete">Silent</MenuItem>
        </TextField>
      </Box>
      {[
        ['global_template_vars', 'Scenario context', 'Business context available to agent prompts through Jinja. Strings, numbers, booleans, and nested objects keep their types.'],
        ['agent_defaults', 'Agent defaults', 'Shared greeting, voice, and template-variable overrides. Existing defaults are preserved unless you change them.'],
      ].map(([field, label, help]) => (
        <Accordion key={field} disableGutters elevation={0}
          sx={{ border: '1px solid', borderColor: jsonErrors[field] ? 'error.main' : 'divider', borderRadius: '8px !important', '&:before': { display: 'none' } }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ textAlign: 'left' }}>
            <Typography variant="body2" fontWeight={600}>{label}</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Stack spacing={1.5}>
              <Typography variant="body2" color="text.secondary">{help}</Typography>
              <TextField label={`${label} (JSON)`} multiline minRows={5} maxRows={14} size="small"
                value={jsonDrafts[field] ?? JSON.stringify(config[field] || {}, null, 2)}
                onChange={(event) => onJsonChange(field, event.target.value)}
                error={Boolean(jsonErrors[field])} helperText={jsonErrors[field] || 'Use a JSON object. Changes are not applied until you save the scenario.'}
                slotProps={{ htmlInput: { spellCheck: false } }}
                sx={{ '& textarea': { fontFamily: 'monospace', fontSize: 13 } }} />
            </Stack>
          </AccordionDetails>
        </Accordion>
      ))}
    </Stack>
  );
});

export default ScenarioDetailsEditor;
