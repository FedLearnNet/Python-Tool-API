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
# A stored CA closer than this to expiry is still used for the current run (its clinics were
# already given it) but a replacement is generated and reported, so later runs switch over well
# before it actually expires.
_CA_RENEWAL_MARGIN = datetime.timedelta(days=30)


@dataclass(frozen=True)
class SuperlinkTlsFiles:
    ca_cert_path: Path
    leaf_cert_path: Path
    leaf_key_path: Path


@dataclass(frozen=True)
class SuperlinkTls:
    # The files to start the SuperLink with TLS, or None when it must run `--insecure` this run:
    # the SuperLink may only present a leaf signed by the CA this run's clinics were given, and
    # with no usable stored CA there is none (see `prepare_superlink_tls`).
    files: Optional[SuperlinkTlsFiles]
    # A newly generated CA (cert PEM, key PEM) the caller must report so Learning APIs stores it
    # for later runs; None when the stored CA is reused as-is.
    ca_to_report: Optional[tuple[str, str]]


@dataclass(frozen=True)
class SupernodeKeyPair:
    public_key: str  # OpenSSH format, e.g. "ecdsa-sha2-nistp384 AAAA..."
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
    """The given CA, or None when it can't be used at all (unparseable, mismatched key, or
    already expired)."""
    try:
        cert = x509.load_pem_x509_certificate(ca_cert_pem.encode("ascii"))
        key = serialization.load_pem_private_key(ca_key_pem.encode("ascii"), password=None)
    except ValueError:
        logging.error("Stored Flower CA could not be parsed")
        return None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or key.public_key() != cert.public_key():
        logging.error("Stored Flower CA key does not match its certificate")
        return None
    if cert.not_valid_after_utc <= datetime.datetime.now(datetime.timezone.utc):
        logging.error("Stored Flower CA expired on %s", cert.not_valid_after_utc)
        return None
    return key, cert


def _pem_pair(key: ec.EllipticCurvePrivateKey, cert: x509.Certificate) -> tuple[str, str]:
    return (
        cert.public_bytes(serialization.Encoding.PEM).decode("ascii"),
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ).decode("ascii"),
    )


def prepare_superlink_tls(directory: Path, leaf_hostnames: list[str], *,
                          ca_cert_pem: Optional[str] = None,
                          ca_key_pem: Optional[str] = None) -> SuperlinkTls:
    """Decides how the platform's SuperLink runs this run, given the stored CA Learning APIs
    sent (the same one this run's clinics got as `--root-certificates`):

    - usable stored CA: write `ca.crt` and a fresh `server.pem`/`server.key` signed by it under
      `directory` (fresh leaf, so its SANs always match `leaf_hostnames`) -> TLS. If it expires
      within `_CA_RENEWAL_MARGIN`, also generate a replacement to report for later runs.
    - no stored CA (the platform's very first Flower run) or an unusable one: generate a new CA
      to report, and run `--insecure` this once - TLS with a CA the clinics weren't given could
      never connect. Every later run then gets TLS (see Flower_Integration_Plan.md, Task 4).
    """
    loaded = _load_ca(ca_cert_pem, ca_key_pem) if ca_cert_pem and ca_key_pem else None
    if loaded is None:
        new_key, new_cert = _self_signed_ca()
        return SuperlinkTls(files=None, ca_to_report=_pem_pair(new_key, new_cert))

    ca_key, ca_cert = loaded
    ca_to_report = None
    remaining = ca_cert.not_valid_after_utc - datetime.datetime.now(datetime.timezone.utc)
    if remaining < _CA_RENEWAL_MARGIN:
        logging.info("Stored Flower CA expires on %s; reporting a replacement for later runs",
                     ca_cert.not_valid_after_utc)
        ca_to_report = _pem_pair(*_self_signed_ca())

    directory.mkdir(parents=True, exist_ok=True)
    ca_path = directory / "ca.crt"
    leaf_cert_path = directory / "server.pem"
    leaf_key_path = directory / "server.key"
    leaf_key, leaf_cert = _leaf_cert(ca_key, ca_cert, leaf_hostnames)
    ca_path.write_text(_pem_pair(ca_key, ca_cert)[0], encoding="utf-8")
    leaf_cert_path.write_bytes(leaf_cert.public_bytes(serialization.Encoding.PEM))
    leaf_key_path.write_bytes(leaf_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    ))
    leaf_key_path.chmod(0o600)
    return SuperlinkTls(
        files=SuperlinkTlsFiles(ca_cert_path=ca_path, leaf_cert_path=leaf_cert_path,
                                leaf_key_path=leaf_key_path),
        ca_to_report=ca_to_report,
    )


def write_ca_certificate(directory: Path, ca_cert_pem: str) -> Path:
    """Writes CA cert content received from Learning APIs to a local file for a clinic's
    SuperNode (`--root-certificates`) to use. The clinic never generates its own CA - only the
    platform's aggregator does (see `prepare_superlink_tls`)."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "ca.crt"
    path.write_text(ca_cert_pem, encoding="utf-8")
    return path


def generate_supernode_keypair(directory: Path) -> SupernodeKeyPair:
    """A SuperNode's own EC auth keypair, independent of the CA/leaf-cert TLS material above.
    Both halves are in OpenSSH format - confirmed against Flower 1.43's own code:
    `flower-supernode --auth-supernode-private-key` loads it with `load_ssh_private_key`, and
    `flwr supernode register` with `load_ssh_public_key` (a PEM key fails with "Unsupported key
    type"), on a NIST curve. The private key is written to `directory` (mode 0600) and never
    returned as content - only the public key, which the platform's aggregator registers, is."""
    directory.mkdir(parents=True, exist_ok=True)
    private_key_path = directory / "supernode_private_key"
    key = ec.generate_private_key(_CURVE)
    private_key_path.write_bytes(key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ))
    private_key_path.chmod(0o600)
    public_key_ssh = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH,
        serialization.PublicFormat.OpenSSH,
    ).decode("ascii")
    return SupernodeKeyPair(public_key=public_key_ssh, private_key_path=private_key_path)
