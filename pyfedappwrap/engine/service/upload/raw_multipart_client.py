import http.client
import json
import logging
import mimetypes
import ssl
import uuid
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Tuple
from urllib.parse import urlencode

CRLF = b"\r\n"
_SENSITIVE_HEADERS = {"authorization", "cookie", "x-api-key"}


def _guess_content_type(path: Path) -> str:
    ctype, _ = mimetypes.guess_type(str(path))
    return ctype or "application/octet-stream"


def _iter_multipart(
        boundary: str,
        fields_json: Mapping[str, Any],
        files: Sequence[Tuple[str, Path]],
        run_id: int,
        meta_json: Optional[Mapping[str, Any]] = None,
) -> Sequence[bytes]:
    bnd = boundary.encode("utf-8")
    chunks: list[bytes] = []

    # --- runId (text/plain) ---
    chunks.append(b"--" + bnd + CRLF)
    chunks.append(b'Content-Disposition: form-data; name="runId"' + CRLF)
    chunks.append(b"Content-Type: text/plain; charset=utf-8" + CRLF)
    chunks.append(CRLF)
    chunks.append(str(run_id).encode("utf-8") + CRLF)

    # --- fields (application/json) ---
    if fields_json and len(fields_json) > 0:
        fields_payload = json.dumps(fields_json, ensure_ascii=False).encode("utf-8")
        chunks.append(b"--" + bnd + CRLF)
        chunks.append(
            b'Content-Disposition: form-data; name="fields"' + CRLF)
        chunks.append(b"Content-Type: application/json; charset=utf-8" + CRLF)
        chunks.append(CRLF)
        chunks.append(fields_payload + CRLF)

    # --- meta (application/json) --- run metadata (timings) persisted with the terminal upload
    if meta_json:
        meta_payload = json.dumps(meta_json, ensure_ascii=False).encode("utf-8")
        chunks.append(b"--" + bnd + CRLF)
        chunks.append(b'Content-Disposition: form-data; name="meta"' + CRLF)
        chunks.append(b"Content-Type: application/json; charset=utf-8" + CRLF)
        chunks.append(CRLF)
        chunks.append(meta_payload + CRLF)

    # --- files ---
    for key, path in files:
        content_type = _guess_content_type(path)
        chunks.append(b"--" + bnd + CRLF)
        chunks.append(
            f'Content-Disposition: form-data; name="files"; filename="{path.name}"'.encode("utf-8")
            + CRLF
        )
        chunks.append(f"Content-Type: {content_type}".encode("utf-8") + CRLF)
        chunks.append(b"Content-Transfer-Encoding: binary" + CRLF)
        chunks.append(f"X-Key: {key}".encode("utf-8") + CRLF)
        chunks.append(f"X-Name: {path.name}".encode("utf-8") + CRLF)
        chunks.append(CRLF)

        with path.open("rb") as f:
            chunks.append(f.read())

        chunks.append(CRLF)

    # --- closing boundary ---
    chunks.append(b"--" + bnd + b"--" + CRLF)
    return chunks


def _compute_length(chunks: Sequence[bytes]) -> int:
    return sum(len(c) for c in chunks)


def post_output_raw_httpclient(
        *,
        host: str,
        port: int,
        use_https: bool,
        path: str,
        run_id: int,
        run_type: str,  # query param, e.g. "MODEL_RUN"
        fields: Mapping[str, Any],  # your output_data.output_data non-file values
        file_paths: Sequence[Tuple[str, Path]],
        headers: Optional[Mapping[str, str]] = None,
        timeout: int = 120,
        meta: Optional[Mapping[str, Any]] = None,  # run metadata (timings)
) -> Tuple[int, str, bytes]:
    boundary = uuid.uuid4().hex
    qs = urlencode({"runType": run_type})
    full_path = f"{path}?{qs}"

    chunks = _iter_multipart(boundary, fields, file_paths, run_id, meta)
    content_length = _compute_length(chunks)

    req_headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        "Content-Length": str(content_length),
        "Accept": "application/json, text/plain, */*",
    }
    if headers:
        for k, v in headers.items():
            if k.lower() != "content-type":
                req_headers[k] = v

    if use_https:
        conn = http.client.HTTPSConnection(host, port, timeout=timeout,
                                           context=ssl.create_default_context())
    else:
        conn = http.client.HTTPConnection(host, port, timeout=timeout)

    try:
        conn.putrequest("POST", full_path)
        for k, v in req_headers.items():
            conn.putheader(k, v)
        conn.endheaders()

        for c in chunks:
            conn.send(c)

        resp = conn.getresponse()
        data = resp.read()
        if resp.status >= 400:
            scheme = "https" if use_https else "http"
            url = f"{scheme}://{host}:{port}{full_path}"

            logging.error(
                "HTTP %s %s\nURL: %s\nHeaders: %s\nrunId=%s\nfields=%s\nResponse: %s",
                resp.status,
                resp.reason,
                url,
                _redact_headers(dict(req_headers)),
                run_id,
                json.dumps(fields, ensure_ascii=False),
                (data[:2000].decode("utf-8", errors="replace") if data else ""),
            )
        return resp.status, resp.reason, data
    finally:
        conn.close()


def _redact_headers(headers: dict[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for k, v in headers.items():
        lk = k.lower()
        if lk in _SENSITIVE_HEADERS:
            out[k] = "<redacted>"
        elif lk in {"content-length"}:
            continue
        else:
            out[k] = v
    return out
