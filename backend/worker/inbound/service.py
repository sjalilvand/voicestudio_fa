"""Lifecycle for inbound mode on both sides, and the settings that gate it.

Two independent switches, deliberately not one:

  * **Accept connections** turns this machine into a node other panels can
    dial. Off by default.
  * **Saved connections** are the nodes this panel dials out to. Adding one is
    what pasting a connection string does.

A machine can do both — a workstation with a GPU that also drives jobs on a
second box — which is why neither implies the other.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Optional

from worker.inbound.artifacts import ArtifactStore
from worker.inbound.connection_log import ConnectionLog
from worker.inbound.connection_string import (
    Connection,
    InvalidConnectionString,
    format_connection,
    parse_connection,
)
from worker.inbound.keys import KeyStore
from worker.inbound.listener import DEFAULT_BIND, DEFAULT_PORT, NodeListener

logger = logging.getLogger(__name__)

_ENABLED_KEY = "inbound_node_enabled"
_BIND_KEY = "inbound_node_bind"
_PORT_KEY = "inbound_node_port"
_SAVED_KEY = "inbound_saved_nodes"


def _setting(name: str, default: str = "") -> str:
    try:
        from services import settings_store  # noqa: PLC0415

        return (settings_store.get_text(name, default) or default).strip()
    except Exception:
        return default


def _set_setting(name: str, value: str) -> None:
    from services import settings_store  # noqa: PLC0415

    settings_store.set_text(name, value)


def enabled() -> bool:
    """Whether this machine accepts inbound connections. Off unless asked.

    Environment first so a headless node can be brought up without a UI, then
    settings for the desktop case — the same precedence remote workers uses.
    """
    env = (os.environ.get("OMNIVOICE_INBOUND_NODE") or "").strip().lower()
    if env in ("1", "true", "yes", "on"):
        return True
    if env in ("0", "false", "no", "off"):
        return False
    return _setting(_ENABLED_KEY).lower() in ("1", "true", "yes", "on")


def set_enabled(value: bool) -> None:
    _set_setting(_ENABLED_KEY, "true" if value else "false")


def bind_host() -> str:
    """Where the listener binds.

    Localhost by default, which is nearly useless on its own — that is the
    point. Reaching this node from another machine should be a decision
    somebody made, not a side effect of turning the feature on.
    """
    return os.environ.get("OMNIVOICE_INBOUND_BIND") or _setting(_BIND_KEY) or DEFAULT_BIND


def set_bind_host(value: str) -> None:
    _set_setting(_BIND_KEY, (value or "").strip() or DEFAULT_BIND)


def bind_port() -> int:
    raw = os.environ.get("OMNIVOICE_INBOUND_PORT") or _setting(_PORT_KEY)
    try:
        return int(raw) if raw else DEFAULT_PORT
    except ValueError:
        return DEFAULT_PORT


def set_bind_port(value: int) -> None:
    _set_setting(_PORT_KEY, str(int(value)))


def is_exposed(host: Optional[str] = None) -> bool:
    """True when the listener is reachable from other machines.

    The UI says so at the point the bind is widened, because with no TLS this
    is the difference between a credential on one machine and a credential on
    a network (docs/adr/inbound-node-mode.md).
    """
    return (host if host is not None else bind_host()) not in (
        "127.0.0.1",
        "localhost",
        "::1",
    )


def paths() -> dict[str, str]:
    from worker.service import paths as worker_paths  # noqa: PLC0415

    root = worker_paths()["root"]
    return {
        "keys": os.path.join(root, "inbound-keys.json"),
        "staged": os.path.join(root, "inbound-staged"),
    }


class InboundNode:
    """This machine as a node other panels can dial."""

    def __init__(self) -> None:
        self._listener: Optional[NodeListener] = None
        self._keys: Optional[KeyStore] = None
        self._log = ConnectionLog()
        self.startup_error: Optional[str] = None

    @property
    def keys(self) -> KeyStore:
        if self._keys is None:
            self._keys = KeyStore(paths()["keys"])
        return self._keys

    @property
    def log(self) -> ConnectionLog:
        return self._log

    @property
    def running(self) -> bool:
        return self._listener is not None and self._listener.running

    @property
    def port(self) -> int:
        return self._listener.port if self._listener else 0

    def _client_factory(self, artifacts: ArtifactStore, key_id: str):
        # Imported here so a machine that never accepts connections does not
        # pay for the executor or grpc at startup.
        from worker import capabilities  # noqa: PLC0415
        from worker.agent import _paths as agent_paths  # noqa: PLC0415
        from worker.executor import TaskExecutor  # noqa: PLC0415
        from worker.identity import load_or_create_worker_key  # noqa: PLC0415
        from worker.transport.client import (  # noqa: PLC0415
            WorkerClient,
            WorkerConfig,
            describe_host,
        )

        locations = agent_paths()
        os.makedirs(locations["root"], exist_ok=True)
        keypair = load_or_create_worker_key(locations["worker_key"])
        discovered = capabilities.discover(include_unavailable=True)
        host = describe_host()
        host["gpus"] = capabilities.describe_gpus()

        executor = TaskExecutor()
        return WorkerClient(
            WorkerConfig(
                endpoint="",
                cert_fingerprint="",
                certificate_pem=b"",
                keypair=keypair,
                # Per panel key, not per node: each panel keeps its own
                # registry, so the same machine is a different worker id to
                # each of them, and the node signs its challenge over that id.
                worker_id=self.keys.worker_id_for(key_id),
                enrollment_token="",
                max_concurrent_tasks=capabilities.max_concurrent_tasks(discovered),
                capabilities=discovered,
                host=host,
            ),
            execute=executor.execute,
            capability_probe=lambda: capabilities.discover(include_unavailable=True),
            on_registered=lambda wid: self.keys.remember_worker_id(key_id, wid),
            artifacts=artifacts,
        )

    async def start(self) -> None:
        if self._listener is not None:
            return
        self.startup_error = None
        listener = NodeListener(
            keys=self.keys,
            log=self._log,
            artifacts=ArtifactStore(paths()["staged"]),
            client_factory=self._client_factory,
        )
        try:
            await listener.start(host=bind_host(), port=bind_port())
        except Exception as exc:
            # A node that cannot listen must say so in the UI rather than look
            # enabled and quietly accept nothing.
            self.startup_error = str(exc)
            logger.error("Could not start the inbound listener: %s", exc)
            return
        self._listener = listener

    async def stop(self) -> None:
        listener, self._listener = self._listener, None
        if listener is not None:
            await listener.stop()

    def connection_string(self, secret: str, *, host: Optional[str] = None) -> str:
        """The one artifact a user copies to another machine."""
        return format_connection(
            host=host or bind_host(), port=self.port or bind_port(), secret=secret
        )

    def snapshot(self) -> dict:
        state = self._log.snapshot()
        host = bind_host()
        return {
            "enabled": enabled(),
            "running": self.running,
            "bind": host,
            "port": self.port or bind_port(),
            "exposed": is_exposed(host),
            "startup_error": self.startup_error,
            "keys": self.keys.list_keys(),
            **state,
        }


class OutboundNodes:
    """Nodes this panel dials. One connection per saved entry."""

    def __init__(self) -> None:
        self._connections: dict[str, object] = {}
        self._tasks: dict[str, asyncio.Task] = {}

    def saved(self) -> list[str]:
        raw = _setting(_SAVED_KEY)
        return [line for line in raw.splitlines() if line.strip()]

    def _save(self, entries: list[str]) -> None:
        _set_setting(_SAVED_KEY, "\n".join(entries))

    async def add(self, text: str, servicer) -> Connection:
        """Parse, save and dial. Raises InvalidConnectionString on a bad paste."""
        connection = parse_connection(text)
        entries = self.saved()
        # Keyed by endpoint: re-pasting a rotated key for the same machine
        # replaces it rather than leaving a dead entry that retries forever.
        entries = [e for e in entries if _endpoint_of(e) != connection.endpoint]
        entries.append(text.strip())
        self._save(entries)
        await self._dial(connection, servicer)
        return connection

    async def remove(self, endpoint: str) -> bool:
        entries = [e for e in self.saved() if _endpoint_of(e) != endpoint]
        self._save(entries)
        connection = self._connections.pop(endpoint, None)
        task = self._tasks.pop(endpoint, None)
        if connection is not None:
            await connection.stop()
        if task is not None:
            task.cancel()
        return connection is not None

    async def start_all(self, servicer) -> None:
        for entry in self.saved():
            try:
                await self._dial(parse_connection(entry), servicer)
            except InvalidConnectionString as exc:
                logger.warning("Ignoring a saved connection that no longer parses: %s", exc)

    async def _dial(self, connection: Connection, servicer) -> None:
        from worker.inbound.connector import NodeConnection  # noqa: PLC0415

        if connection.endpoint in self._connections:
            return
        node = NodeConnection(servicer, connection)
        self._connections[connection.endpoint] = node
        self._tasks[connection.endpoint] = asyncio.create_task(
            node.run_forever(), name=f"inbound-node-{connection.endpoint}"
        )

    async def stop(self) -> None:
        for connection in list(self._connections.values()):
            await connection.stop()
        for task in list(self._tasks.values()):
            task.cancel()
        self._connections.clear()
        self._tasks.clear()

    def snapshot(self) -> list[dict]:
        rows = []
        for entry in self.saved():
            endpoint = _endpoint_of(entry)
            live = self._connections.get(endpoint)
            rows.append(
                {
                    "endpoint": endpoint,
                    "connected": bool(live and live.worker_id),
                    "worker_id": getattr(live, "worker_id", ""),
                    "last_error": getattr(live, "last_error", ""),
                }
            )
        return rows


def _endpoint_of(entry: str) -> str:
    try:
        return parse_connection(entry).endpoint
    except InvalidConnectionString:
        return ""


node = InboundNode()
outbound = OutboundNodes()
