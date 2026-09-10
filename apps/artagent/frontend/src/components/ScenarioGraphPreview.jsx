import { memo, useId, useMemo } from 'react';
import { Alert, Box, Button, ButtonBase, Skeleton, Stack, Typography } from '@mui/material';
import { alpha, useTheme } from '@mui/material/styles';
import AccountTreeIcon from '@mui/icons-material/AccountTree';
import ArrowForwardIcon from '@mui/icons-material/ArrowForward';
import OpenInFullIcon from '@mui/icons-material/OpenInFull';
import SmartToyIcon from '@mui/icons-material/SmartToy';
import { scenarioGraphPreview } from '../utils/scenarioGraph.js';

const ScenarioGraphPreview = memo(function ScenarioGraphPreview({
  config, agents, name, loading, error, dirty, disabled, onOpen, onRetry,
}) {
  const theme = useTheme();
  const id = useId();
  const graph = useMemo(() => scenarioGraphPreview(config, agents), [config, agents]);
  const title = config?.name || name;
  const summary = [
    graph.nodes.length < graph.agentCount
      ? `${graph.nodes.length} of ${graph.agentCount} agents shown`
      : `${graph.agentCount} ${graph.agentCount === 1 ? 'agent' : 'agents'}`,
    `${graph.handoffCount} ${graph.handoffCount === 1 ? 'handoff' : 'handoffs'}`,
  ].join(' / ');

  if (!title) return null;
  if (error && !config) {
    return (
      <Alert severity="warning" sx={{ mb: 2 }}
        action={<Button size="small" onClick={onRetry}>Retry preview</Button>}>
        Scenario preview unavailable: {error}
      </Alert>
    );
  }
  if (loading || !config) {
    return (
      <Box role="status" aria-label={`Loading scenario preview for ${title}`} sx={{ mb: 2 }}>
        <Skeleton variant="rounded" height={180} animation={false} />
      </Box>
    );
  }

  return (
    <ButtonBase
      onClick={onOpen} disabled={disabled} aria-haspopup="dialog"
      aria-label={`Open graphical editor for ${title}`} aria-describedby={`${id}-summary ${id}-hint`}
      data-testid="scenario-graph-preview"
      sx={{
        display: 'block', width: '100%', minWidth: 0, textAlign: 'left', mb: 2,
        border: '1px solid', borderColor: 'divider', borderRadius: 2,
        overflow: 'hidden', color: 'text.primary', bgcolor: 'background.paper',
        transition: 'border-color 150ms ease',
        '&:hover': { borderColor: 'primary.main' },
        '&.Mui-focusVisible': { outline: '2px solid', outlineColor: 'primary.main', outlineOffset: 2 },
        '&.Mui-disabled': { opacity: 0.6 },
        '@media (prefers-reduced-motion: reduce)': { transition: 'none' },
      }}
    >
      <Stack component="span" direction="row" alignItems="center" gap={1}
        sx={{ px: 1.5, py: 1, minWidth: 0 }}>
        <AccountTreeIcon fontSize="small" sx={{ color: 'primary.main', flexShrink: 0 }} />
        <Typography component="span" variant="body2" fontWeight={600} sx={{ flex: 1, minWidth: 0 }}>
          {title}
        </Typography>
        {dirty && <Typography component="span" variant="caption" color="warning.dark">Draft</Typography>}
        <OpenInFullIcon sx={{ fontSize: 16, color: 'text.secondary', flexShrink: 0 }} />
      </Stack>
      <Box component="svg" viewBox={`0 0 ${graph.width} ${graph.height}`} aria-hidden="true"
        focusable="false" sx={{ display: 'block', width: '100%', bgcolor: 'action.hover' }}>
        <defs>
          <pattern id={`${id}-grid`} width="20" height="20" patternUnits="userSpaceOnUse">
            <circle cx="1" cy="1" r="0.8" fill={theme.palette.divider} />
          </pattern>
          {['announced', 'discrete'].map((type) => (
            <marker key={type} id={`${id}-${type}`} markerWidth="7" markerHeight="7"
              refX="6" refY="3.5" orient="auto">
              <path d="M 0 0 L 7 3.5 L 0 7 Z"
                fill={type === 'discrete' ? theme.palette.warning.main : theme.palette.primary.main} />
            </marker>
          ))}
        </defs>
        <rect width="100%" height="100%" fill={`url(#${id}-grid)`} />
        {graph.edges.map((edge) => {
          const type = edge.type === 'discrete' ? 'discrete' : 'announced';
          return (
            <path key={edge.id} d={edge.path} fill="none" strokeWidth="2"
              stroke={type === 'discrete' ? theme.palette.warning.main : theme.palette.primary.main}
              strokeDasharray={type === 'discrete' ? '5 4' : undefined}
              markerEnd={`url(#${id}-${type})`}
              data-testid={`scenario-preview-edge-${edge.from_agent}-${edge.to_agent}`}>
              <title>{`${edge.from_agent} to ${edge.to_agent}: ${edge.handoff_condition || 'Condition not set'}`}</title>
            </path>
          );
        })}
        {graph.nodes.map((node) => (
          <g key={node.name} transform={`translate(${node.x} ${node.y})`}
            data-testid={`scenario-preview-node-${node.name}`}>
            <title>{node.name}{node.isStart ? ' (start agent)' : ''}</title>
            <rect width={node.width} height={node.height} rx="10"
              fill={node.isStart ? alpha(theme.palette.success.main, 0.08) : theme.palette.background.paper}
              stroke={node.isStart ? theme.palette.success.main : theme.palette.divider} />
            <SmartToyIcon x="12" y="15" width="21" height="21"
              sx={{ color: node.isStart ? 'success.dark' : 'text.secondary', fontSize: 21 }} />
            <foreignObject x="42" y="12" width={node.width - 54} height="42">
              <Box xmlns="http://www.w3.org/1999/xhtml" component="span" sx={{
                display: '-webkit-box', WebkitBoxOrient: 'vertical', WebkitLineClamp: 2,
                overflow: 'hidden', overflowWrap: 'anywhere', fontSize: 17, lineHeight: '20px',
                fontWeight: 600, color: node.isStart ? 'success.dark' : 'text.primary',
              }}>{node.label}</Box>
            </foreignObject>
            <text x="12" y="67" fontSize="15"
              fill={node.isStart ? theme.palette.success.dark : theme.palette.text.secondary}>
              {node.isStart ? 'Start / ' : ''}
              {node.toolCount === null ? 'Tools not loaded' : `${node.toolCount} ${node.toolCount === 1 ? 'tool' : 'tools'}`}
            </text>
          </g>
        ))}
        {graph.nodes.length === 0 && (
          <text x={graph.width / 2} y={graph.height / 2} textAnchor="middle"
            fill={theme.palette.text.secondary} fontSize="17">Add agents in the graphical editor</text>
        )}
      </Box>
      <Stack component="span" gap={0.5} sx={{ px: 1.5, py: 1.25 }}>
        <Stack component="span" direction="row" alignItems="center" gap={1} flexWrap="wrap">
          <Typography component="span" variant="body2" fontWeight={600} color="primary.main"
            sx={{ display: 'inline-flex', alignItems: 'center', gap: 0.75 }}>
            Open graphical editor <ArrowForwardIcon sx={{ fontSize: 16 }} />
          </Typography>
          <Typography component="span" id={`${id}-summary`} variant="caption" color="text.secondary">
            {summary}
          </Typography>
        </Stack>
        <Typography component="span" id={`${id}-hint`} variant="caption" color="text.secondary">
          Drag agents, connect routes, and edit handoff conditions.
        </Typography>
      </Stack>
    </ButtonBase>
  );
});

export default ScenarioGraphPreview;
