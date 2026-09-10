"""Discover every voice from the configured Speech resource, outside the audio path."""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from apps.artagent.backend.api.v1.schemas.voices import VoiceInfo
from apps.artagent.backend.config import get_config_value
from azure.core.exceptions import AzureError
from utils.ml_logging import get_logger

logger = get_logger(__name__)
CATALOG_TTL_SECONDS = 600
FAILURE_TTL_SECONDS = 30
MAX_STALE_SECONDS = 3600
DISCOVERY_TIMEOUT_SECONDS = 12
MAX_CACHED_RESOURCES = 4


@dataclass(frozen=True)
class SpeechVoiceScope:
    """Configuration captured at request time; credentials never enter the response."""

    region: str
    endpoint: str
    resource_id: str
    key: str = field(repr=False)

    @property
    def cache_key(self) -> tuple[str, str, str, str]:
        return (
            self.region,
            self.endpoint,
            self.resource_id,
            hashlib.sha256(self.key.encode()).hexdigest(),
        )

    @property
    def resource_host(self) -> str | None:
        return urlsplit(self.endpoint).hostname if self.endpoint else None


@dataclass(frozen=True)
class VoiceSnapshot:
    voices: tuple[VoiceInfo, ...]
    retrieved_at: float


@dataclass(frozen=True)
class VoiceDiscovery:
    scope: SpeechVoiceScope
    snapshot: VoiceSnapshot | None
    cached: bool = False
    stale: bool = False
    warning: str | None = None


class VoiceCatalogUnavailable(RuntimeError):
    """A configured resource could not provide its voice catalog."""


_cache: OrderedDict[tuple[str, str, str, str], VoiceSnapshot] = OrderedDict()
_failures: OrderedDict[tuple[str, str, str, str], tuple[float, str]] = OrderedDict()
_pending: dict[tuple[str, str, str, str], asyncio.Task[VoiceSnapshot]] = {}


def speech_voice_scope() -> SpeechVoiceScope:
    """Resolve current configuration rather than stale import-time settings."""
    return SpeechVoiceScope(
        region=get_config_value("azure/speech/region", default="") or "",
        endpoint=get_config_value("azure/speech/endpoint", default="") or "",
        resource_id=get_config_value("azure/speech/resource-id", default="") or "",
        key=get_config_value("azure/speech/key", "AZURE_SPEECH_KEY", default="") or "",
    )


def voice_category(name: str) -> str:
    """Preserve the Builder's family categories without restricting the catalog."""
    lowered = name.lower()
    if ":mai-" in lowered:
        return "mai"
    if "dragonhd" in lowered:
        return "hd"
    if "turbo" in lowered:
        return "turbo"
    return "standard"


def _query_voice_snapshot(scope: SpeechVoiceScope) -> VoiceSnapshot:
    """Run the existing Speech SDK enumeration with no synthesis or microphone."""
    if not scope.region and not scope.endpoint:
        raise VoiceCatalogUnavailable("The backend has no configured Speech region or endpoint.")
    try:
        import azure.cognitiveservices.speech as speechsdk

        address = {"endpoint": scope.endpoint} if scope.endpoint else {"region": scope.region}
        if scope.key:
            config = speechsdk.SpeechConfig(subscription=scope.key, **address)
        else:
            if not scope.resource_id:
                raise VoiceCatalogUnavailable(
                    "Speech resource ID is required for Entra authentication."
                )
            from src.speech.auth_manager import SpeechTokenManager, get_speech_token_manager
            from utils.azure_auth import get_credential

            manager = get_speech_token_manager()
            if manager.resource_id != scope.resource_id:
                manager = SpeechTokenManager(get_credential(), scope.resource_id)
            config = speechsdk.SpeechConfig(**address)
            manager.apply_to_config(config)
        synthesizer = speechsdk.SpeechSynthesizer(speech_config=config, audio_config=None)
        result = synthesizer.get_voices_async().get()
        if result.reason != speechsdk.ResultReason.VoicesListRetrieved or result.voices is None:
            raise VoiceCatalogUnavailable("Speech did not return its regional voice catalog.")
        voices = []
        for voice in result.voices:
            if not voice.short_name or not voice.locale:
                raise VoiceCatalogUnavailable("Speech returned incomplete voice metadata.")
            voices.append(
                VoiceInfo(
                    name=voice.short_name,
                    display_name=voice.local_name or voice.short_name,
                    local_name=voice.local_name or "",
                    category=voice_category(voice.short_name),
                    language=voice.locale,
                    gender=getattr(voice.gender, "name", ""),
                    voice_type=getattr(voice.voice_type, "name", ""),
                    styles=list(voice.style_list or []),
                    status=getattr(voice.status, "name", voice.status) or "",
                )
            )
        ordered = {voice.name: voice for voice in voices}
        return VoiceSnapshot(
            voices=tuple(sorted(ordered.values(), key=lambda voice: (voice.language, voice.name))),
            retrieved_at=time.time(),
        )
    except VoiceCatalogUnavailable:
        raise
    except (ImportError, AzureError, RuntimeError, OSError, ValueError) as cause:
        logger.warning("Regional voice discovery failed (%s).", type(cause).__name__)
        raise VoiceCatalogUnavailable(
            "The full Speech voice catalog could not be retrieved. Check the resource connection and retry."
        ) from cause


def _remember(cache: OrderedDict, key: tuple[str, str, str, str], value: Any) -> None:
    cache[key] = value
    cache.move_to_end(key)
    while len(cache) > MAX_CACHED_RESOURCES:
        cache.popitem(last=False)


async def _load(scope: SpeechVoiceScope) -> VoiceSnapshot:
    try:
        snapshot = await asyncio.to_thread(_query_voice_snapshot, scope)
    except VoiceCatalogUnavailable as cause:
        _remember(_failures, scope.cache_key, (time.time() + FAILURE_TTL_SECONDS, str(cause)))
        raise
    _remember(_cache, scope.cache_key, snapshot)
    _failures.pop(scope.cache_key, None)
    logger.info(
        "Discovered %d Speech voices for region %s.",
        len(snapshot.voices),
        scope.region or "resource endpoint",
    )
    return snapshot


def _finished(key: tuple[str, str, str, str], task: asyncio.Task[VoiceSnapshot]) -> None:
    if _pending.get(key) is task:
        _pending.pop(key, None)
    if not task.cancelled():
        # A caller timeout must not leave a late discovery failure unobserved.
        error = task.exception()
        if error is not None and not isinstance(error, VoiceCatalogUnavailable):
            logger.error("Voice discovery failed unexpectedly (%s).", type(error).__name__)


async def discover_voice_catalog(*, use_cache: bool = True) -> VoiceDiscovery:
    """Coalesce catalog requests and bound caller waits without blocking audio handlers."""
    scope = speech_voice_scope()
    key = scope.cache_key
    now = time.time()
    cached = _cache.get(key)
    if use_cache and cached is not None and now - cached.retrieved_at < CATALOG_TTL_SECONDS:
        return VoiceDiscovery(scope, cached, cached=True)
    failure = _failures.get(key)
    warning = failure[1] if use_cache and failure and now < failure[0] else None
    if not warning:
        task = _pending.get(key)
        if task is not None and task.done():
            _pending.pop(key, None)
            task = None
        if task is None:
            if len(_pending) >= MAX_CACHED_RESOURCES:
                warning = "Voice discovery is busy. Retry shortly."
            else:
                task = asyncio.create_task(_load(scope))
                _pending[key] = task
                task.add_done_callback(lambda completed: _finished(key, completed))
        if task is not None:
            try:
                snapshot = await asyncio.wait_for(
                    asyncio.shield(task), timeout=DISCOVERY_TIMEOUT_SECONDS
                )
                return VoiceDiscovery(scope, snapshot)
            except TimeoutError:
                warning = "Speech voice discovery is taking too long. Retry shortly."
            except VoiceCatalogUnavailable as cause:
                warning = str(cause)
    if cached is not None and now - cached.retrieved_at < MAX_STALE_SECONDS:
        return VoiceDiscovery(scope, cached, cached=True, stale=True, warning=warning)
    return VoiceDiscovery(scope, None, warning=warning)
