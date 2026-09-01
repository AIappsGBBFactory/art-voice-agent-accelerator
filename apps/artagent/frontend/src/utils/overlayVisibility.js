import { useSyncExternalStore } from 'react';

/**
 * Tracks whether a full-screen overlay is currently covering the app.
 *
 * A full-screen modal hides everything behind it, so any rAF-driven visual
 * underneath (waveforms, level meters) keeps burning main-thread time painting
 * pixels nobody can see. Continuous animations subscribe here and idle while an
 * overlay is up, which keeps the overlay itself smooth.
 */

let openCount = 0;
const listeners = new Set();

const notify = () => {
  listeners.forEach((listener) => listener());
};

export const isOverlayOpen = () => openCount > 0;

/** Register a full-screen overlay. Returns a release function. */
export function pushOverlay() {
  openCount += 1;
  if (openCount === 1) notify();

  let released = false;
  return () => {
    if (released) return;
    released = true;
    openCount = Math.max(0, openCount - 1);
    if (openCount === 0) notify();
  };
}

export function subscribeOverlay(listener) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** True while at least one full-screen overlay is open. */
export function useOverlayOpen() {
  return useSyncExternalStore(subscribeOverlay, isOverlayOpen, () => false);
}
