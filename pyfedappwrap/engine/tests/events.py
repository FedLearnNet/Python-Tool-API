import random

from pyfedappwrap.engine.config.config_handler import load_config
from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.enums.test_embed_states import TestEmbedEnum, RunType
from pyfedappwrap.engine.generator.generator import RandomTestGeneratorFactory
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage


class TestEvents:
    def __init__(self, test_data: RandomTestGeneratorFactory):
        self.config = load_config(system_settings.config_settings_path)
        if self.config is None:
            raise ValueError(f"Failed to load config from {system_settings.config_settings_path}")
        self.input_configs = self.config.appConfig.input
        self.hyper_params = self.config.appConfig.hyperparams
        self.test_data_factory = test_data

    def get_hyperparams(self):
        hyperparams = {}
        pre_defined_hyperparams = self.test_data_factory.hyperparams or {}
        for param in self.hyper_params:
            if param.name in pre_defined_hyperparams.keys():
                hyperparams[param.name] = pre_defined_hyperparams[param.name]
            else:
                hyperparams[param.name] = param.default
        return hyperparams

    def get_input_files(self):
        input_files = {}
        for input_cfg in self.input_configs:
            name = input_cfg.name
            generated_path = self.test_data_factory.path_name(name)
            if generated_path is not None:
                input_files[name] = generated_path
            elif input_cfg.required:
                raise ValueError(f"Failed to generate input file for {name}")
        print("Generated input files:", input_files)
        return input_files

    def get_federated_input_files(self):
        input_files = {}
        for input_cfg in self.input_configs:
            name = input_cfg.name
            generated_path = self.test_data_factory.path_name(name)
            if generated_path is not None:
                input_files[name] = generated_path.name
            elif input_cfg.required:
                raise ValueError(f"Failed to generate input file for {name}")
        print("Generated federated input files:", input_files)
        return input_files

    def get_base_body(self):
        return {
            "hyperParams": self.get_hyperparams(),
            "inputData": {},
            "inputFilePaths": self.get_input_files(),
            "id": random.randint(3, 4000),
            "status": "PENDING",
        }

    def default_start_prediction_task(self) -> BaseSocketMessage:
        body = self.get_base_body()

        return BaseSocketMessage(
            type=TestEmbedEnum.START_PREDICTION,
            message=body,
            run_type=RunType.TEST_RUN
        )

    def default_start_run_task(self) -> BaseSocketMessage:
        body = self.get_base_body()
        print("Using input files:", body["inputFilePaths"])
        return BaseSocketMessage(
            type=TestEmbedEnum.START_RUN,
            message=body,
            run_type=RunType.TEST_RUN
        )

    def default_start_federated_test_run_task(self) -> BaseSocketMessage:
        hyperparams = self.get_hyperparams()
        input_files = self.get_federated_input_files()
        total_rounds = hyperparams.get("federated_rounds") or hyperparams.get("total_rounds")
        try:
            total_rounds = int(total_rounds) if total_rounds is not None else None
        except (TypeError, ValueError):
            total_rounds = None

        aggregator_hyperparams = {
            key: value
            for key, value in hyperparams.items()
            if key in {"communication_id", "federated_rounds", "total_rounds", "output_filename"}
        }

        body = {
            "id": random.randint(3, 4000),
            "status": "PENDING",
            "totalRounds": total_rounds,
            "startAggregator": True,
            "config": {
                "pollInterval": 0.01,
                "timeout": 30,
                "maxPolls": 3000,
            },
            "participants": [
                {
                    "participantId": "aggregator",
                    "role": "AGGREGATOR",
                    "hyperParams": aggregator_hyperparams,
                    "inputFilePaths": input_files,
                },
                {
                    "participantId": "client-1",
                    "role": "CLIENT",
                    "hyperParams": hyperparams,
                    "inputFilePaths": input_files,
                },
                {
                    "participantId": "client-2",
                    "role": "CLIENT",
                    "hyperParams": hyperparams,
                    "inputFilePaths": input_files,
                },
            ],
        }
        return BaseSocketMessage(
            type=TestEmbedEnum.START_FEDERATED_TEST_RUN,
            message=body,
            run_type=RunType.FEDERATED_TEST_RUN,
        )
