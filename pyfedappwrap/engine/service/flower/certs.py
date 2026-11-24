"""Generates the TLS material Flower needs, entirely locally - no network calls, no Learning
APIs round-trip. This lives here (not in Learning APIs) per Julian's review of #13's platform
setup task: all Flower-specific cert/CLI logic belongs inside the app template (this package),
not the platform's Java side - see Flower_Integration_Plan.md's Task 3 discoveries.

Two independent credentials, confirmed via `flower-federated-learning` to be unrelated
mechanisms:
- A self-signed CA plus a SuperLink leaf cert/key signed by it. Flower's SuperNode<->SuperLink
  connection is one-way, server-authenticated TLS (confirmed: "This is not mTLS" in Flower's own
  docs) - the leaf cert only needs to authenticate the SuperLink to connecting SuperNodes, there
  is no client certificate at the TLS layer at all.
- A SuperNode's own EC auth keypair (`--auth-supernode-private-key`), a separate,
  application-layer signature-challenge mechanism with no CA involved.

The CA must stay the same across runs: clinics are handed the CA Learning APIs has stored before
the platform's aggregator for that run even starts, and the aggregator's container (and its
`/tmp/fedrun/<run_id>` directory) is gone after every run. So the CA's single home is Learning
APIs' database (FlowerPlatformCertificateEntity): the aggregator receives the stored CA cert and
key back on every start, signs a fresh leaf cert with it, and only generates (and reports up) a
new CA when none was given or the given one is about to expire.
"""
from __future__ import annotations

import datetime
import ipaddress
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

_CERT_VALIDITY = datetime.timedelta(days=397)  # under the ~398-day CA/Browser Forum cap
_CURVE = ec.SECP384R1()
# A stored CA closer than this to expiry is replaced instead of reused, so a run never starts
# with a CA that expires mid-run.
_CA_RENEWAL_MARGIN = datetime.timedelta(days=30)


@dataclass(frozen=True)
class CaAndLeafCert:
    ca_cert_pem: str
    ca_key_pem: str
    # True when this call generated a new CA (none given, or the given one was about to expire);
    # the caller must then report it up so Learning APIs stores it for later runs.
    ca_is_new: bool
    ca_cert_path: Path
    leaf_cert_path: Path
    leaf_key_path: Path


@dataclass(frozen=True)
class SupernodeKeyPair:
    public_key_pem: str
    private_key_path: Path


def _self_signed_ca() -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(_CURVE)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "flower-platform-ca")])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + _CERT_VALIDITY)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    return key, cert


def _leaf_cert(ca_key: ec.EllipticCurvePrivateKey, ca_cert: x509.Certificate,
               hostnames: list[str]) -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = ec.generate_private_key(_CURVE)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostnames[0])])
    now = datetime.datetime.now(datetime.timezone.utc)
    san_entries: list[x509.GeneralName] = []
    for host in hostnames:
        try:
            san_entries.append(x509.IPAddress(ipaddress.ip_address(host)))
        except ValueError:
            san_entries.append(x509.DNSName(host))
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(min(now + _CERT_VALIDITY, ca_cert.not_valid_after_utc))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.SubjectAlternativeName(san_entries), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    return key, cert


def _load_ca(ca_cert_pem: str, ca_key_pem: str) -> Optional[
        tuple[ec.EllipticCurvePrivateKey, x509.Certificate]]:
    """The given CA, or None when it can't be used (unparseable, mismatched key, or within
    `_CA_RENEWAL_MARGIN` of expiry) and a new one must be generated instead."""
    try:
        cert = x509.load_pem_x509_certificate(ca_cert_pem.encode("ascii"))
        key = serialization.load_pem_private_key(ca_key_pem.encode("ascii"), password=None)
    except ValueError:
        logging.warning("Stored Flower CA could not be parsed; generating a new one")
        return None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.public_key() != cert.public_key():
        logging.warning("Stored Flower CA key does not match its certificate; generating a new one")
        return None
    remaining = cert.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc)
    if remaining < _CA_RENEWAL_MARGIN:
        logging.info("Stored Flower CA expires on %s; generating a new one",
                     cert.not_valid_after_utc)
        return None
    return key, cert


def ensure_ca_and_leaf_cert(directory: Path, leaf_hostnames: list[str], *,
                            ca_cert_pem: Optional[str] = None,
                            ca_key_pem: Optional[str] = None) -> CaAndLeafCert:
    """Writes `ca.crt`/`server.pem`/`server.key` under `directory`. Reuses the given CA when it
    is usable (see `_load_ca`), otherwise generates a new one; the leaf cert is always new, so
    its SANs always match the current `leaf_hostnames`."""
    directory.mkdir(parents=True, exist_ok=True)
    ca_path = directory / "ca.crt"
    leaf_cert_path = directory / "server.pem"
    leaf_key_path = directory / "server.key"

    loaded = _load_ca(ca_cert_pem, ca_key_pem) if ca_cert_pem and ca_key_pem else None
    ca_is_new = loaded is None
    ca_key, ca_cert = _self_signed_ca() if loaded is None else loaded
    leaf_key, leaf_cert = _leaf_cert(ca_key, ca_cert, leaf_hostnames)

    out_ca_cert_pem = ca_cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
    out_ca_key_pem = ca_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode("ascii")
    ca_path.write_text(out_ca_cert_pem, encoding="utf-8")
    leaf_cert_path.write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
    leaf_key_path.write_bytes(leaf_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    leaf_key_path.chmod(0o600)
    return CaAndLeafCert(
        ca_cert_pem=out_ca_cert_pem,
        ca_key_pem=out_ca_key_pem,
        ca_is_new=ca_is_new,
        ca_cert_path=ca_path,
        leaf_cert_path=leaf_cert_path,
        leaf_key_path=leaf_key_path,
    )


def write_ca_certificate(directory: Path, ca_cert_pem: str) -> Path:
    """Writes CA cert content received from Learning APIs to a local file for a clinic's
    SuperNode (`--root-certificates`) to use. The clinic never generates its own CA - only the
    platform's aggregator does (see `ensure_ca_and_leaf_cert`)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ca.crt"
    path.write_text(ca_cert_pem, encoding="utf-8")
    return path


def generate_supernode_keypair(directory: Path) -> SupernodeKeyPair:
    """A SuperNode's own EC auth keypair, independent of the CA/leaf-cert TLS material above -
    confirmed via `flower-federated-learning` to be a separate, application-layer mechanism. The
    private key is written to `directory` and never returned as content - only the public key
    (which must reach the platform's aggregator for registration) is."""
    directory.mkdir(parents=True, exist_ok=True)
    private_key_path = directory / "supernode_private_key"
    key = ec.generate_private_key(_CURVE)
    private_key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ))
    public_key_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    return SupernodeKeyPair(public_key_pem=public_key_pem, private_key_path=private_key_path)
