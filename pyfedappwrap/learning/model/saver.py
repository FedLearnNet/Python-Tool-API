import os
from typing import Optional

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.enums.test_embed_states import RunType
from pyfedappwrap.engine.service.upload.upload_client import UploadClient


class ModelSaver:
    def __init__(self, upload_client: UploadClient, run_id, run_type: RunType):
        self.model_dir = system_settings.model_dir
        self.run_id = run_id
        self.upload_client: UploadClient = upload_client
        self.run_type: RunType = run_type

    def save(self, path_name: str, model_name: Optional[str]):
        name = model_name if model_name is not None else path_name
        print(f"Saving model to {path_name} with name {name}")
        model_path = os.path.join(self.model_dir, path_name)
        if not os.path.exists(model_path):
            print("Model file does not exist, skipping upload.")
            return

        if self.upload_client is not None:
            self.upload_client.upload_model_file(
                run_id=self.run_id,
                name=name,
                file_path=model_path
            )
        else:
            print("Model saving upload_client does not exist, skipping upload.")

    def restore(self, file_dto):
        self._save_binary_to_file(file_dto)

    @staticmethod
    def _save_binary_to_file(file_dto) -> None:
        with open(file_dto.model_path, "wb") as file:
            file.write(file_dto.model_params)
