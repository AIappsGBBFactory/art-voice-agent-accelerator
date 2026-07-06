"""Tests for the log pseudonymization helper in utils.pii_filter."""

from __future__ import annotations

from utils.pii_filter import mask_pii


def test_mask_pii_is_deterministic_and_correlatable():
    phone = "+14255551234"
    assert mask_pii(phone, prefix="phone") == mask_pii(phone, prefix="phone")


def test_mask_pii_does_not_leak_raw_value():
    phone = "+14255551234"
    token = mask_pii(phone, prefix="phone")
    assert phone not in token
    assert token.startswith("phone:")
    # Only the prefix plus a short hex digest, never the raw digits.
    assert token[len("phone:") :].isalnum()


def test_mask_pii_distinguishes_different_values():
    assert mask_pii("+14255551234", prefix="phone") != mask_pii(
        "+14255559999", prefix="phone"
    )


def test_mask_pii_handles_empty_and_none():
    assert mask_pii("", prefix="client") == "client:none"
    assert mask_pii(None, prefix="client") == "client:none"


def test_mask_pii_respects_digest_length():
    token = mask_pii("secret-value", prefix="k", digest_len=6)
    assert token.startswith("k:")
    assert len(token[len("k:") :]) == 6
