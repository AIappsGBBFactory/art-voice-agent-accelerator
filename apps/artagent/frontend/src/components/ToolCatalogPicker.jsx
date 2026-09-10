import { memo, useCallback, useId, useMemo, useState } from 'react';
import {
  Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, Checkbox,
  Chip, Collapse, IconButton, InputAdornment, MenuItem, Pagination, Stack,
  TextField, ToggleButton, ToggleButtonGroup, Tooltip, Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined';
import SearchIcon from '@mui/icons-material/Search';
import FilterListIcon from '@mui/icons-material/FilterList';
import { agentKey, mergeAgentAssignments } from '../utils/quickTune.js';
import { authoringSelectProps, authoringSurfaceSx } from '../styles/authoringStyles.js';

const PAGE_SIZE = 6;
const readableName = (name) => name.replace(/[_-]+/g, ' ').replace(/^\w/, (letter) => letter.toUpperCase());
const categoryOf = (tool) => tool.is_handoff ? 'handoff' : tool.tags?.[0] || 'general';
const assignmentSource = (agent) => agent.has_local_draft ? 'Workspace draft'
  : agent.is_session_agent ? 'Session configuration' : 'Template';

function ToolDetails({ tool, assignedAgents, assignmentsAvailable }) {
  const inputs = Object.entries(tool.parameters?.properties || {});
  const required = new Set(tool.parameters?.required || []);
  return (
    <Stack spacing={2} sx={{ pt: 1.5 }}>
      <Typography variant="body2" sx={{ whiteSpace: 'pre-line' }}>
        {tool.description || 'No description provided in the tool catalog.'}
      </Typography>
      <Box>
        <Typography variant="subtitle2" gutterBottom>Agent assignments</Typography>
        {!assignmentsAvailable ? (
          <Typography variant="body2" color="text.secondary">Agent assignments are unavailable. Refresh the agent catalog.</Typography>
        ) : assignedAgents.length ? (
          <Stack component="ul" spacing={1} sx={{ listStyle: 'none', m: 0, p: 0 }}>
            {assignedAgents.map((agent) => (
              <Box component="li" key={agentKey(agent.name)}>
                <Typography variant="body2" fontWeight={600}>{agent.name || 'Unnamed draft agent'}</Typography>
                <Typography variant="caption" color="text.secondary">{assignmentSource(agent)}</Typography>
                {agent.description && <Typography variant="caption" component="div" color="text.secondary">{agent.description}</Typography>}
              </Box>
            ))}
          </Stack>
        ) : <Typography variant="body2" color="text.secondary">Not assigned to any agent in this catalog.</Typography>}
        <Typography variant="caption" color="text.secondary" component="p" sx={{ mb: 0 }}>
          Direct assignments from the agent catalog, including session configurations and workspace drafts, not execution history.
        </Typography>
      </Box>
      <Box>
        <Typography variant="subtitle2" gutterBottom>Inputs</Typography>
        {inputs.length ? (
          <Stack component="dl" spacing={1.5} sx={{ m: 0 }}>
            {inputs.map(([name, field]) => (
              <Box key={name}>
                <Stack component="dt" direction="row" alignItems="baseline" flexWrap="wrap" gap={0.75}>
                  <Typography component="span" variant="body2" fontWeight={600}>{name}</Typography>
                  <Typography component="span" variant="caption" color="text.secondary">
                    {Array.isArray(field?.type) ? field.type.join(' / ') : field?.type || 'See schema'}
                    {required.has(name) ? ' / required' : ' / optional'}
                  </Typography>
                </Stack>
                <Box component="dd" sx={{ m: 0 }}>
                  {field?.description && <Typography variant="body2" color="text.secondary">{field.description}</Typography>}
                  {Array.isArray(field?.enum) && (
                    <Typography variant="caption" color="text.secondary">
                      Choices: {field.enum.map((value) => JSON.stringify(value)).join(', ')}
                    </Typography>
                  )}
                </Box>
              </Box>
            ))}
          </Stack>
        ) : <Typography variant="body2" color="text.secondary">
          {tool.parameters ? 'No input fields listed in the catalog.' : 'Input schema is not available in the catalog.'}
        </Typography>}
      </Box>
      {(tool.tags || []).length > 0 && (
        <Stack direction="row" flexWrap="wrap" gap={0.75}>
          {tool.tags.map((tag) => <Chip key={tag} label={tag} size="small" variant="outlined" />)}
        </Stack>
      )}
      {tool.source === 'mcp' && (
        <Alert severity="info">
          MCP server: {tool.mcp_server || 'Not specified'}
          {tool.mcp_transport ? ` (${tool.mcp_transport})` : ''}. Registration does not confirm a working connection.
        </Alert>
      )}
      {tool.parameters && (
        <Accordion disableGutters elevation={0} sx={{ bgcolor: 'action.hover', '&:before': { display: 'none' } }}>
          <AccordionSummary expandIcon={<ExpandMoreIcon />} sx={{ textAlign: 'left' }}>
            <Typography variant="body2">Full input schema</Typography>
          </AccordionSummary>
          <AccordionDetails>
            <Box component="pre" sx={{ m: 0, fontSize: 12, whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>
              {JSON.stringify(tool.parameters, null, 2)}
            </Box>
          </AccordionDetails>
        </Accordion>
      )}
    </Stack>
  );
}

const ToolCatalogPicker = memo(function ToolCatalogPicker({
  tools = [], value = [], onChange, agents = [],
  disabled = false, toolsAvailable = true, assignmentsAvailable = true,
}) {
  const id = useId();
  const [query, setQuery] = useState('');
  const [category, setCategory] = useState('');
  const [filtersOpen, setFiltersOpen] = useState(false);
  const [agentFilter, setAgentFilter] = useState('');
  const [scope, setScope] = useState('all');
  const [page, setPage] = useState(1);
  const [expandedName, setExpandedName] = useState(null);
  const selected = useMemo(() => new Set(value), [value]);
  const assignmentAgents = useMemo(() => mergeAgentAssignments(agents), [agents]);
  const assignments = useMemo(() => {
    const index = new Map();
    assignmentAgents.forEach((agent) => {
      new Set(agent.tools || []).forEach((name) => {
        if (!index.has(name)) index.set(name, []);
        index.get(name).push(agent);
      });
    });
    return index;
  }, [assignmentAgents]);
  const catalog = useMemo(() => {
    const byName = new Map(tools.map((tool) => [tool.name, tool]));
    value.forEach((name) => {
      if (!byName.has(name)) byName.set(name, { name, description: '', unavailable: true });
    });
    return [...byName.values()].sort((a, b) => a.name.localeCompare(b.name));
  }, [tools, value]);
  const categories = useMemo(() => [...new Set(tools.map(categoryOf))].sort(), [tools]);
  const filtered = useMemo(() => {
    const terms = query.toLowerCase().trim().split(/\s+/).filter(Boolean);
    return catalog.filter((tool) => {
      const assigned = assignments.get(tool.name) || [];
      if (scope === 'selected' && !selected.has(tool.name)) return false;
      if (category && categoryOf(tool) !== category) return false;
      if (agentFilter === 'unassigned' && assigned.length) return false;
      if (agentFilter.startsWith('agent:') && !assigned.some((agent) => `agent:${agentKey(agent.name)}` === agentFilter)) return false;
      const searchable = [
        tool.name, readableName(tool.name), tool.description, ...(tool.tags || []),
        tool.source === 'mcp' ? `MCP ${tool.mcp_server || ''}` : 'Built-in',
        ...assigned.map((agent) => agent.name),
      ].join(' ').toLowerCase();
      return terms.every((term) => searchable.includes(term));
    });
  }, [catalog, query, scope, selected, category, agentFilter, assignments]);
  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageTools = filtered.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE);
  const hasFilters = Boolean(query || category || agentFilter);
  const toggleTool = useCallback((name) => {
    onChange(selected.has(name) ? value.filter((item) => item !== name) : [...value, name]);
  }, [onChange, selected, value]);
  const resetFilters = () => {
    setQuery(''); setCategory(''); setAgentFilter(''); setPage(1);
  };

  return (
    <Stack component="section" aria-label="Tool catalog" spacing={1.5} sx={authoringSurfaceSx}>
      <Stack direction="row" alignItems="center" gap={0.75}>
        <TextField label="Find capabilities" placeholder="Purpose, name, or agent" size="small" sx={{ flex: 1 }}
          value={query} onChange={(event) => { setQuery(event.target.value); setPage(1); }}
          slotProps={{ input: {
            startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment>,
            endAdornment: query ? <InputAdornment position="end">
              <IconButton size="small" aria-label="Clear tool search" onClick={() => { setQuery(''); setPage(1); }}>
                <CloseIcon fontSize="small" />
              </IconButton>
            </InputAdornment> : null,
          } }} />
        <Tooltip title="Filter by category or agent">
          <Button size="small" startIcon={<FilterListIcon />} aria-label="Tool filters"
            aria-expanded={filtersOpen} aria-controls={`${id}-filters`}
            onClick={() => setFiltersOpen((current) => !current)}
            sx={{ flexShrink: 0, px: 1, minWidth: 0, minHeight: 40 }}>
            Filters{category || agentFilter ? ` (${Number(Boolean(category)) + Number(Boolean(agentFilter))})` : ''}
          </Button>
        </Tooltip>
      </Stack>
      <Collapse in={filtersOpen}>
      <Box id={`${id}-filters`} sx={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(min(100%, 130px), 1fr))', gap: 1 }}>
        <TextField select size="small" label="Category" value={category} slotProps={{ select: authoringSelectProps }}
          onChange={(event) => { setCategory(event.target.value); setPage(1); }}>
          <MenuItem value="">All categories</MenuItem>
          {categories.map((item) => <MenuItem key={item} value={item}>{readableName(item)}</MenuItem>)}
        </TextField>
        <TextField select size="small" label="Assigned to" value={agentFilter} disabled={!assignmentsAvailable}
          slotProps={{ select: authoringSelectProps }}
          onChange={(event) => { setAgentFilter(event.target.value); setPage(1); }}>
          <MenuItem value="">Any agent</MenuItem>
          <MenuItem value="unassigned">Not assigned</MenuItem>
          {assignmentAgents.map((agent) => (
            <MenuItem key={agentKey(agent.name)} value={`agent:${agentKey(agent.name)}`}>
              {agent.name || 'Unnamed draft agent'}{agent.has_local_draft ? ' (draft)' : ''}
            </MenuItem>
          ))}
        </TextField>
      </Box>
      </Collapse>
      <ToggleButtonGroup value={scope} exclusive fullWidth size="small" aria-label="Tool selection view"
        onChange={(_, next) => { if (next) { setScope(next); setPage(1); } }}
        sx={{ '& .MuiToggleButton-root': { textTransform: 'none', lineHeight: 1.4 } }}>
        <ToggleButton value="all">All tools ({catalog.length})</ToggleButton>
        <ToggleButton value="selected">Selected ({selected.size})</ToggleButton>
      </ToggleButtonGroup>
      {!toolsAvailable && <Alert severity="warning">Tool catalog unavailable. Selections are preserved; refresh catalogs to continue.</Alert>}
      {!assignmentsAvailable && <Alert severity="info">Agent assignments are unavailable. Refresh the agent catalog to see usage.</Alert>}
      <Stack direction="row" justifyContent="space-between" alignItems="center" flexWrap="wrap" gap={1}>
        <Typography variant="caption" color="text.secondary" role="status" aria-live="polite">
          {filtered.length} {filtered.length === 1 ? 'result' : 'results'}
        </Typography>
        {hasFilters && <Button size="small" onClick={resetFilters}>Clear filters</Button>}
        {selected.size > 0 && <Button size="small" disabled={disabled || !toolsAvailable}
          onClick={() => onChange([])}>Clear selection</Button>}
      </Stack>
      <Box component="ul" aria-label="Available capabilities" sx={{
        listStyle: 'none', m: 0, p: 0, maxHeight: 480, overflowY: 'auto', overscrollBehavior: 'contain',
        border: '1px solid', borderColor: 'divider', borderRadius: 2,
      }}>
        {pageTools.map((tool) => {
          const assignedAgents = assignments.get(tool.name) || [];
          const isSelected = selected.has(tool.name);
          const expanded = expandedName === tool.name;
          const rowId = `${id}-${encodeURIComponent(tool.name)}`;
          const assignmentText = assignedAgents.length
            ? `Assigned to ${assignedAgents.slice(0, 2).map((agent) => agent.name || 'Unnamed draft agent').join(', ')}${assignedAgents.length > 2 ? ` +${assignedAgents.length - 2} more` : ''}`
            : 'Not assigned in this catalog';
          return (
            <Box component="li" key={tool.name} data-testid={`tool-option-${tool.name}`} sx={{
              p: 1.5, borderBottom: '1px solid', borderColor: 'divider',
              bgcolor: isSelected ? 'action.selected' : 'background.paper',
              '&:last-child': { borderBottom: 0 },
            }}>
              <Stack direction="row" alignItems="flex-start" gap={0.75}>
                <Checkbox size="small" checked={isSelected} onChange={() => toggleTool(tool.name)}
                  disabled={disabled || !toolsAvailable || (tool.unavailable && !isSelected)}
                  slotProps={{ input: { id: rowId, 'aria-label': `Use ${tool.name}` } }} sx={{ p: 0.5, ml: -0.5 }} />
                <Box sx={{ flex: 1, minWidth: 0 }}>
                  <Typography component="label" htmlFor={rowId} variant="body2" fontWeight={600}
                    sx={{ display: 'block', cursor: disabled ? 'default' : 'pointer' }}>
                    {readableName(tool.name)}
                  </Typography>
                  <Typography component="code" variant="caption" color="text.secondary"
                    sx={{ fontFamily: 'monospace', display: 'block', mt: 0.25 }}>{tool.name}</Typography>
                </Box>
                <Tooltip title={expanded ? 'Hide tool details' : 'View tool details'}>
                  <IconButton size="small" aria-label={`Details for ${tool.name}`}
                    aria-expanded={expanded} aria-controls={`${rowId}-details`}
                    onClick={() => setExpandedName(expanded ? null : tool.name)}>
                    <InfoOutlinedIcon fontSize="small" />
                  </IconButton>
                </Tooltip>
              </Stack>
              {tool.unavailable && toolsAvailable && <Alert severity="warning" sx={{ mt: 1 }}>
                Not in the current catalog. Remove it or refresh before saving.
              </Alert>}
              {!expanded && <Typography variant="body2" color="text.secondary" sx={{
                mt: 1, display: '-webkit-box', WebkitLineClamp: 3, WebkitBoxOrient: 'vertical', overflow: 'hidden',
              }}>{tool.description || 'No description provided in the tool catalog.'}</Typography>}
              <Stack direction="row" alignItems="center" gap={1} flexWrap="wrap" sx={{ mt: 1 }}>
                {!tool.unavailable && <Chip size="small" variant="outlined" label={readableName(categoryOf(tool))} />}
                <Typography variant="caption" color="text.secondary">
                  {tool.unavailable ? toolsAvailable ? 'Not registered' : 'Catalog unavailable'
                    : tool.source === 'mcp' ? `MCP: ${tool.mcp_server || 'external'}` : 'Built-in'}
                </Typography>
              </Stack>
              {assignmentsAvailable && (
                <Button size="small" onClick={() => setExpandedName(expanded ? null : tool.name)}
                  sx={{ mt: 0.75, p: 0, minWidth: 0, textAlign: 'left', justifyContent: 'flex-start', fontSize: 12 }}>
                  {assignmentText}
                </Button>
              )}
              <Collapse in={expanded} unmountOnExit>
                <Box id={`${rowId}-details`}>
                  <ToolDetails tool={tool} assignedAgents={assignedAgents} assignmentsAvailable={assignmentsAvailable} />
                </Box>
              </Collapse>
            </Box>
          );
        })}
        {!filtered.length && (
          <Box component="li" sx={{ p: 2 }}>
            <Typography variant="body2" fontWeight={600}>
              {scope === 'selected' && !selected.size ? 'No tools selected yet' : catalog.length ? 'No matching tools' : 'No registered tools'}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>
              {hasFilters ? 'Try a different purpose, category, or agent.'
                : scope === 'selected' ? 'Browse all tools to choose the capabilities this agent needs.'
                  : 'Connect tools in Advanced Builder, then refresh the catalog.'}
            </Typography>
            {(hasFilters || scope === 'selected') && (
              <Button size="small" sx={{ mt: 1 }} onClick={() => { resetFilters(); setScope('all'); }}>Show all tools</Button>
            )}
          </Box>
        )}
      </Box>
      {pageCount > 1 && (
        <Pagination count={pageCount} page={currentPage} onChange={(_, next) => setPage(next)}
          size="small" siblingCount={0} sx={{ alignSelf: 'center' }} />
      )}
    </Stack>
  );
});

export default ToolCatalogPicker;
