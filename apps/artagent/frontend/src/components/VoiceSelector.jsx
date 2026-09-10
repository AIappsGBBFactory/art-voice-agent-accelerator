import { memo, useMemo } from 'react';
import { Autocomplete, Box, IconButton, Stack, TextField, Tooltip, Typography } from '@mui/material';
import RefreshIcon from '@mui/icons-material/Refresh';
import { authoringAutocompleteSlots } from '../styles/authoringStyles.js';
import { MAI_VOICE_PRESETS, maiVoiceRank, voiceDisplayLabel } from '../utils/maiSpeech.js';

const languageNames = typeof Intl.DisplayNames === 'function'
  ? new Intl.DisplayNames(['en'], { type: 'language' }) : null;

function languageLabel(locale) {
  if (!locale || !languageNames) return locale || '';
  try {
    return languageNames.of(locale) || locale;
  } catch (error) {
    if (!(error instanceof RangeError)) throw error;
    return locale;
  }
}

const VoiceSelector = memo(function VoiceSelector({
  voices, value, onChange, metadata, loading = false, onRefresh, disabled = false,
}) {
  const options = useMemo(() => {
    const listed = new Set(voices.map((voice) => voice.name));
    const list = [...voices, ...MAI_VOICE_PRESETS.filter((voice) => !listed.has(voice.name))].map((voice) => ({
      ...voice, languageLabel: languageLabel(voice.language),
    }));
    if (value && !list.some((voice) => voice.name === value)) {
      list.unshift({ name: value, display_name: value, unlisted: true });
    }
    return list.sort((a, b) => (
      maiVoiceRank(a.name) - maiVoiceRank(b.name)
      || Number(Boolean(a.unavailablePreset)) - Number(Boolean(b.unavailablePreset))
      || (a.language || '').localeCompare(b.language || '')
      || (a.display_name || a.name).localeCompare(b.display_name || b.name)
      || a.name.localeCompare(b.name)
    ));
  }, [voices, value]);
  const selected = options.find((voice) => voice.name === value) || null;
  const count = metadata?.total_available ?? voices.length;
  const origin = metadata?.region || metadata?.resource_host || 'the configured Speech resource';
  const hasMai = voices.some((voice) => maiVoiceRank(voice.name) < 2);
  let provenance = '';
  if (loading) provenance = 'Loading the regional Speech voice catalog...';
  else if (metadata?.source === 'repository-configurations') {
    provenance = 'Repository voices only. This registration-only backend is not connected to the full regional catalog.';
  } else if (metadata?.catalog_complete) {
    provenance = `${count} voices from ${origin}${metadata.stale ? ' (stale cache)' : metadata.cached ? ' (cached)' : ''}.`;
  } else if (metadata?.source === 'static-catalog') {
    provenance = 'Limited starter presets. Regional availability is not verified.';
  } else if (metadata?.source === 'region-validated') {
    provenance = 'Region-checked presets only. This backend does not expose the full catalog.';
  }

  return (
    <Stack spacing={0.75} sx={{ minWidth: 0 }}>
      <Stack direction="row" alignItems="flex-start" gap={0.5}>
        <Autocomplete size="small" fullWidth loading={loading} disabled={disabled}
          options={options} value={selected} disableClearable
          slotProps={authoringAutocompleteSlots}
          getOptionLabel={voiceDisplayLabel}
          getOptionKey={(voice) => voice.name}
          getOptionDisabled={(voice) => Boolean(voice.unavailablePreset)}
          isOptionEqualToValue={(option, current) => option.name === current.name}
          filterOptions={(items, { inputValue }) => {
            const terms = inputValue.toLowerCase().trim().split(/\s+/).filter(Boolean);
            return items.filter((voice) => {
              const text = [
                voice.name, voice.display_name, voice.local_name, voice.language,
                voice.languageLabel, voice.gender, voice.category, ...(voice.styles || []),
              ].filter(Boolean).join(' ').toLowerCase();
              return terms.every((term) => text.includes(term));
            });
          }}
          onChange={(_, voice) => voice && onChange(voice.name)}
          renderOption={(props, voice) => {
            const { key, ...optionProps } = props;
            const label = voiceDisplayLabel(voice);
            return (
              <li key={key} {...optionProps}
                aria-label={voice.language ? `${label}, ${voice.languageLabel}, ${voice.name}` : label}>
                <Box sx={{ minWidth: 0, overflowWrap: 'anywhere' }}>
                  <Typography variant="body2" fontWeight={600}>{label}</Typography>
                  <Typography variant="caption" color="text.secondary" component="div">
                    {[voice.languageLabel, voice.gender, voice.category, voice.status].filter(Boolean).join(' / ')}
                  </Typography>
                  <Typography variant="caption" color="text.secondary" component="div">{voice.name}</Typography>
                  {voice.unavailablePreset && <Typography variant="caption" color="text.secondary" component="div">
                    Not verified for this resource
                  </Typography>}
                </Box>
              </li>
            );
          }}
          renderInput={(params) => <TextField {...params} label="Voice" placeholder="Search name, language, or style" />} />
        {onRefresh && (
          <Tooltip title="Refresh regional voice catalog">
            <span><IconButton size="small" aria-label="Refresh regional voice catalog"
              disabled={loading || disabled} onClick={onRefresh} sx={{ mt: 0.5 }}>
              <RefreshIcon fontSize="small" />
            </IconButton></span>
          </Tooltip>
        )}
      </Stack>
      {provenance && <Typography variant="caption" color="text.secondary">{provenance}</Typography>}
      {!loading && !hasMai && <Typography variant="caption" color="text.secondary">
        MAI voices are listed first for visibility, but need a supported Speech resource/region.
        They were not returned by this catalog.
      </Typography>}
      {!loading && metadata?.warnings?.map((warning, index) => (
        <Typography key={index} variant="caption" color="warning.dark">{warning}</Typography>
      ))}
      {!loading && selected?.unlisted && metadata?.catalog_complete && (
        <Typography variant="caption" color="warning.dark">
          The current voice was not returned by this resource. It is preserved until you choose another.
        </Typography>
      )}
    </Stack>
  );
});

export default VoiceSelector;
