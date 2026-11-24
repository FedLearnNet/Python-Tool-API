import datetime

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from pyfedappwrap.engine.service.flower import certs


def _load_cert(path):
    return x509.load_pem_x509_certificate(path.read_bytes())


def test_ensure_ca_and_leaf_cert_generates_a_leaf_signed_by_the_generated_ca(tmp_path):
    result = certs.ensure_ca_and_leaf_cert(tmp_path, ["127.0.0.1", "platform.example"])

    ca_cert = _load_cert(result.ca_cert_path)
    leaf_cert = _load_cert(result.leaf_cert_path)
    assert leaf_cert.issuer == ca_cert.subject
    # The one-way TLS model (not mTLS): the CA's own public key must verify the leaf's signature.
    ca_cert.public_key().verify(
        leaf_cert.signature,
        leaf_cert.tbs_certificate_bytes,
        ec.ECDSA(leaf_cert.signature_hash_algorithm),
    )
    san = leaf_cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "platform.example" in [n.value for n in san if isinstance(n, x509.DNSName)]
    assert result.ca_cert_pem == result.ca_cert_path.read_text()


def test_without_a_stored_ca_a_new_one_is_generated_and_flagged_for_reporting(tmp_path):
    result = certs.ensure_ca_and_leaf_cert(tmp_path, ["127.0.0.1"])

    assert result.ca_is_new
    key = serialization.load_pem_private_key(result.ca_key_pem.encode(), password=None)
    assert key.public_key() == _load_cert(result.ca_cert_path).public_key()


def test_a_stored_ca_is_reused_across_runs_and_signs_each_runs_new_leaf(tmp_path):
    first = certs.ensure_ca_and_leaf_cert(tmp_path / "run1", ["127.0.0.1"])

    second = certs.ensure_ca_and_leaf_cert(
        tmp_path / "run2", ["127.0.0.1", "platform.example"],
        ca_cert_pem=first.ca_cert_pem, ca_key_pem=first.ca_key_pem)

    assert not second.ca_is_new
    assert second.ca_cert_pem == first.ca_cert_pem
    # A clinic given run 1's CA verifies run 2's SuperLink leaf.
    ca_cert = x509.load_pem_x509_certificate(first.ca_cert_pem.encode())
    leaf_cert = _load_cert(second.leaf_cert_path)
    ca_cert.public_key().verify(
        leaf_cert.signature,
        leaf_cert.tbs_certificate_bytes,
        ec.ECDSA(leaf_cert.signature_hash_algorithm),
    )
    assert leaf_cert.not_valid_after_utc <= ca_cert.not_valid_after_utc


def test_a_stored_ca_close_to_expiry_is_replaced(tmp_path, monkeypatch):
    monkeypatch.setattr(certs, "_CERT_VALIDITY", datetime.timedelta(days=10))
    expiring = certs.ensure_ca_and_leaf_cert(tmp_path / "run1", ["127.0.0.1"])
    monkeypatch.setattr(certs, "_CERT_VALIDITY", datetime.timedelta(days=397))

    renewed = certs.ensure_ca_and_leaf_cert(
        tmp_path / "run2", ["127.0.0.1"],
        ca_cert_pem=expiring.ca_cert_pem, ca_key_pem=expiring.ca_key_pem)

    assert renewed.ca_is_new
    assert renewed.ca_cert_pem != expiring.ca_cert_pem


def test_a_stored_ca_whose_key_does_not_match_is_replaced(tmp_path):
    a = certs.ensure_ca_and_leaf_cert(tmp_path / "a", ["127.0.0.1"])
    b = certs.ensure_ca_and_leaf_cert(tmp_path / "b", ["127.0.0.1"])

    result = certs.ensure_ca_and_leaf_cert(
        tmp_path / "c", ["127.0.0.1"], ca_cert_pem=a.ca_cert_pem, ca_key_pem=b.ca_key_pem)

    assert result.ca_is_new


def test_write_ca_certificate_writes_the_given_content_verbatim(tmp_path):
    pem = "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"

    path = certs.write_ca_certificate(tmp_path, pem)

    assert path.name == "ca.crt"
    assert path.read_text() == pem


def test_generate_supernode_keypair_returns_a_public_key_and_writes_a_private_key_file(tmp_path):
    result = certs.generate_supernode_keypair(tmp_path)

    assert "BEGIN PUBLIC KEY" in result.public_key_pem
    assert result.private_key_path.exists()
    private_key_pem = result.private_key_path.read_bytes()
    assert b"BEGIN PRIVATE KEY" in private_key_pem
    # The private key never shows up in the returned public content.
    assert result.public_key_pem.encode() not in private_key_pem

    loaded = serialization.load_pem_private_key(private_key_pem, password=None)
    assert loaded.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode() == result.public_key_pem
