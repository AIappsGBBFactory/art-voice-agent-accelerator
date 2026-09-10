"""Tests for EasyAuth identity obfuscation in session telemetry attributes.

Verifies that the signed-in operator identity is emitted only as a stable,
non-reversible pseudonym via the OpenTelemetry ``enduser.id`` semantic
convention (which the Azure Monitor exporter maps to the App Insights
authenticated user), and that the raw Entra oid / email never reach telemetry.
"""

from __future__ import annotations

from utils.pii_filter import mask_pii
from utils.session_context import SessionCorrelation

_OID = "11111111-2222-3333-4444-555555555555"
_EMAIL = "alice@contoso.com"


def test_authenticated_identity_is_obfuscated_as_enduser_id():
    corr = SessionCorrelation(
        session_id="sess-123",
        user_id=_OID,
        user_email=_EMAIL,
        device_id="device_abc",
    )
    attrs = corr.to_span_attributes()

    # enduser.id → App Insights authenticated user, obfuscated (never the oid).
    assert attrs["enduser.id"] == mask_pii(_OID, prefix="user")
    assert _OID not in attrs["enduser.id"]
    assert attrs["enduser.authenticated"] is True


def test_pseudonym_is_cross_tier_compatible_with_frontend():
    # The frontend telemetry maskId (SHA-256 of "<salt>:<value>", first 10 hex,
    # default salt "artvoice-log-pseudonym-v1") must byte-match the backend so
    # the same operator correlates browser↔server. Locking this value keeps the
    # two implementations in sync.
    assert mask_pii(_OID, prefix="user") == "user:240adbc1ac"


def test_raw_identity_never_appears_in_span_attributes():
    corr = SessionCorrelation(session_id="sess-123", user_id=_OID, user_email=_EMAIL)
    attrs = corr.to_span_attributes()

    flat = " ".join(f"{k}={v}" for k, v in attrs.items())
    assert _OID not in flat
    assert _EMAIL not in flat
    # Legacy raw-PII attributes must be gone.
    assert "enduser.email" not in attrs
    assert "ai.user.authenticatedId" not in attrs


def test_anonymous_user_uses_pseudo_id_bucket():
    corr = SessionCorrelation(session_id="sess-9", device_id="device_xyz")
    attrs = corr.to_span_attributes()

    assert attrs["enduser.pseudo.id"] == "device_xyz"
    assert "enduser.id" not in attrs
    assert "enduser.authenticated" not in attrs


def test_log_record_pseudonymizes_identity():
    corr = SessionCorrelation(session_id="sess-1", user_id=_OID, user_email=_EMAIL)
    record = corr.to_log_record()

    assert record["user_id"] == mask_pii(_OID, prefix="user")
    assert record["user_email"] == mask_pii(_EMAIL, prefix="email")
    assert _OID not in str(record.values())
    assert _EMAIL not in str(record.values())
