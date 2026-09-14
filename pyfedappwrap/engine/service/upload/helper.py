import logging
from typing import Any
from urllib.parse import urlparse

import requests
import validators

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.helper.url_helper import replace_domain, remove_path_prefix, \
    get_request_header


def get_base_address(url: str) -> str:
    """
    Extracts and returns the “protocol://host:port” part of any given URL.
    """
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url!r}")
    return f"{parsed.scheme}://{parsed.netloc}"


def is_remote_resource(value: Any) -> bool:
    try:
        result = isinstance(value, str) and validators.url(value, simple_host=True)
        logging.info(f"Checking if '{value}' is a valid URL: {result}")
        return result
    except Exception:
        logging.warning(f"Remote resource '{value}' is not a valid URL")
        return False


def download_file(file_url: str, token: str, as_utf_8: bool = False) -> str | bytes | None | Any:
    parsed_file_url = replace_domain(file_url, system_settings.http_url)
    url = remove_path_prefix(parsed_file_url, system_settings.url_prefix_remove)
    headers = get_request_header(token)
    response = requests.get(parsed_file_url, headers=headers)
    logger = logging.getLogger(__name__)
    logger.info(f"Downloading file from {url} instead of {file_url}")
    if response.status_code == 200:
        if as_utf_8:
            return response.content.decode("utf-8")
        return response.content
    logger.error("Failed to download file from %s: %s", url, response.status_code)
    return None
