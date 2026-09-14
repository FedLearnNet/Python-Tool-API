from pyfedappwrap.engine.config.config_handler import load_config, save_config, does_config_exist
from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.enums.test_embed_states import TestEmbedEnum
from pyfedappwrap.engine.service.socket.messages.base import BaseSocketMessage
from pyfedappwrap.engine.worker.data_manager import list_all_data_files


def handle_internal_event(event: BaseSocketMessage, send_sync):
    # Handle the received event here
    event_type = event.type
    run_type = event.run_type
    message = event.message
    print(f"Handling event: {event_type}")
    if TestEmbedEnum.CLIENT_STARTED.equals(event_type):
        print(f"Client started: {message}")
        config = load_config(system_settings.config_settings_path)
        if config is not None and system_settings.prio_local_config:
            msg = config.__dict__
            send_sync(BaseSocketMessage(type=TestEmbedEnum.CONFIG_CHANGED,
                                        message=msg,
                                        run_type=run_type))

        send_sync(BaseSocketMessage(type=TestEmbedEnum.CONFIG_CLIENT_SEND,
                                    message=system_settings.model_dump(),
                                    run_type=run_type))

        send_sync(BaseSocketMessage(type=TestEmbedEnum.DATA_LIST_CLIENT_SEND,
                                    message=list_all_data_files(),
                                    run_type=run_type))

    elif TestEmbedEnum.CONFIG_CHANGED.equals(event_type):
        print(f"Configuration changed: {message}")
        save_config(system_settings.config_settings_path, message)

    elif TestEmbedEnum.CONFIG_INITIAL_SEND.equals(event_type):
        print(f"Configuration initial send: {message}")
        if (not system_settings.prio_local_config or
                not does_config_exist(system_settings.config_settings_path)):
            save_config(system_settings.config_settings_path, message)

