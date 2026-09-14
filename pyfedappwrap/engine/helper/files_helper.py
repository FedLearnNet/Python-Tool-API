from pathlib import Path

from pyfedappwrap.engine.config.system_config import system_settings


def _ensure_directory_exists(directory: str, description: str) -> None:
    """
    Ensures that the specified directory exists, creating it if necessary.

    Args:
        directory: The directory path to check/create
        description: A description of the directory for logging purposes
    """
    path = Path(directory)
    if not path.exists():
        path.mkdir(parents=True, exist_ok=True)
        print(f"{description} directory created at: {directory}")
    else:
        print(f"{description} directory already exists at: {directory}")


def ensure_system_directories() -> None:
    """
    Ensures that system data and model directories exist.
    """

    if system_settings.data_dir:
        _ensure_directory_exists(system_settings.data_dir, "Data")
        print(f"Data directory is set to: {system_settings.data_dir}")
    if system_settings.model_dir:
        _ensure_directory_exists(system_settings.model_dir, "Model")
        print(f"Model directory is set to: {system_settings.model_dir}")


def create_data_file_path(relative_path: str) -> Path:
    """
    Creates a full file path by combining the base directory with the relative path.
    Args:
        relative_path: The relative path to append to the base directory

    Returns:
        A Path object representing the full file path
    """
    return Path(system_settings.data_dir) / relative_path
