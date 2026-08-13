"""TLS for a control plane that lives on someone's desktop.

The awkward fact the goal doc skipped: the OSS control server is a laptop. It
has no domain name, no publicly-valid certificate, and its IP changes. "All
remote communication must use TLS" is easy to write and, stated that way,
unimplementable — which in practice means somebody adds an
``insecure_skip_verify`` flag and the whole thing becomes theatre, because on a
café network that flag *is* the attack.

So the trust anchor is the enrollment token, not the public CA system. The
control plane generates a self-signed certificate once and keeps it; the token
the user copies carries that certificate's fingerprint; the worker pins it on
first connect and refuses anything else afterwards. This is the join-token
pattern from k3s and Tailscale, and it gives a desktop the same practical
security a real CA would, without asking the user to run one.

There is deliberately no way to disable verification.
"""

from __future__ import annotations

import datetime as _dt
import ipaddress
import logging
import os
import socket
import ssl
from dataclasses import dataclass
from typing import Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from worker.identity import certificate_fingerprint

logger = logging.getLogger("omnivoice.worker")

_CERT_VALID_DAYS = 825  # the CA/Browser Forum maximum; long enough to be quiet
_RENEW_WITHIN_DAYS = 30


def unverified_client_context() -> ssl.SSLContext:
    """Build the pin-bootstrap context without permitting legacy TLS."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    return context


@dataclass(frozen=True)
class ServerCredentials:
    """A control plane's certificate and its pinnable fingerprint."""

    certificate_pem: bytes
    private_key_pem: bytes
    certificate_der: bytes

    @property
    def fingerprint(self) -> str:
        return certificate_fingerprint(self.certificate_der)


def _san_entries(hostnames: list[str]) -> list[x509.GeneralName]:
    """Cover every address a worker might legitimately dial.

    A tailnet name, a LAN hostname, and a bare IP are all normal ways to reach
    a desktop, and a certificate that only names one of them fails as soon as
    the user's network changes shape.
    """
    entries: list[x509.GeneralName] = []
    for host in hostnames:
        host = (host or "").strip()
        if not host:
            continue
        try:
            entries.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            entries.append(x509.DNSName(host))
    if not entries:
        entries.append(x509.DNSName("localhost"))
    return entries


def primary_ip() -> str:
    """This host's address on the route to the outside world.

    Opening a UDP socket sends no packets — it only makes the kernel choose a
    source address, which is exactly the one a worker on the LAN would reach us
    on. Enumerating interfaces instead would leave us guessing between docker0,
    a VPN, and the real NIC.
    """
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        # TEST-NET-1 (RFC 5737): reserved, never routed, never contacted.
        probe.connect(("192.0.2.1", 9))
        return probe.getsockname()[0]
    except OSError:
        return ""
    finally:
        probe.close()


def covers(credentials: "ServerCredentials", host: str) -> bool:
    """Does this certificate actually name ``host``?

    Used to regenerate when the machine's address changes — a laptop that moved
    networks otherwise keeps a certificate no worker can validate.
    """
    if not host:
        return True
    try:
        certificate = x509.load_der_x509_certificate(credentials.certificate_der)
        san = certificate.extensions.get_extension_for_class(
            x509.SubjectAlternativeName
        ).value
    except Exception:
        return False
    names = set(san.get_values_for_type(x509.DNSName))
    names |= {str(ip) for ip in san.get_values_for_type(x509.IPAddress)}
    return host in names


def default_hostnames() -> list[str]:
    """Best-effort local identities, deduplicated and order-stable.

    The routable IP matters as much as the names: gRPC resolves through c-ares,
    which does NOT speak mDNS, so a macOS ``host.local`` that Python resolves
    happily is unreachable to a worker. Whatever we advertise must appear here
    or TLS verification fails on the name.
    """
    names = ["localhost", "127.0.0.1", "::1"]
    address = primary_ip()
    if address:
        names.append(address)
    try:
        hostname = socket.gethostname()
        if hostname:
            names.append(hostname)
            # A tailnet or mDNS name is the realistic way a worker reaches a
            # laptop that has no fixed address. macOS already reports the
            # hostname WITH the .local suffix, so only add it when absent —
            # otherwise the SAN carries a bogus "host.local.local".
            if "." not in hostname:
                names.append(f"{hostname}.local")
    except OSError:
        pass
    seen: set[str] = set()
    return [n for n in names if not (n in seen or seen.add(n))]


def generate_self_signed(
    *, hostnames: Optional[list[str]] = None, now: Optional[_dt.datetime] = None
) -> ServerCredentials:
    """Mint the control plane's certificate.

    EC P-256 rather than RSA: far faster to generate, which matters because
    this runs on first launch while the user is waiting.
    """
    stamp = now or _dt.datetime.now(_dt.timezone.utc)
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name(
        [
            x509.NameAttribute(NameOID.COMMON_NAME, "OmniVoice Control Plane"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "OmniVoice Studio"),
        ]
    )
    certificate = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(stamp - _dt.timedelta(minutes=5))  # tolerate clock skew
        .not_valid_after(stamp + _dt.timedelta(days=_CERT_VALID_DAYS))
        .add_extension(
            x509.SubjectAlternativeName(_san_entries(hostnames or default_hostnames())),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    return ServerCredentials(
        certificate_pem=certificate.public_bytes(serialization.Encoding.PEM),
        private_key_pem=key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
        certificate_der=certificate.public_bytes(serialization.Encoding.DER),
    )


def load_or_create(
    cert_path: str, key_path: str, *, hostnames: Optional[list[str]] = None
) -> ServerCredentials:
    """Return the stored certificate, regenerating it if absent or expiring.

    Renewing early matters more here than usual: an expired certificate on a
    desktop control plane presents as "my workers all went offline" with
    nothing in the UI explaining why.
    """
    existing = _load(cert_path, key_path)
    wanted = hostnames or default_hostnames()
    # Every explicitly requested identity must be present. This matters for an
    # inbound listener bound to a user-entered LAN address: keeping a stable
    # certificate that does not name that address makes mandatory hostname
    # verification fail even though its fingerprint is correct.
    missing = [
        host for host in wanted if existing is not None and not covers(existing, host)
    ]
    if existing is not None and not _expiring_soon(existing) and not missing:
        return existing
    if existing is not None:
        reason = (
            "expiring" if _expiring_soon(existing) else "missing a requested hostname"
        )
        logger.info("Control-plane certificate is %s — regenerating.", reason)
    credentials = generate_self_signed(hostnames=wanted)
    _save(cert_path, key_path, credentials)
    return credentials


def _load(cert_path: str, key_path: str) -> Optional[ServerCredentials]:
    try:
        with open(cert_path, "rb") as fh:
            cert_pem = fh.read()
        with open(key_path, "rb") as fh:
            key_pem = fh.read()
    except (FileNotFoundError, PermissionError):
        return None
    try:
        certificate = x509.load_pem_x509_certificate(cert_pem)
    except ValueError:
        return None
    return ServerCredentials(
        certificate_pem=cert_pem,
        private_key_pem=key_pem,
        certificate_der=certificate.public_bytes(serialization.Encoding.DER),
    )


def _expiring_soon(
    credentials: ServerCredentials, *, now: Optional[_dt.datetime] = None
) -> bool:
    certificate = x509.load_der_x509_certificate(credentials.certificate_der)
    stamp = now or _dt.datetime.now(_dt.timezone.utc)
    expires = getattr(certificate, "not_valid_after_utc", None)
    if expires is None:  # cryptography 41 and older
        expires = certificate.not_valid_after.replace(tzinfo=_dt.timezone.utc)
    return (expires - stamp) < _dt.timedelta(days=_RENEW_WITHIN_DAYS)


def _save(cert_path: str, key_path: str, credentials: ServerCredentials) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(cert_path)), exist_ok=True)
    with open(cert_path, "wb") as fh:
        fh.write(credentials.certificate_pem)
    # The private key gets the same 0600 treatment as worker keys.
    fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, credentials.private_key_pem)
    finally:
        os.close(fd)
    try:
        os.chmod(key_path, 0o600)
    except OSError:
        pass


def pin_matches(certificate_der: bytes, expected_fingerprint: str) -> bool:
    """Constant-time-ish comparison of a presented certificate against a pin."""
    import hmac  # noqa: PLC0415 — trivial, keeps the module import light

    return hmac.compare_digest(
        certificate_fingerprint(certificate_der).lower(),
        (expected_fingerprint or "").lower(),
    )


__all__ = [
    "ServerCredentials",
    "covers",
    "default_hostnames",
    "primary_ip",
    "generate_self_signed",
    "load_or_create",
    "pin_matches",
]
