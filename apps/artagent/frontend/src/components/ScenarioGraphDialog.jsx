/**
 * ScenarioGraphDialog
 * ===================
 *
 * A controlled overlay that hosts the existing graphical scenario editor
 * (`ScenarioGraphCanvas` from ScenarioBuilderGraph.jsx) for reviewing a
 * generated draft or editing the routing of the currently active scenario.
 *
 * This component owns no persistence: every write goes through the caller's
 * `onConfigChange`/`onLayoutChange` callbacks, and nothing is saved,
 * activated, or registered until the caller's own Apply/Save action runs.
 * Closing the dialog only hides it - the caller keeps the draft and layout
 * state so reopening restores exactly where the user left off.
 */

import { memo, useId, useMemo } from 'react';
import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  IconButton, Stack, Typography,
} from '@mui/material';
import { createTheme, ThemeProvider, useTheme } from '@mui/material/styles';
import CloseIcon from '@mui/icons-material/Close';
import { ScenarioGraphCanvas } from './ScenarioBuilderGraph.jsx';
import { authoringSurfaceSx } from '../styles/authoringStyles.js';

const ScenarioGraphDialog = memo(function ScenarioGraphDialog({
  open, onClose, title = 'Review scenario', subtitle,
  agents, config, onConfigChange, layout, onLayoutChange,
  onSelectAgent, inspector, banner, actions, disabled = false,
}) {
  const titleId = useId();
  const parentTheme = useTheme();
  const overlayTheme = useMemo(() => createTheme(parentTheme, {
    zIndex: { modal: 13010, tooltip: 13020 },
  }), [parentTheme]);
  return (
    <ThemeProvider theme={overlayTheme}>
    <Dialog
      open={open}
      onClose={onClose}
      aria-labelledby={titleId}
      maxWidth="lg"
      fullWidth
      slotProps={{ paper: { sx: {
        ...authoringSurfaceSx,
        m: { xs: 1, sm: 3 },
        width: { xs: 'calc(100% - 16px)', sm: 'calc(100% - 48px)' },
        height: { xs: 'calc(100dvh - 16px)', sm: 'min(900px, calc(100dvh - 48px))' },
        maxHeight: 'calc(100dvh - 16px)', borderRadius: 3,
      } } }}
    >
      <DialogTitle id={`${titleId}-header`} component="div" sx={{ px: { xs: 2, sm: 3 }, py: 2, flexShrink: 0 }}>
        <Stack direction="row" alignItems="flex-start" spacing={1.5}>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography id={titleId} component="h2" variant="h6" fontWeight={650} sx={{ lineHeight: 1.35 }}>{title}</Typography>
            {subtitle && <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5 }}>{subtitle}</Typography>}
          </Box>
          <IconButton aria-label="Close graphical editor" onClick={onClose} sx={{ mt: -0.5 }}>
            <CloseIcon fontSize="small" />
          </IconButton>
        </Stack>
      </DialogTitle>
      <DialogContent dividers sx={{ p: 0, display: 'flex', minHeight: 0, flexDirection: 'column' }}>
        {banner && <Box sx={{ p: 1.5, flexShrink: 0, maxHeight: '30%', overflowY: 'auto' }}>{banner}</Box>}
        <Box sx={{ flex: 1, display: 'flex', minHeight: 0, overflow: 'hidden' }}>
          <Box component="fieldset" disabled={disabled}
            sx={{
              flex: 1, minWidth: 0, minHeight: 0, m: 0, p: 0, border: 0,
              display: inspector ? { xs: 'none', lg: 'block' } : 'block',
              opacity: disabled ? 0.6 : 1, pointerEvents: disabled ? 'none' : 'auto',
            }}>
            <ScenarioGraphCanvas
              agents={agents}
              config={config}
              onConfigChange={onConfigChange}
              layout={layout}
              onLayoutChange={onLayoutChange}
              onViewAgentDetails={(agent) => onSelectAgent?.(agent?.name || null)}
              showSummary={!inspector}
            />
          </Box>
          {inspector && (
            <Box component="section" aria-label="Agent inspector" sx={{
              width: { xs: '100%', lg: 384 }, minWidth: 0, boxSizing: 'border-box',
              borderLeft: { lg: '1px solid' }, borderColor: 'divider',
              overflowY: 'auto', overscrollBehavior: 'contain', flexShrink: 0,
              bgcolor: 'background.paper',
            }}>
              <Box sx={{ px: 2, py: 1, position: 'sticky', top: 0, zIndex: 1, bgcolor: 'background.paper', borderBottom: 1, borderColor: 'divider' }}>
                <Button size="small" onClick={() => onSelectAgent?.(null)}>Close inspector</Button>
              </Box>
              <Box sx={{ p: 2 }}>{inspector}</Box>
            </Box>
          )}
        </Box>
      </DialogContent>
      <DialogActions disableSpacing sx={{
        px: { xs: 2, sm: 3 }, py: 1.5, gap: 1, flexWrap: 'wrap', flexShrink: 0,
        '& > .MuiAlert-root': { flexBasis: { xs: '100%', sm: 'auto' } },
        '& > .MuiButton-root': { minHeight: { xs: 44, sm: 36 } },
      }}>
        {!actions && (
          <Alert severity="info" sx={{ flex: 1, py: 0 }}>
            Drag, connect, and edit here - nothing is saved until you apply.
          </Alert>
        )}
        {actions || <Button onClick={onClose}>Close</Button>}
      </DialogActions>
    </Dialog>
    </ThemeProvider>
  );
});

export default ScenarioGraphDialog;
