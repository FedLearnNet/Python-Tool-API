import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import requests

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.service.upload.raw_multipart_client import post_output_raw_httpclient


class AbstractUploadClient(ABC):
    """Abstract base class for upload clients."""

    @abstractmethod
    def __init__(self, token: Optional[str], api_key: Optional[str] = None):
        self.token = token

    @abstractmethod
    def upload_model_file(self, run_id: int, name: str, file_path: str) -> requests.Response:
        """
        Upload a model to the API.

        :param file_path: file_path of the model to upload.
        :param run_id: The run ID associated with the model.
        :param name: The name of the model.
        :return: The response object.
        """
        pass

    @abstractmethod
    def upload_output(self, run_type, run_id: int,
                      output: dict[str, Any],
                      meta: Optional[dict[str, Any]] = None) -> requests.Response:
        """
        Create output and finish a run.

        :param output:
        :param run_id:
        :param meta: Optional run metadata (timings) persisted with the (terminal) output upload.
        :param run_type: The run type as a string.
        :return: The response object.
        """
        pass


class UploadClient(AbstractUploadClient):
    def __init__(self, token: Optional[str], api_key: Optional[str] = None):
        """
        Initialize the UploadClient.

        :param token: Optional OAuth token for user-authenticated calls.
        """
        self.base_url = system_settings.http_url
        self.app_id = system_settings.app_id
        self.token = token
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        self.form_headers = {
            "Authorization": f"Bearer {token}",
            # "Content-Type": "multipart/form-data",
        }
        if token is None or token == "":
            self.headers = {
                "Content-Type": "application/json",
            }
            self.form_headers = {}
        if api_key:
            self.headers["X-API-Key"] = api_key
            self.form_headers["X-API-Key"] = api_key

        self.logger = logging.getLogger(__name__)
        logging.basicConfig(level=logging.INFO)

    def upload_model_file(self, run_id: int, name: str, file_path: str) -> requests.Response:
        """
        Upload model via MULTIPART_FORM_DATA to match:
        ModelSubDataDTO { runId, name, filePath, file }
        """
        url = f"{self.base_url}{self.app_id}/{system_settings.http_upload_path}/model"
        self.logger.info(f"Uploading model to {url}")
        p = Path(file_path)
        if not p.exists():
            raise FileNotFoundError(f"Model file does not exist: {file_path}")

        data = {
            "runId": str(run_id),
            "name": name,
            "filePath": str(p),
        }

        with p.open("rb") as f:
            files = {
                "file": (p.name, f, "application/octet-stream")
            }
            try:
                response = requests.post(
                    url,
                    data=data,
                    files=files,
                    headers=self.form_headers,
                    timeout=(5, 120),  # connect, read
                )
                response.raise_for_status()
                self.logger.info(f"Successfully uploaded model to {url}")
            except requests.exceptions.RequestException as e:
                self.logger.error(f"Failed to upload model to {url}: {e}")
                raise

        return response

    def upload_output(self, run_type, run_id: int,
                      output: dict[str, Any],
                      meta: Optional[dict[str, Any]] = None) -> requests.Response:

        fields: dict[str, Any] = {}
        file_paths: list[tuple[str, Path]] = []

        for key, value in output.items():
            if isinstance(value, Path) and value.exists():
                if value.exists():
                    file_paths.append((key, value))
                else:
                    self.logger.error(f"File for output key '{key}' does not exist: {value}")
                    fields[key] = str(value)
            elif value is not None:
                fields[key] = str(value)

        url = f"{self.base_url}{self.app_id}/{system_settings.http_upload_path}/output"
        parsed = urlparse(self.base_url if "://" in self.base_url else f"http://{self.base_url}")
        use_https = parsed.scheme == "https"
        host = parsed.hostname or "localhost"
        port = parsed.port or (443 if use_https else 80)

        headers = dict(getattr(self, "form_headers", {}) or {})
        headers.pop("Content-Type", None)
        headers.pop("content-type", None)

        status, reason, body = post_output_raw_httpclient(
            host=host,
            port=port,
            use_https=use_https,
            path=url,
            run_id=run_id,
            run_type=str(run_type.value),
            fields=fields,
            file_paths=file_paths,
            headers=headers,
            timeout=120,
            meta=meta,
        )

        resp = requests.Response()
        resp.status_code = status
        resp._content = body
        resp.reason = reason
        resp.url = url

        resp.headers["Content-Type"] = "application/octet-stream"

        if status >= 400:
            resp.raise_for_status()

        self.logger.info("Successfully uploaded output to %s", resp.url)
        return resp
