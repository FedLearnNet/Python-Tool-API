from urllib.parse import urlsplit

import requests
from dotenv import set_key

from pyfedappwrap.engine.config.system_config import system_settings
from pyfedappwrap.engine.service.keycloak.keycloak import KeycloakClient


def authenticate_execution():
    token = (system_settings.app_key or "").strip() or None
    api_key = (system_settings.app_api_key or "").strip() or None
    http_url, ws_url = system_settings.http_url, system_settings.ws_url
    if not api_key:
        if not token and not system_settings.dev_mode:
            raise ValueError("Supply APP_API_KEY or an authenticated APP_KEY for execution bootstrap")
        token = token or KeycloakClient().get_token()
        if not token:
            raise ValueError("Execution authentication failed")
        development = urlsplit(http_url).path.rstrip("/").endswith("/testembed")
        if not development:
            http_url, ws_url = execution_base_url(http_url), execution_base_url(ws_url)
        api_key = bootstrap_execution(http_url, system_settings.app_id, token)
        if development:
            set_key(system_settings.model_config["env_file"], "APP_API_KEY", api_key)
            system_settings.app_api_key = api_key
    return token, api_key, http_url, ws_url


def authentication_headers(token=None, api_key=None):
    if api_key:
        return {"X-API-Key": api_key}
    if token:
        return {"Authorization": f"Bearer {token}"}
    return {}


def execution_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    path = parsed.path.rstrip("/")
    prefix = path.rsplit("/execution/", 1)[0] if "/execution/" in path else path.removesuffix("/testembed")
    if prefix == path:
        raise ValueError("Expected a TestEmbed or execution backend URL")
    return parsed._replace(path=f"{prefix}/execution/APP/", query="", fragment="").geturl()


def bootstrap_execution(base_url: str, execution_id, token: str) -> str:
    if not token:
        raise ValueError("An authenticated user is required to provision execution credentials")
    response = requests.post(
        f"{base_url.rstrip('/')}/{int(execution_id)}/credential",
        headers=authentication_headers(token),
        timeout=(5, 30),
        allow_redirects=False,
    )
    response.raise_for_status()
    if response.status_code != 200:
        raise ValueError("Execution credential bootstrap did not succeed")
    key = response.json().get("apiKey")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Execution credential bootstrap returned no credential")
    return key
