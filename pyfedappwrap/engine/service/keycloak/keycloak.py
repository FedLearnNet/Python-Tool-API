from pathlib import Path
import base64
import hashlib
import secrets
import webbrowser
import requests
import logging

from urllib.parse import urlencode, parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, HTTPServer

from pyfedappwrap.engine.config.system_config import system_settings

logger = logging.getLogger("KeycloakClient")
logger.setLevel(logging.INFO)


def generate_code_verifier() -> str:
    """
    PKCE code verifier.
    Must be a high-entropy random string.
    """
    return base64.urlsafe_b64encode(secrets.token_bytes(64)).decode("utf-8").rstrip("=")


def generate_code_challenge(code_verifier: str) -> str:
    """
    PKCE S256 code challenge.
    Keycloak expects this when the client requires PKCE.
    """
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


class CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        code = params.get("code", [""])[0]
        state = params.get("state", [""])[0]
        valid = bool(code and state and secrets.compare_digest(state, self.server.auth_state))
        self.server.auth_code = code if valid else None
        self.send_response(200 if valid else 400)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.open_file_response("success.html" if valid else "fail.html")

    def log_message(self, format, *args):
        # The callback URL contains an authorization code; never write it to the access log.
        return

    def open_file_response(self, file_name):
        self.wfile.write(Path(__file__).with_name(file_name).read_bytes())


class KeycloakClient:
    def __init__(self):
        self.keycloak_url = system_settings.keycloak.url.rstrip("/")
        self.client_id = system_settings.keycloak.client_id
        self.redirect_uri = system_settings.keycloak.redirect_uri
        self.server_port = system_settings.keycloak.server_port

        self.code_verifier = None
        self.auth_state = None

    def get_token(self):
        auth_code = self._get_auth_code()

        if not auth_code:
            logger.error("Authentication error")
            return None

        return self._exchange_code_for_token(auth_code)

    def _get_auth_code(self):
        self.code_verifier = generate_code_verifier()
        self.auth_state = secrets.token_urlsafe(32)
        code_challenge = generate_code_challenge(self.code_verifier)

        auth_url = f"{self.keycloak_url}/protocol/openid-connect/auth?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": self.auth_state,
        })

        with HTTPServer(("localhost", self.server_port), CallbackHandler) as server:
            server.auth_code = None
            server.auth_state = self.auth_state
            server.timeout = 180
            webbrowser.open(auth_url)
            server.handle_request()
            return server.auth_code

    def _exchange_code_for_token(self, auth_code):
        token_url = f"{self.keycloak_url}/protocol/openid-connect/token"

        data = {
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
            "code_verifier": self.code_verifier,
        }

        response = requests.post(token_url, data=data, timeout=(5, 30), allow_redirects=False)

        if response.status_code == 200:
            token_response = response.json()
            access_token = token_response.get("access_token")

            logger.info("Access token retrieved successfully")
            return access_token

        logger.error("Error retrieving token: HTTP %s", response.status_code)
        return None
