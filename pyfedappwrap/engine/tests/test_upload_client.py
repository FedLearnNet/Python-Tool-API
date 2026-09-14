from typing import Any, Optional

import requests

from pyfedappwrap.engine.service.upload.upload_client import AbstractUploadClient


class TestUploadClient(AbstractUploadClient):

    def __init__(self, token: str):
        super().__init__(token)

    def upload_model_file(self, run_id: int, name: str, file_path: str) -> requests.Response:
        print("Mock upload_model called")
        response = requests.Response()
        response.status_code = 200
        return response

    def upload_output(self, run_type, run_id: int,
                      output: dict[str, Any],
                      meta: Optional[dict[str, Any]] = None) -> requests.Response:
        print("Mock upload_output called")
        response = requests.Response()
        response.status_code = 200
        return response
