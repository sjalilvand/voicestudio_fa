"""Admission for inbound mode: per-panel keys, hashing, throttling.

Inbound trades away the TLS pinning and single-use enrollment token that
outbound relies on (docs/adr/inbound-node-mode.md), so the API key is the
whole of admission. These tests exist because everything that protects it —
hashing at rest, per-key revocation, the failed-auth throttle — is invisible in
normal use and would fail silently if it regressed.
"""

from __future__ import annotations

import json
import os
import stat

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


def test_failed_key_throttle_ignores_ephemeral_source_ports(store):
    """Reconnects from one host must contribute to the same lockout."""
    store.issue("Alice")

    for port in range(41000, 41000 + keys_module._MAX_FAILURES):
        store.authenticate("ovnode_wrong", peer=f"10.0.0.9:{port}")

    assert store.locked_out("10.0.0.9:49999") is True


def test_failed_key_throttle_normalises_bracketed_ipv6_ports(store):
    store.issue("Alice")

    for port in range(41000, 41000 + keys_module._MAX_FAILURES):
        store.authenticate("ovnode_wrong", peer=f"[fd00::9]:{port}")

    assert store.locked_out("[fd00::9]:49999") is True


def test_an_empty_key_never_authenticates(store):
    """A missing metadata header arrives as "" and must not match a key whose
    hash happens to be falsy-adjacent."""
    store.issue("Alice")
    assert store.authenticate("", peer="10.0.0.1") is None


def test_keys_survive_a_restart(store, tmp_path):
    issued = store.issue("Alice")

    reopened = KeyStore(str(tmp_path / "inbound-keys.json"))

    assert reopened.authenticate(issued.secret, peer="10.0.0.1") is not None


def test_pasted_connection_secrets_use_the_protected_key_file(store, tmp_path):
    secret = KEY_PREFIX + "s" * 40
    store.remember_connection_secret("10.0.0.2:7444", secret)

    reopened = KeyStore(str(tmp_path / "inbound-keys.json"))

    assert reopened.connection_secret("10.0.0.2:7444") == secret
    if os.name != "nt":
        assert stat.S_IMODE((tmp_path / "inbound-keys.json").stat().st_mode) == 0o600


def test_legacy_saved_connection_is_migrated_out_of_settings(store, monkeypatch):
    from worker.inbound import service as inbound_service

    secret = KEY_PREFIX + "s" * 40
    legacy = format_connection(host="10.0.0.2", port=7444, secret=secret)
    settings = {inbound_service._SAVED_KEY: legacy}
    monkeypatch.setattr(
        inbound_service,
        "_setting",
        lambda name, default="": settings.get(name, default),
    )
    monkeypatch.setattr(
        inbound_service,
        "_set_setting",
        lambda name, value: settings.__setitem__(name, value),
    )

    outbound = inbound_service.OutboundNodes(store)

    assert outbound.saved() == ["10.0.0.2:7444"]
    assert secret not in settings[inbound_service._SAVED_KEY]
    assert store.connection_secret("10.0.0.2:7444") == secret


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


# ── Settings gate ──────────────────────────────────────────────────────────


def test_the_bind_is_localhost_until_someone_widens_it(monkeypatch):
    """With no TLS, the difference between localhost and 0.0.0.0 is the
    difference between a credential on one machine and a credential on a
    network. It must never widen as a side effect of enabling the feature."""
    from worker.inbound import service as inbound_service

    monkeypatch.delenv("OMNIVOICE_INBOUND_BIND", raising=False)
    monkeypatch.setattr(inbound_service, "_setting", lambda name, default="": default)

    assert inbound_service.bind_host() == "127.0.0.1"
    assert inbound_service.is_exposed("127.0.0.1") is False


def test_a_wider_bind_is_reported_as_exposed():
    """The UI needs to say so at the point the bind is widened, not bury it."""
    from worker.inbound import service as inbound_service

    assert inbound_service.is_exposed("0.0.0.0") is True
    assert inbound_service.is_exposed("192.168.0.110") is True
    assert inbound_service.is_exposed("localhost") is False


def test_inbound_is_off_unless_it_was_turned_on(monkeypatch):
    from worker.inbound import service as inbound_service

    monkeypatch.delenv("OMNIVOICE_INBOUND_NODE", raising=False)
    monkeypatch.setattr(inbound_service, "_setting", lambda name, default="": default)

    assert inbound_service.enabled() is False


@pytest.mark.asyncio
async def test_environment_override_rejects_ui_enablement_changes(monkeypatch):
    from fastapi import HTTPException

    from api.routers import workers as workers_router
    from worker.inbound import service as inbound_service

    monkeypatch.setenv("OMNIVOICE_INBOUND_NODE", "true")
    changed = []
    monkeypatch.setattr(inbound_service, "set_enabled", lambda value: changed.append(value))

    with pytest.raises(HTTPException) as excinfo:
        await workers_router.set_inbound_enabled(
            workers_router.InboundEnableRequest(enabled=False)
        )

    assert excinfo.value.status_code == 409
    assert changed == []
    assert inbound_service.enabled() is True


def test_a_wildcard_bind_never_reaches_the_connection_string(monkeypatch):
    """0.0.0.0 is legal to bind and meaningless to dial.

    Found on hardware: with the listener bound to every interface, the issued
    string came out as ovnode://…@0.0.0.0:7444, which fails on the far end with
    a connection error that names nothing. The string has to carry an address
    the other machine can actually reach.
    """
    from worker.inbound import service as inbound_service

    monkeypatch.setattr(inbound_service, "bind_host", lambda: "0.0.0.0")
    monkeypatch.setattr(inbound_service, "bind_port", lambda: 7444)

    node = inbound_service.InboundNode()
    text = node.connection_string("ovnode_" + "k" * 40)

    assert "0.0.0.0" not in text
    assert parse_connection(text).host not in ("0.0.0.0", "", "*")


def test_an_explicit_bind_is_advertised_as_given(monkeypatch):
    """Only wildcards are substituted — a user who typed a specific address
    meant that address, including one this host cannot introspect."""
    from worker.inbound import service as inbound_service

    monkeypatch.setattr(inbound_service, "bind_host", lambda: "192.168.0.202")

    assert inbound_service.advertised_host() == "192.168.0.202"


# ── Idle-unload tunables ───────────────────────────────────────────────────


def test_the_idle_threshold_can_be_shortened_for_testing(monkeypatch):
    """Ten minutes is right in production and useless to observe by hand."""
    from services import tts_backend

    monkeypatch.setenv("OMNIVOICE_ENGINE_IDLE_UNLOAD_SECONDS", "60")
    assert tts_backend._idle_seconds_from_env(
        "OMNIVOICE_ENGINE_IDLE_UNLOAD_SECONDS", 600.0, floor=5.0
    ) == 60.0


def test_a_zero_or_junk_idle_threshold_is_refused(monkeypatch, caplog):
    """A zero threshold unloads an engine the instant it goes idle, so a busy
    machine reloads it for every request. Falling back loudly beats honouring
    a value that quietly destroys throughput."""
    from services import tts_backend

    for bad in ("0", "-5", "abc", "2"):
        monkeypatch.setenv("OMNIVOICE_ENGINE_IDLE_UNLOAD_SECONDS", bad)
        with caplog.at_level("WARNING"):
            value = tts_backend._idle_seconds_from_env(
                "OMNIVOICE_ENGINE_IDLE_UNLOAD_SECONDS", 600.0, floor=5.0
            )
        assert value == 600.0, f"{bad!r} should not have been honoured"
    assert "Ignoring" in caplog.text


def test_the_sweep_interval_can_be_shortened_with_the_threshold(monkeypatch):
    """Shortening only the threshold still means waiting a full minute to see
    a thirty-second rule fire, which reads as a broken sweep."""
    from worker import agent

    monkeypatch.setenv("OMNIVOICE_IDLE_SWEEP_SECONDS", "5")
    assert agent._sweep_seconds_from_env() == 5.0

    monkeypatch.setenv("OMNIVOICE_IDLE_SWEEP_SECONDS", "0")
    assert agent._sweep_seconds_from_env() == 60.0


# ── Preload on a node ──────────────────────────────────────────────────────


def test_a_worker_machine_does_not_preload_a_model(monkeypatch, caplog):
    """A node has no local user to warm the model for.

    The startup preload exists so the first /generate feels instant for the
    person in front of the app. On a headless GPU node there is nobody there,
    so it is several GB held from boot against a request that may never
    arrive — and the idle sweep cannot reclaim it, because the sweep owns the
    worker executor's engines while this is the default local model. Observed
    on hardware: a node that had run nothing still sat at 2.4 GB.
    """
    import asyncio

    from services import model_manager

    monkeypatch.setenv("OMNIVOICE_WORKER_MODE", "1")
    monkeypatch.setattr(model_manager, "model", None)
    loaded = {"count": 0}
    monkeypatch.setattr(
        model_manager,
        "_checkpoint_in_local_cache",
        lambda *a, **k: loaded.__setitem__("count", loaded["count"] + 1) or True,
    )

    with caplog.at_level("INFO"):
        asyncio.run(model_manager.preload_model())

    assert loaded["count"] == 0, "a worker machine still went looking for a model to preload"
    assert "loads on first request" in caplog.text


def test_a_desktop_machine_still_preloads(monkeypatch):
    """A machine that is both an app and a worker keeps the warm-up — there is
    a real user in front of it and the whole point of preloading stands."""
    from services import model_manager

    monkeypatch.delenv("OMNIVOICE_WORKER_MODE", raising=False)

    assert model_manager._headless_worker() is False
