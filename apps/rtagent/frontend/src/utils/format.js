export const formatDuration = (ms) => {
  if (ms === null || ms === undefined) {
    return null;
  }
  if (ms < 1000) {
    return `${ms.toFixed(0)}ms`;
  }
  return `${(ms / 1000).toFixed(2)}s`;
};
