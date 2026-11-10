import json
import mimetypes
from abc import ABC, abstractmethod
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Optional

import requests

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.service.execution_auth import (
    authentication_headers, execution_base_url,
)


class AbstractUploadClient(ABC):
    """Abstract base class for upload clients."""

    @abstractmethod
    def __init__(self, token: Optional[str], api_key: Optional[str] = None):
        self.token = token

    def for_execution(self, start):
        return self

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
    def __init__(self, token: Optional[str], api_key: Optional[str] = None, *,
                 base_url=None, app_id=None, run_id=None):
        """
        Initialize the UploadClient.

        :param token: Optional OAuth token for user-authenticated calls.
        """
        self.base_url = base_url or system_settings.http_url
        self.app_id = system_settings.app_id if app_id is None else app_id
        self.run_id = self.app_id if run_id is None else run_id
        self.token = token
        self.api_key = api_key
        self.form_headers = authentication_headers(token, api_key)

    def for_execution(self, start):
        api_key = start.pop("executionApiKey", None)
        execution_id = start.pop("executionId", None)
        if api_key is None:
            return self
        if execution_id is None:
            raise ValueError("Execution identity is required")
        return UploadClient(self.token, api_key, base_url=execution_base_url(self.base_url),
                            app_id=execution_id, run_id=start["id"])

    def _upload(self, kind, run_id, files, data=None, params=None):
        if not self.api_key:
            raise ValueError("Execution credential is required")
        if int(run_id) >= 0 and int(run_id) != int(self.run_id):
            raise ValueError("Upload belongs to another execution")
        response = requests.post(
            f"{self.base_url}{self.app_id}/{system_settings.http_upload_path}/{kind}",
            data={"runId": str(run_id if int(run_id) < 0 else self.app_id), **(data or {})},
            files=files, params=params, headers=self.form_headers,
            timeout=(5, 120), allow_redirects=False,
        )
        response.raise_for_status()
        if response.status_code >= 300:
            raise requests.HTTPError("Execution upload was redirected", response=response)
        return response

    def upload_model_file(self, run_id: int, name: str, file_path: str) -> requests.Response:
        """
        Upload model via MULTIPART_FORM_DATA to match:
        ModelSubDataDTO { runId, name, filePath, file }
        """
        p = Path(file_path)
        with p.open("rb") as f:
            return self._upload("model", run_id, {"file": (p.name, f, "application/octet-stream")},
                                data={"name": name, "filePath": str(p)})

    def upload_output(self, run_type, run_id: int,
                      output: dict[str, Any],
                      meta: Optional[dict[str, Any]] = None) -> requests.Response:

        fields = {}
        with ExitStack() as stack:
            files = []
            for key, value in output.items():
                if isinstance(value, Path) and value.exists():
                    content_type = mimetypes.guess_type(value.name)[0] or "application/octet-stream"
                    files.append(("files", (value.name, stack.enter_context(value.open("rb")), content_type,
                                             {"X-Key": key, "X-Name": value.name})))
                elif value is not None:
                    fields[key] = str(value)
            files.append(("fields", (None, json.dumps(fields), "application/json")))
            if meta:
                files.append(("meta", (None, json.dumps(meta), "application/json")))
            return self._upload("output", run_id, files, params={"runType": run_type.value})
