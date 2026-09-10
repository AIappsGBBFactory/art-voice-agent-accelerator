/**
 * Foundry model source attribution
 * ================================
 *
 * Quick Tune silently switches the model dropdown between two different Azure
 * accounts: the primary AI Foundry account for Cascade, and the Voice Live
 * (AVL) account for VoiceLive. Because Voice Live is only offered in a subset
 * of regions, those accounts are routinely provisioned in different
 * geographies — in the reference deployment the backend runs in westus2, the
 * Cascade LLM in northcentralus and Voice Live in swedencentral, a
 * trans-Atlantic hop paid on the realtime audio path.
 *
 * These tests pin the pure attribution/comparison logic that lets the panel
 * say so, kept out of the React tree precisely so it can be tested here.
 */
import test from 'node:test';
import assert from 'node:assert/strict';

import {
  crossRegionHint,
  describeModelSource,
  regionKeyOf,
} from './foundryRegions.js';

// =============================================================================
// regionKeyOf
// =============================================================================

test('regionKeyOf collapses both spellings Azure reports', () => {
  // The resource itself returns the display form; configuration uses the slug.
  // If these didn't compare equal, a colocated deployment would be reported as
  // a cross-region hop.
  assert.equal(regionKeyOf('Sweden Central'), 'swedencentral');
  assert.equal(regionKeyOf('swedencentral'), 'swedencentral');
  assert.equal(regionKeyOf('North Central US'), 'northcentralus');
  assert.equal(regionKeyOf('West-US-2'), 'westus2');
});

test('regionKeyOf treats missing values as empty', () => {
  assert.equal(regionKeyOf(''), '');
  assert.equal(regionKeyOf(null), '');
  assert.equal(regionKeyOf(undefined), '');
});

// =============================================================================
// describeModelSource
// =============================================================================

test('describeModelSource names the resource and its region', () => {
  assert.equal(
    describeModelSource({ resourceName: 'artagentanqvgqu7avl', region: 'Sweden Central' }),
    ' · artagentanqvgqu7avl · Sweden Central',
  );
});

test('describeModelSource labels managed Voice Live as the service, not an account', () => {
  // With BYOM off the models are Microsoft-hosted, so naming the AVL account
  // as their source would be wrong — but its region still applies.
  assert.equal(
    describeModelSource(
      { resourceName: 'artagentanqvgqu7avl', region: 'Sweden Central' },
      { managed: true },
    ),
    ' · managed Voice Live · Sweden Central',
  );
});

test('describeModelSource degrades to whichever half is known', () => {
  assert.equal(describeModelSource({ resourceName: 'contoso-aif' }), ' · contoso-aif');
  assert.equal(describeModelSource({ region: 'North Central US' }), ' · North Central US');
  assert.equal(describeModelSource({}), '');
  assert.equal(describeModelSource(null), '');
});

// =============================================================================
// crossRegionHint
// =============================================================================

const vl = { label: 'Voice Live', region: 'Sweden Central', resourceFallback: false };
const cascade = { label: 'Cascade models', region: 'North Central US' };

test('crossRegionHint flags the distance from the app to the model region', () => {
  const hint = crossRegionHint({ active: vl, app: 'westus2', other: cascade });

  assert.ok(hint);
  assert.equal(hint.title, 'Cross-region round trip');
  assert.match(hint.lines[0], /Voice Live — served from Sweden Central/);
  assert.match(hint.lines[0], /while this app runs in westus2/);
});

test('crossRegionHint also reports a Cascade/VoiceLive split', () => {
  const hint = crossRegionHint({ active: vl, app: 'westus2', other: cascade });

  assert.equal(hint.lines.length, 2);
  assert.match(hint.lines[1], /Cascade models — served from North Central US/);
});

test('crossRegionHint stays silent when everything is colocated', () => {
  assert.equal(
    crossRegionHint({
      active: { label: 'Voice Live', region: 'West US 2' },
      app: 'westus2',
      other: { label: 'Cascade models', region: 'westus2' },
    }),
    null,
  );
});

test('crossRegionHint compares canonically, not textually', () => {
  // 'Sweden Central' and 'swedencentral' are the same place.
  assert.equal(
    crossRegionHint({
      active: { label: 'Voice Live', region: 'Sweden Central' },
      app: 'swedencentral',
      other: { label: 'Cascade models', region: 'SWEDENCENTRAL' },
    }),
    null,
  );
});

test('crossRegionHint says nothing when a region is unknown', () => {
  // Better to show no advisory than to imply a hop we can't verify.
  assert.equal(crossRegionHint({ active: { label: 'Voice Live', region: '' }, app: 'westus2' }), null);
  assert.equal(crossRegionHint({ active: vl, app: '' }), null);
  assert.equal(crossRegionHint({}), null);
});

test('crossRegionHint does not report a split against a shared account', () => {
  // resourceFallback means VoiceLive has no dedicated account and is served by
  // the primary Foundry resource — one account cannot be in two regions, so the
  // differing region strings here are stale, not a real split.
  const hint = crossRegionHint({
    active: { label: 'Voice Live', region: 'North Central US', resourceFallback: true },
    app: 'northcentralus',
    other: { label: 'Cascade models', region: 'Sweden Central' },
  });

  assert.equal(hint, null);
});

test('crossRegionHint reports the app distance even for a shared account', () => {
  const hint = crossRegionHint({
    active: { label: 'Voice Live', region: 'North Central US', resourceFallback: true },
    app: 'westus2',
    other: { label: 'Cascade models', region: 'North Central US' },
  });

  assert.ok(hint);
  assert.equal(hint.lines.length, 1);
});
