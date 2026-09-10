export const authoringSurfaceSx = {
  minWidth: 0,
  color: 'text.primary',
  '& .MuiStack-root, & .MuiAutocomplete-root, & .MuiFormControl-root': { minWidth: 0 },
  '& .MuiFormControl-root, & .MuiChip-root': { maxWidth: '100%' },
  '& .MuiAccordionSummary-content, & .MuiChip-label': { minWidth: 0 },
  '& .MuiTypography-root, & .MuiAlert-message': { overflowWrap: 'anywhere' },
  '& .MuiAlert-message': { minWidth: 0 },
  '& .MuiFormHelperText-root': { mx: 0, lineHeight: 1.5, overflowWrap: 'anywhere' },
  '& .MuiButton-root': { textTransform: 'none', boxShadow: 'none', overflowWrap: 'anywhere' },
  '& .MuiIconButton-root, & .MuiAccordionSummary-expandIconWrapper': { flexShrink: 0 },
};

// Menus render in portals, outside the workspace's containment styles.
export const authoringMenuSx = {
  maxWidth: 'min(480px, calc(100vw - 24px))',
  '& .MuiMenuItem-root': { whiteSpace: 'normal', overflowWrap: 'anywhere', minHeight: 40 },
  '& .MuiTypography-root': { overflowWrap: 'anywhere' },
};

export const authoringSelectProps = {
  MenuProps: {
    slotProps: {
      paper: { sx: authoringMenuSx },
      list: { sx: { maxHeight: 'min(420px, calc(100dvh - 64px))', overflowY: 'auto' } },
    },
  },
};

export const authoringAutocompleteSlots = {
  listbox: {
    sx: {
      '& .MuiAutocomplete-option': { overflowWrap: 'anywhere' },
      '& .MuiCheckbox-root': { flexShrink: 0 },
    },
  },
};
