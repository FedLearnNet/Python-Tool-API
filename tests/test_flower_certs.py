import datetime

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from pyfedappwrap.engine.service.flower import certs


def _load_cert(path):
    return x509.load_pem_x509_certificate(path.read_bytes())


def _stored_ca(validity_days=397):
    key, cert = certs._self_signed_ca()
    if validity_days != 397:
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(cert.subject).issuer_name(cert.issuer)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - datetime.timedelta(days=1))
                .not_valid_after(now + datetime.timedelta(days=validity_days))
                .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
                .sign(key, hashes.SHA256()))
    return certs._pem_pair(key, cert)


def _assert_signed_by(ca_cert, leaf_cert):
    assert leaf_cert.issuer == ca_cert.subject
    ca_cert.public_key().verify(
        leaf_cert.signature,
        leaf_cert.tbs_certificate_bytes,
        ec.ECDSA(leaf_cert.signature_hash_algorithm),
    )


def test_first_run_without_a_stored_ca_runs_insecure_and_reports_a_new_ca(tmp_path):
    tls = certs.prepare_superlink_tls(tmp_path, ["127.0.0.1"])

    assert tls.files is None
    cert_pem, key_pem = tls.ca_to_report
    key = serialization.load_pem_private_key(key_pem.encode(), password=None)
    assert key.public_key() == x509.load_pem_x509_certificate(cert_pem.encode()).public_key()


def test_a_stored_ca_signs_a_fresh_leaf_covering_the_given_hostnames(tmp_path):
    cert_pem, key_pem = _stored_ca()

    tls = certs.prepare_superlink_tls(tmp_path, ["127.0.0.1", "platform.example"],
                                      ca_cert_pem=cert_pem, ca_key_pem=key_pem)

    assert tls.ca_to_report is None
    assert tls.files.ca_cert_path.read_text() == cert_pem
    leaf_cert = _load_cert(tls.files.leaf_cert_path)
    # A clinic given the stored CA verifies this run's SuperLink leaf.
    ca_cert = x509.load_pem_x509_certificate(cert_pem.encode())
    _assert_signed_by(ca_cert, leaf_cert)
    assert leaf_cert.not_valid_after_utc <= ca_cert.not_valid_after_utc
    san = leaf_cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "platform.example" in [n.value for n in san if isinstance(n, x509.DNSName)]
    assert oct(tls.files.leaf_key_path.stat().st_mode & 0o777) == "0o600"


def test_a_ca_close_to_expiry_is_still_used_this_run_and_a_replacement_is_reported(tmp_path):
    cert_pem, key_pem = _stored_ca(validity_days=10)

    tls = certs.prepare_superlink_tls(tmp_path, ["127.0.0.1"],
                                      ca_cert_pem=cert_pem, ca_key_pem=key_pem)

    assert tls.files is not None
    _assert_signed_by(x509.load_pem_x509_certificate(cert_pem.encode()),
                      _load_cert(tls.files.leaf_cert_path))
    assert tls.ca_to_report is not None
    assert tls.ca_to_report[0] != cert_pem


def test_an_expired_stored_ca_is_replaced_and_the_run_goes_insecure(tmp_path):
    cert_pem, key_pem = _stored_ca(validity_days=-1)

    tls = certs.prepare_superlink_tls(tmp_path, ["127.0.0.1"],
                                      ca_cert_pem=cert_pem, ca_key_pem=key_pem)

    assert tls.files is None
    assert tls.ca_to_report is not None


def test_a_stored_ca_whose_key_does_not_match_is_replaced(tmp_path):
    cert_pem, _ = _stored_ca()
    _, other_key_pem = _stored_ca()

    tls = certs.prepare_superlink_tls(tmp_path, ["127.0.0.1"],
                                      ca_cert_pem=cert_pem, ca_key_pem=other_key_pem)

    assert tls.files is None
    assert tls.ca_to_report is not None


def test_write_ca_certificate_writes_the_given_content_verbatim(tmp_path):
    pem = "-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n"

    path = certs.write_ca_certificate(tmp_path, pem)

    assert path.name == "ca.crt"
    assert path.read_text() == pem


def test_generate_supernode_keypair_writes_openssh_keys_flower_can_load(tmp_path):
    result = certs.generate_supernode_keypair(tmp_path)

    assert result.public_key.startswith("ecdsa-sha2-nistp384 ")
    private_bytes = result.private_key_path.read_bytes()
    assert b"BEGIN OPENSSH PRIVATE KEY" in private_bytes
    assert oct(result.private_key_path.stat().st_mode & 0o777) == "0o600"
    # The same loaders flower-supernode and `flwr supernode register` use.
    private_key = serialization.load_ssh_private_key(private_bytes, password=None)
    public_key = serialization.load_ssh_public_key(result.public_key.encode())
    assert private_key.public_key() == public_key
