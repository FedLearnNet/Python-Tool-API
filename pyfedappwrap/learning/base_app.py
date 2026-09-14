import asyncio
import shutil
import threading
import time
import traceback
from abc import ABC, abstractmethod
from asyncio import Queue
from dataclasses import asdict
from enum import Enum
from pathlib import Path
from typing import TypeVar, Generic, Optional, get_origin, get_args, Any

from pydantic import TypeAdapter

from pyfedappwrap.engine.config.config import FederatedAppBaseConfigDTO, AppType, ModeType
from pyfedappwrap.engine.config.config_handler import load_config, load_tool_type
from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.enums.test_embed_states import RunType
from pyfedappwrap.engine.helper.banner import print_validation_error_banner
from pyfedappwrap.engine.helper.pandas_helper import convert_dict_output_to_paths
from pyfedappwrap.engine.helper.visualisation_helper import visualisations_to_string
from pyfedappwrap.engine.logger import WebSocketLogger
from pyfedappwrap.engine.runtime_lifecycle import EngineLifecycle
from pyfedappwrap.engine.service.socket.messages.app import AppTaskMessage, SendUpdateRunDTO, \
    SendFinishRunDTO
from pyfedappwrap.engine.service.socket.messages.message import TestRunMessageMetricDTO, \
    RunMessageTypes, SendMetricDTO
from pyfedappwrap.engine.service.upload.upload_client import UploadClient
from pyfedappwrap.engine.validate.dto import ToolFileEvaluationResultDTO
from pyfedappwrap.engine.validate.validator import ValidatorService
from pyfedappwrap.engine.watcher.cpu_watcher import SystemWatcher
from pyfedappwrap.engine.watcher.run_timing import RunTiming
from pyfedappwrap.engine.worker.data_manager import get_data
from pyfedappwrap.engine.worker.run_dto import RunStatusTypes, UpdateTestRunDTO, FinishRunDTO, \
    RunMetaDTO
from pyfedappwrap.learning.model.saver import ModelSaver
from pyfedappwrap.learning.run_runfig import AppOutputConfig, AppConfig, AppInputConfig

C = TypeVar('C', bound=AppConfig)
I = TypeVar('I', bound=AppInputConfig)
O = TypeVar('O', bound=AppOutputConfig)


class DataValidatorService(Generic[I, O]):
    def __init__(self):
        self.config = load_config(system_settings.config_settings_path)
        if self.config is None:
            raise ValueError(f"Failed to load config from {system_settings.config_settings_path}")
        self.input_configs = self.config.appConfig.input
        self.output_configs = self.config.appConfig.output

    def validate_output(self, output: O, mode: ModeType) -> tuple[
        list[ToolFileEvaluationResultDTO], bool]:
        data = asdict(output)
        return self.validate(data, self.output_configs, mode)

    def validate_input(self, input_data: I, mode: ModeType) -> tuple[
        list[ToolFileEvaluationResultDTO], bool]:
        data = asdict(input_data)
        return self.validate_input_dict(data, mode)

    def validate_input_dict(self, data: dict, mode: ModeType) -> tuple[
        list[ToolFileEvaluationResultDTO], bool]:
        return self.validate(data, self.input_configs, mode)

    def validate(self, data: dict, config: list[FederatedAppBaseConfigDTO],
                 mode: ModeType) -> tuple[
        list[ToolFileEvaluationResultDTO], bool]:
        results = []
        for cfg in config:
            req = True
            if mode is not ModeType.BOTH:
                # if train or prediction mode is specified in the config, only validate if it matches the current mode
                if cfg.mode is not None and cfg.mode.lower() != mode.lower():
                    req = False
            if cfg.name not in data or data[cfg.name] is None:
                if req:
                    result = ToolFileEvaluationResultDTO.fail(
                        f"Data missing for {cfg.name}", cfg.name)
                    results.append(result)
                continue
            value = data[cfg.name]
            validator = ValidatorService(value, cfg)
            result = validator.validate()
            results.append(result)
        has_errors = self.check_for_errors(results)
        return results, not has_errors

    @staticmethod
    def check_for_errors(results: list[ToolFileEvaluationResultDTO]) -> bool:
        for result in results:
            if not result.ok:
                return True
        return False

    def get_path_for_output(self, key: str, folder: Path) -> Optional[Path]:
        for cfg in self.output_configs:
            if cfg.name == key:
                name = cfg.name + "." + cfg.type.name.lower()
                return folder / name
        return None


class BaseApp(ABC, Generic[C, I, O]):
    def __init__(self):
        self.config: Optional[C] = None
        self.validator = DataValidatorService[I, O]()
        self.status: RunStatusTypes = RunStatusTypes.PENDING
        self.tool_type = load_tool_type(system_settings.config_settings_path)
        self.run_type = RunType.NOT_DEFINED
        self.task_queue = None
        self._lifecycle: Optional[EngineLifecycle] = None
        self.finish_event = None
        self.websocket_client = None
        self.upload_client: Optional[UploadClient] = None
        self.app_id = None
        self.run_id = None
        self.name = None
        self.logger = None
        self.saver = None
        self.system_watcher = None
        self.timing: Optional[RunTiming] = None
        self.c_type = None
        self.i_type = None
        self.stop_worker = None
        self.c_type, self.i_type = BaseApp._resolve_baseapp_types(self.__class__)
        if self.c_type is None or self.i_type is None:
            # Provide a clearer error indicating which class failed resolution
            raise TypeError(
                f"Could not resolve generic parameters C and I for {self.__class__.__name__}. "
                f"Ensure your concrete subclass ultimately inherits from BaseApp[C, I, O] "
                f"with C (config) and I (input) concretely specified."
            )

    def set_startup(self, websocket_client, upload_client, app_id, run_id, run_type: RunType,
                    lifecycle: EngineLifecycle, stop_worker):
        self.websocket_client = websocket_client
        self.upload_client = upload_client
        self.app_id = app_id
        self.run_id = run_id
        self.run_type: RunType = run_type
        self._lifecycle: EngineLifecycle = lifecycle
        self.name = f"Worker {app_id}"
        self.logger = WebSocketLogger(
            self.name,
            self.websocket_client,
            self.run_id,
            self.run_type,
            worker_id=app_id,
        )
        self.system_watcher = SystemWatcher(self._lifecycle, self.websocket_client)
        self.task_queue = Queue()
        self.finish_event = threading.Event()
        # Begin lifecycle timing for this run. engine_start/connected are picked up from the
        # process-boot references so container start + engine init count towards startup overhead.
        self.timing = RunTiming()
        self.timing.mark_run_received()
        self.update_status(RunStatusTypes.INITIALIZED)
        self.stop_worker = stop_worker
        self.saver = ModelSaver(self.upload_client, self.run_id, self.run_type)

    def get_model_name(self):
        return self.name

    def save(self):
        if self.tool_type and self.tool_type == AppType.ANALYSIS:
            # Federated runs DO produce a final model (each participant primes its model with the
            # aggregated global coefficients), so the trained model.joblib must be uploaded via
            # upload_model_file just like a normal run. Only pure TEST_RUN has no model to persist.
            if self.run_type != RunType.TEST_RUN:
                path_name = self._save()
                if self.saver is not None:
                    self.saver.save(path_name, self.get_model_name())
                else:
                    self.logger.error(f"Failed to save model to {path_name} because saver is null")

    @abstractmethod
    def _save(self) -> str:
        """
        Save the model to a file and return the file name.

        This method should be implemented by subclasses to handle the actual
        saving of the model to a file. The implementation should store the model
        to a file and return the name of the file as a string.

        Returns:
            str: The name of the file where the model is saved.
        """
        pass

    @abstractmethod
    def _load(self, path: str):
        pass

    def on_config_loaded(self, config: C):
        self.config = config

    def send_output(self, output: O, mode: ModeType = ModeType.TRAINING):
        self.logger.info(f"Received output: {list(asdict(output).keys())}")

        self.finish_run(output, mode)

    def start(self, config: C, input_data: I, mode: ModeType = ModeType.TRAINING):
        self.logger.info(f"Starting app with mode: {mode}")
        self.on_config_loaded(config)
        # Bracket only the tool's scientific function so runtime excludes validation/mapping and
        # output transfer. If run() raises, compute_end stays None (ERROR path).
        if self.timing is not None:
            self.timing.mark_compute_start()
        output = self.run(input_data, mode)
        if self.timing is not None:
            self.timing.mark_compute_end()
        self.send_output(output, mode)

    def run(self, data: I, mode: ModeType = ModeType.TRAINING) -> O:
        if mode == ModeType.TRAINING:
            return self.run_train(data)
        elif mode == ModeType.VALIDATION:
            return self.run_prediction(data)
        elif mode == ModeType.PREDICTION:
            if self.tool_type and self.tool_type == AppType.ANALYSIS:
                self.logger.info(f"Starting prediction for ANALYSIS")
            return self.run_prediction(data)
        else:
            raise ValueError(f"Invalid mode: {mode}")

    @abstractmethod
    def run_train(self, data: I) -> O:
        pass

    @abstractmethod
    def run_prediction(self, data: I) -> O:
        pass

    def start_app(self):
        asyncio.run(self.start_process())

    async def start_process(self):
        try:
            # Start CPU tracking in a separate thread
            # tracking_thread = threading.Thread(target=self.track_cpu_usage)
            # tracking_thread.start()
            self.update_status(RunStatusTypes.RUNNING)

            # Perform tasks from the queue
            while not self._lifecycle.is_stopping() or not self.finish_event.is_set():
                if not self.task_queue.empty():
                    task = await self.task_queue.get()
                    self.perform_task(task)
                else:
                    time.sleep(1)

            self.stop_worker()
            self.update_status(RunStatusTypes.FINISHED)

            # tracking_thread.join()
        except Exception as e:
            self.update_status(RunStatusTypes.ERROR, str(e))
            self.logger.error(f"Error in start_process: {e}")
            self.stop_worker(str(e))
            traceback.print_exc()

    def finish_run(self, output: O, mode: ModeType = ModeType.TRAINING):
        self.logger.info(f"Finished app with mode: {mode}")
        validation, validation_success = (self.validator
                                          .validate_output(output,
                                                           self.needs_mode_specific_validation(
                                                               mode)))
        # TODO change to rename columns or apply mapping inside of validation
        if not validation_success and self.tool_type is not AppType.DATA_TRANSFORMATION:
            if self._lifecycle:
                self._lifecycle.request_exit_output_validation(validation)
            self.stop_worker(ToolFileEvaluationResultDTO.str_list(validation))
            self.stop("Invalid output data.")
            print_validation_error_banner(validation)
            raise ValueError(f"Output data validation failed: {validation}")
        self.logger.info(f"Finished output validation with {len(validation)} results, success")
        self.status = RunStatusTypes.FINISHED
        visualisations: Optional[str] = visualisations_to_string(output)
        output_dict = asdict(output)
        if visualisations is not None:
            output_dict["visualisations"] = visualisations
        output_paths: dict[str, Any] = convert_dict_output_to_paths(output_dict)
        # Snapshot the timing before the upload: for data-analysis runs the output upload is the
        # terminal call (the backend marks the run FINISHED and tears the container down right
        # after), so the websocket FINISH_RUN below never arrives and the timing must ride on the
        # upload. Teardown here therefore excludes the upload's own network transfer.
        upload_meta = None
        if self.timing is not None:
            self.timing.mark_outputs_transferred()
            meta = self._build_run_meta()
            upload_meta = meta.model_dump(by_alias=True) if meta is not None else None
        if system_settings.enable_remote_result_saving:
            self.upload_client.upload_output(self.run_type, self.run_id, output_paths,
                                             meta=upload_meta)
        self.save_results(output_paths)
        if mode == ModeType.TRAINING:
            self.save()
        # Refine the teardown mark to include upload + save for run types whose FINISH_RUN websocket
        # message is still processed (e.g. test/experiment runs).
        if self.timing is not None:
            self.timing.mark_outputs_transferred()
        dto = self._build_finish_dto()
        self.finish_event.set()
        self.stop_worker()
        self.logger.info("Inform server over finished app")
        self.websocket_client.send(SendFinishRunDTO(message=dto, run_type=self.run_type))

    def _build_run_meta(self) -> Optional[RunMetaDTO]:
        """Build the run metadata (timings) from the current timing marks, or None if unavailable."""
        if self.timing is None:
            return None
        timings = self.timing.timings_dict()
        return RunMetaDTO(timings=timings) if timings else None

    def _build_finish_dto(self) -> FinishRunDTO:
        """Assemble the FINISH_RUN payload with the measured monotonic timings in run metadata.
        The wrapper always reports runtime and the raw overhead breakdown; whether the overhead is
        persisted and displayed is decided by the learning-api (posymed.runtime.overhead.enabled),
        keeping a single source of truth for the flag."""
        return FinishRunDTO(run_id=self.run_id, meta=self._build_run_meta())

    def save_results(self, output: dict[str, Any]):
        # safe files also in output
        if system_settings.enable_local_result_saving:
            output_dir = system_settings.output_dir
            self.logger.info(f"Saving results local to {output_dir}")
            path = Path(output_dir) if not isinstance(output_dir, Path) else output_dir
            path.mkdir(parents=True, exist_ok=True)
            for key, value in output.items():
                if isinstance(value, Path) and value.exists():
                    dest_path = self.validator.get_path_for_output(key, path)
                    shutil.move(str(value), str(dest_path))
                    self.logger.info(f"Saved {value.name} to {dest_path}")

    def save_df(self, df, name: str) -> Path:
        output_dir = system_settings.output_dir
        path = Path(output_dir) if not isinstance(output_dir, Path) else output_dir
        path.mkdir(parents=True, exist_ok=True)
        file_path = path / f"{name}.csv"
        df.to_csv(file_path, index=False)
        self.logger.info(f"Saved DataFrame to {file_path}")
        return file_path

    def update_status(self, status: RunStatusTypes, error: str = None):
        self.status = status
        self.logger.info(f"Status updated: {status}")
        dto = UpdateTestRunDTO(run_id=self.run_id, status=status, error=error)
        self.websocket_client.send(SendUpdateRunDTO(message=dto, run_type=self.run_type))

    def send_metric(self, metric: str, value: float, x: Optional[int] = None,
                    x_label: Optional[str] = None):
        # Accept a MetricName (or any Enum): a str-Enum stringifies to "MetricName.X", so normalise to
        # its value ("val_auc") to keep the on-the-wire metric name a plain string the backend matches.
        if isinstance(metric, Enum):
            metric = metric.value
        self.logger.info(f"Sending metric: {metric} - {value}")
        dto = TestRunMessageMetricDTO(process=self.app_id,
                                      run_id=self.run_id,
                                      type=RunMessageTypes.METRIC,
                                      message=metric,
                                      worker_id=self.app_id,
                                      metric=metric,
                                      value=str(value),
                                      x=str(x),
                                      x_unit=str(x_label))
        self.websocket_client.send(SendMetricDTO(message=dto, run_type=self.run_type))

    def perform_task(self, task: AppTaskMessage):
        """Simulate performing a task."""
        self.logger.info(f"Starting task: {task}", "task")
        # TODO rename columns is input mapping is there in config, put it into map before validation and run
        if task.task.lower() == "TestEmbedEnum.START_RUN".lower():
            config_instance, input_config_instance = self.map(task.body)
            self.start(config_instance, input_config_instance)
        if task.task.lower() == "TestEmbedEnum.START_PREDICTION".lower():
            config_instance, input_config_instance = self.map(task.body)
            self.start(config_instance, input_config_instance, ModeType.PREDICTION)
        self.logger.info(f"Task completed: {task}", "task")

    def needs_mode_specific_validation(self, mode: ModeType) -> ModeType:
        if self.tool_type == AppType.ANALYSIS:
            return mode
        return ModeType.BOTH

    def map(self, body: dict, mode: ModeType = ModeType.TRAINING):
        try:
            hyper_params_dict = body["hyperParams"]
            token = self.upload_client.token
            input_data = get_data(body["inputData"], body["inputFilePaths"], self.i_type, token)
            validation, validation_success = self.validator.validate_input_dict(
                input_data, self.needs_mode_specific_validation(mode))
            # TODO USE rename columns instead
            if not validation_success and self.tool_type is not AppType.DATA_TRANSFORMATION:
                if self._lifecycle and self._lifecycle.test_mode:
                    self._lifecycle.request_exit_output_validation(validation)
                    self.stop_worker(ToolFileEvaluationResultDTO.str_list(validation))
                self.stop("Invalid input data.")
                print_validation_error_banner(validation)
                raise ValueError(f"Error mapping task body: {validation}")
            config_adapter = TypeAdapter(self.c_type)
            input_config_adapter = TypeAdapter(self.i_type)
            config_instance = config_adapter.validate_python(hyper_params_dict)
            input_config_instance = input_config_adapter.validate_python(input_data)
            self.logger.info(f"Input and config mapping task done")
            return config_instance, input_config_instance
        except Exception as e:
            self.logger.error(f"Error input and config mapping task body: {e}")
            if self._lifecycle and self._lifecycle.test_mode:
                self._lifecycle.request_exit(e)
                self.stop(e)
            raise ValueError(f"Error mapping task body: {e}")

    def stop(self, error=None):
        self.finish_event.set()
        # if error is None:
        #    self.update_status(RunStatusTypes.ERROR, "App stopped.")

    def get_status(self):
        return self.status

    async def enqueue_task(self, task: AppTaskMessage):
        """Add a task to the queue."""
        await self.task_queue.put(task)
        self.logger.info(f"Task added to queue: {task}", "task")

    @staticmethod
    def _resolve_baseapp_types(cls):
        varmap = {}
        # Walk down the MRO from the concrete class towards BaseApp
        for current in getattr(cls, '__mro__', ()):  # includes cls itself
            for orig in getattr(current, '__orig_bases__', ()):  # parametrized bases
                origin = get_origin(orig)
                if origin is None:
                    continue
                # Apply current var mappings to the args for proper substitution
                args = list(get_args(orig))
                args = [varmap.get(a, a) for a in args]

                # Update TypeVar -> concrete mappings for this level
                params = getattr(origin, '__parameters__', ())
                for p, a in zip(params, args):
                    # If a maps to another TypeVar, keep substituting via varmap
                    if isinstance(a, TypeVar) and a in varmap:
                        a = varmap[a]
                    varmap[p] = a

                # If we found the BaseApp origin, extract C and I (first two args)
                if origin is BaseApp and len(args) >= 2:
                    return args[0], args[1]
        return None, None

    def get_test_data(self) -> Optional[dict[str, Path]]:
        """Helper method to get test data for the app."""
        # This method can be overridden by subclasses to provide specific test data
        return None

    def get_test_hyperparams(self) -> Optional[dict[str, Any]]:
        """Helper method to get test hyperparams for the app."""
        # This method can be overridden by subclasses to provide specific test data
        return None
