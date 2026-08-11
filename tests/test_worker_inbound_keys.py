"""Admission for inbound mode: per-panel keys, hashing, throttling.

Inbound trades away the TLS pinning and single-use enrollment token that
outbound relies on (docs/adr/0002-inbound-node-mode.md), so the API key is the
whole of admission. These tests exist because everything that protects it —
hashing at rest, per-key revocation, the failed-auth throttle — is invisible in
normal use and would fail silently if it regressed.
"""

from __future__ import annotations

import json

import pytest

from worker.inbound import keys as keys_module
from worker.inbound.connection_string import (
    InvalidConnectionString,
    format_connection,
    parse_connection,
)
from worker.inbound.keys import KEY_PREFIX, KeyStore


@pytest.fixture
def store(tmp_path):
    return KeyStore(str(tmp_path / "inbound-keys.json"))


def test_the_plaintext_key_is_never_written_to_disk(store, tmp_path):
    """The node can replace a key but must never be able to show it again."""
    issued = store.issue("Alice laptop")

    on_disk = (tmp_path / "inbound-keys.json").read_text(encoding="utf-8")
    assert issued.secret not in on_disk
    assert issued.key.secret_hash in on_disk

    # And nothing in the API hands it back either — a "reveal key" button is
    # the feature this shape exists to make impossible to build by accident.
    assert all("secret" not in row for row in store.list_keys())


def test_revoking_one_panel_leaves_the_others_working(store):
    """The whole reason keys are per-panel rather than one shared node key."""
    alice = store.issue("Alice")
    bob = store.issue("Bob")

    assert store.revoke(alice.key.key_id) is True

    assert store.authenticate(alice.secret, peer="10.0.0.1") is None
    assert store.authenticate(bob.secret, peer="10.0.0.2") is not None


def test_a_wrong_key_is_throttled_before_it_can_be_guessed(store, monkeypatch):
    """A bearer credential with no second factor has only this between it and
    unlimited LAN guesses."""
    store.issue("Alice")

    for _ in range(keys_module._MAX_FAILURES):
        assert store.authenticate("ovnode_wrong", peer="10.0.0.9") is None

    assert store.locked_out("10.0.0.9") is True


def test_one_panel_typing_a_stale_key_cannot_lock_out_another(store):
    """The throttle is per source address on purpose: a shared counter turns
    one person's stale bookmark into an outage for everybody else."""
    good = store.issue("Bob")

    for _ in range(keys_module._MAX_FAILURES + 2):
        store.authenticate("ovnode_wrong", peer="10.0.0.9")

    assert store.locked_out("10.0.0.9") is True
    assert store.locked_out("10.0.0.10") is False
    assert store.authenticate(good.secret, peer="10.0.0.10") is not None


def test_a_locked_out_peer_is_refused_even_with_the_right_key(store):
    """Otherwise the throttle is decorative: an attacker who eventually
    guesses correctly is admitted on the guess that succeeds."""
    good = store.issue("Bob")
    for _ in range(keys_module._MAX_FAILURES):
        store.authenticate("ovnode_wrong", peer="10.0.0.9")

    assert store.authenticate(good.secret, peer="10.0.0.9") is None


def test_an_empty_key_never_authenticates(store):
    """A missing metadata header arrives as "" and must not match a key whose
    hash happens to be falsy-adjacent."""
    store.issue("Alice")
    assert store.authenticate("", peer="10.0.0.1") is None


def test_keys_survive_a_restart(store, tmp_path):
    issued = store.issue("Alice")

    reopened = KeyStore(str(tmp_path / "inbound-keys.json"))

    assert reopened.authenticate(issued.secret, peer="10.0.0.1") is not None


def test_a_corrupt_key_file_is_reported_rather_than_read_as_no_keys(tmp_path, caplog):
    """Silently becoming "no keys configured" reads to the user as "my keys
    vanished", with the cause nowhere."""
    path = tmp_path / "inbound-keys.json"
    path.write_text("{not json", encoding="utf-8")

    with caplog.at_level("ERROR"):
        store = KeyStore(str(path))

    assert store.list_keys() == []
    assert "unreadable" in caplog.text


def test_authentication_records_who_connected_and_from_where(store):
    issued = store.issue("Alice laptop")

    store.authenticate(issued.secret, peer="10.0.0.5")

    row = store.list_keys()[0]
    assert row["label"] == "Alice laptop"
    assert row["last_seen_peer"] == "10.0.0.5"
    assert row["last_seen_at"] > 0


# ── Connection string ──────────────────────────────────────────────────────


def test_the_connection_string_round_trips(store):
    issued = store.issue("Alice")
    text = format_connection(host="192.168.0.110", port=7444, secret=issued.secret)

    parsed = parse_connection(text)

    assert parsed.host == "192.168.0.110"
    assert parsed.port == 7444
    assert parsed.secret == issued.secret
    assert parsed.endpoint == "192.168.0.110:7444"


def test_an_ipv6_node_is_bracketed_for_grpc():
    """gRPC's resolver reads an unbracketed IPv6 address as host:port and
    fails on the wrong half of it."""
    text = format_connection(host="fd00::1", port=7444, secret=KEY_PREFIX + "a" * 32)

    assert parse_connection(text).endpoint == "[fd00::1]:7444"


def test_the_secret_never_appears_in_the_loggable_form():
    connection = parse_connection(
        format_connection(host="10.0.0.2", port=7444, secret=KEY_PREFIX + "s" * 40)
    )

    redacted = connection.redacted()

    assert connection.secret not in redacted
    assert "10.0.0.2:7444" in redacted


@pytest.mark.parametrize(
    "text, expected",
    [
        ("192.168.0.110:7444", "without a key"),
        ("ovnode://192.168.0.110:7444", "no key in it"),
        ("https://192.168.0.110:7444", "connection string"),
        ("ovnode://ovnode_short@10.0.0.1:7444", "not in the expected format"),
        ("", "Paste the connection string"),
    ],
)
def test_a_malformed_connection_string_says_what_is_wrong(text, expected):
    """Every one of these otherwise surfaces as "cannot connect", which is the
    same thing a firewall, a wrong port and a dead node all say."""
    with pytest.raises(InvalidConnectionString) as excinfo:
        parse_connection(text)

    assert expected in str(excinfo.value)


def test_pasting_an_outbound_enrollment_token_says_so():
    """The two credentials look alike and go in opposite directions; "invalid
    key" would send someone hunting for a typo that is not there."""
    with pytest.raises(InvalidConnectionString) as excinfo:
        parse_connection("ovnode://ovw_" + "a" * 40 + "@10.0.0.1:7444")

    assert "other direction" in str(excinfo.value)
