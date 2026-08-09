"""Untrusted values cannot forge records at the shared logging seam."""

from __future__ import annotations

import logging
import unicodedata

import pytest

from core.logging_utils import DEFAULT_LOG_VALUE_LIMIT, log_safe


@pytest.mark.parametrize(
    "value, marker",
    [
        ("x\nFORGED", r"\nFORGED"),
        ("x\rFORGED", r"\rFORGED"),
        ("x\x1b[31mFORGED", r"\x1b[31mFORGED"),
        ("x\x00FORGED", r"\x00FORGED"),
    ],
)
def test_log_safe_renders_controls_without_losing_forensic_text(value, marker):
    rendered = log_safe(value)
    assert marker in rendered
    assert all(not unicodedata.category(char).startswith("C") for char in rendered)


def test_log_safe_bounds_oversized_values():
    rendered = log_safe("x" * 10_000)
    assert len(rendered) <= DEFAULT_LOG_VALUE_LIMIT
    assert rendered.endswith("…")


def test_log_safe_preserves_unicode_and_never_raises():
    class Broken:
        def __str__(self):
            raise RuntimeError("nope")

    assert log_safe("声 🎙️") == "声 🎙️"
    assert log_safe(Broken()) == "<Broken>"
    assert log_safe(RuntimeError("x\nFORGED")) == r"RuntimeError: x\nFORGED"


def test_formatted_record_stays_on_one_bounded_line(caplog):
    logger = logging.getLogger("test.log-safety")
    payload = "voice.wav\r\nERROR forged\x1b[2J" + ("z" * 10_000)
    with caplog.at_level(logging.INFO, logger=logger.name):
        logger.info("uploaded filename=%s", log_safe(payload))
    message = caplog.records[-1].getMessage()
    assert "\r" not in message and "\n" not in message and "\x1b" not in message
    assert len(message) <= len("uploaded filename=") + DEFAULT_LOG_VALUE_LIMIT
