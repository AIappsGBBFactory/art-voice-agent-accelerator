import { memo } from 'react';
import {
  Alert, Autocomplete, Box, Button, Checkbox, FormControlLabel, IconButton,
  MenuItem, Paper, Stack, TextField, Typography,
} from '@mui/material';
import AddIcon from '@mui/icons-material/Add';
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline';
import {
  authoringAutocompleteSlots, authoringSelectProps, authoringSurfaceSx,
} from '../styles/authoringStyles.js';

const ScenarioFlowEditor = memo(function ScenarioFlowEditor({
  scenario, onChange, tools = [], availableAgents = [], disabled = false, allowAllAgents = false,
}) {
  const membership = scenario.agents || [];
  const usesAllAgents = allowAllAgents && membership.length === 0;
  const agents = usesAllAgents ? availableAgents : membership;
  const routes = scenario.handoffs || [];
  const handoffTools = tools.filter((tool) => tool.is_handoff);
  const options = [...new Set([...agents, ...availableAgents])];
  const set = (key, value) => onChange({ ...scenario, [key]: value });
  const updateRoute = (index, patch) => set('handoffs', routes.map((route, position) => (
    index === position ? { ...route, ...patch } : route
  )));

  return (
    <Stack spacing={2} component="fieldset" disabled={disabled} sx={{ ...authoringSurfaceSx, border: 0, p: 0, m: 0 }}>
      <Autocomplete multiple size="small" options={options} value={membership}
        slotProps={authoringAutocompleteSlots}
        onChange={(_, names) => onChange({
          ...scenario,
          agents: names,
          start_agent: (allowAllAgents && !names.length) || names.includes(scenario.start_agent) ? scenario.start_agent : '',
          handoffs: allowAllAgents && !names.length ? routes
            : routes.filter((route) => names.includes(route.from_agent) && names.includes(route.to_agent)),
        })}
        renderInput={(params) => <TextField {...params} label="Agents in this scenario"
          placeholder={usesAllAgents ? 'All registered agents' : undefined}
          helperText={usesAllAgents
            ? 'This scenario allows all registered agents. Select specific agents to restrict it.'
            : 'Removing an agent also removes its handoffs.'} />} />
      <TextField select size="small" label="Starting agent" value={scenario.start_agent || ''}
        slotProps={{ select: authoringSelectProps }}
        onChange={(event) => set('start_agent', event.target.value)}>
        <MenuItem value="" disabled>Choose an agent</MenuItem>
        {agents.map((name) => <MenuItem key={name} value={name}>{name}</MenuItem>)}
      </TextField>
      {agents.length <= 1 && (
        <Typography variant="body2" color="text.secondary">
          One agent, one conversation. No handoffs needed.
        </Typography>
      )}
      {routes.map((route, index) => (
        <Paper key={index} variant="outlined" sx={{ p: 1.5, borderRadius: 2 }}>
          <Stack spacing={1.5}>
            <Stack direction="row" justifyContent="space-between" alignItems="center">
              <Typography variant="body2" fontWeight={600}>Handoff {index + 1}</Typography>
              <IconButton size="small" aria-label={`Remove handoff ${index + 1}`}
                onClick={() => set('handoffs', routes.filter((_, position) => position !== index))}>
                <DeleteOutlineIcon fontSize="small" />
              </IconButton>
            </Stack>
            <TextField label="When should this handoff happen?" size="small" multiline
              value={route.handoff_condition || ''}
              onChange={(event) => updateRoute(index, { handoff_condition: event.target.value })} />
            <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 190px), 1fr))', gap: 1.5 }}>
              <TextField select fullWidth size="small" label="From agent" value={route.from_agent}
                slotProps={{ select: authoringSelectProps }}
                onChange={(event) => updateRoute(index, { from_agent: event.target.value })}>
                {agents.map((name) => <MenuItem key={name} value={name}>{name}</MenuItem>)}
              </TextField>
              <TextField select fullWidth size="small" label="To agent" value={route.to_agent}
                slotProps={{ select: authoringSelectProps }}
                onChange={(event) => updateRoute(index, { to_agent: event.target.value })}>
                {agents.map((name) => <MenuItem key={name} value={name}>{name}</MenuItem>)}
              </TextField>
            </Box>
            <TextField select size="small" label="Handoff tool" value={route.tool || ''}
              slotProps={{ select: authoringSelectProps }}
              onChange={(event) => updateRoute(index, { tool: event.target.value })}>
              <MenuItem value="" disabled>Choose a registered handoff tool</MenuItem>
              {route.tool && !handoffTools.some((tool) => tool.name === route.tool)
                && <MenuItem value={route.tool}>{route.tool} (not in catalog)</MenuItem>}
              {handoffTools.map((tool) => <MenuItem key={tool.name} value={tool.name}>{tool.name}</MenuItem>)}
            </TextField>
            <TextField select size="small" label="Transfer style" value={route.type || 'announced'}
              slotProps={{ select: authoringSelectProps }}
              onChange={(event) => updateRoute(index, { type: event.target.value })}>
              <MenuItem value="announced">Announce the transfer</MenuItem>
              <MenuItem value="discrete">Transfer silently</MenuItem>
            </TextField>
            <FormControlLabel label="Share conversation context"
              control={<Checkbox size="small" checked={route.share_context !== false}
                onChange={(event) => updateRoute(index, { share_context: event.target.checked })} />} />
          </Stack>
        </Paper>
      ))}
      {agents.length > 1 && (
        handoffTools.length ? (
          <Box>
            <Button size="small" startIcon={<AddIcon />} onClick={() => set('handoffs', [
              ...routes,
              {
                from_agent: scenario.start_agent || agents[0],
                to_agent: agents.find((name) => name !== scenario.start_agent) || agents[1],
                tool: handoffTools.length === 1 ? handoffTools[0].name : '',
                type: 'announced', share_context: true, handoff_condition: '', context_vars: {},
              },
            ])}>Add handoff</Button>
          </Box>
        ) : <Alert severity="warning">No registered handoff tools are available. Connect a routing capability in Advanced Builder.</Alert>
      )}
    </Stack>
  );
});

export default ScenarioFlowEditor;
