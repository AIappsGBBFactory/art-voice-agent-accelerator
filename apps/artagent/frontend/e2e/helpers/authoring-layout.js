export async function layoutViolations(container) {
  return container.evaluate((root) => {
    const boundary = root.getBoundingClientRect();
    const selectors = [
      '.MuiTypography-root', '.MuiAccordionSummary-content', '.MuiFormControl-root',
      '.MuiAlert-message', '.MuiStack-root', '.MuiDialogActions-root',
      '.MuiMenuItem-root', '.MuiAutocomplete-option', '.MuiButton-root', '.MuiChip-root',
    ].join(',');
    return Array.from(root.querySelectorAll(selectors)).flatMap((element) => {
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height || element.closest('[hidden]')) return [];
      // Pannable graph contents may intentionally lie outside their viewport.
      if (element.closest('[data-testid="graph-canvas"]')) return [];
      const style = getComputedStyle(element);
      const escapesPanel = rect.left < boundary.left - 2 || rect.right > boundary.right + 2;
      const visibleOverflow = element.clientWidth > 0 && element.scrollWidth > element.clientWidth + 2
        && style.overflowX === 'visible';
      if (!escapesPanel && !visibleOverflow) return [];
      return [{
        text: element.textContent?.trim().slice(0, 95),
        width: Math.round(rect.width),
        scrollWidth: element.scrollWidth,
        escapesPanel,
      }];
    }).slice(0, 20);
  });
}
