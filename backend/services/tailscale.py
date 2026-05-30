"""Thin wrapper around the `tailscale` CLI. Every call degrades gracefully
when the CLI is missing or not logged in (installed/running flags)."""
import json
import shutil
import subprocess
from services.network_share import BACKEND_PORT


def _cli():
    return shutil.which("tailscale")


def status() -> dict:
    out = {"installed": False, "running": False, "magic_dns_name": "", "tailnet_ips": []}
    cli = _cli()
    if not cli:
        return out
    out["installed"] = True
    try:
        r = subprocess.run([cli, "status", "--json"], capture_output=True, text=True, timeout=10)
        if r.returncode != 0:
            return out
        data = json.loads(r.stdout or "{}")
        out["running"] = data.get("BackendState") == "Running"
        self_ = data.get("Self") or {}
        out["magic_dns_name"] = (self_.get("DNSName") or "").rstrip(".")
        out["tailnet_ips"] = self_.get("TailscaleIPs") or []
    except Exception:
        pass
    return out


def serve_enable(port: int = BACKEND_PORT) -> dict:
    cli = _cli()
    if not cli:
        return {"ok": False, "error": "tailscale CLI not found"}
    try:
        r = subprocess.run(
            [cli, "serve", "--bg", "--https=443", f"http://127.0.0.1:{port}"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode != 0:
            return {"ok": False, "error": (r.stderr or r.stdout or "tailscale serve failed").strip()}
        dns = status().get("magic_dns_name", "")
        return {"ok": True, "url": f"https://{dns}" if dns else ""}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def serve_disable() -> dict:
    cli = _cli()
    if not cli:
        return {"ok": True}
    try:
        subprocess.run([cli, "serve", "reset"], capture_output=True, text=True, timeout=20)
    except Exception:
        pass
    return {"ok": True}
