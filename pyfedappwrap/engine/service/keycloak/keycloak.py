import os
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
        query = urlparse(self.path).query
        params = parse_qs(query)

        if "code" in params:
            logger.info("[CallbackHandler] Received auth code")
            self.server.auth_code = params["code"][0]

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()

            self.open_file_response("success.html")
        else:
            logger.error("[CallbackHandler] Authentication error: %s", params)
            self.server.auth_code = None

            self.send_response(400)
            self.send_header("Content-type", "text/html")
            self.end_headers()

            self.open_file_response("fail.html")

    def open_file_response(self, file_name):
        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(script_dir, file_name)

        with open(file_path, "r", encoding="utf-8") as file:
            html_content = file.read()
            self.wfile.write(html_content.encode("utf-8"))


class KeycloakClient:
    def __init__(self):
        self.keycloak_url = system_settings.keycloak.url.rstrip("/")
        self.client_id = system_settings.keycloak.client_id
        self.redirect_uri = system_settings.keycloak.redirect_uri
        self.server_port = system_settings.keycloak.server_port

        self.code_verifier = None

    def get_token(self):
        auth_code = self._get_auth_code()

        if not auth_code:
            logger.error("Authentication error")
            return None

        token = self._exchange_code_for_token(auth_code)
        return token

    def _get_auth_code(self):
        self.code_verifier = generate_code_verifier()
        code_challenge = generate_code_challenge(self.code_verifier)

        auth_url = f"{self.keycloak_url}/protocol/openid-connect/auth?" + urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": "openid",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        })

        webbrowser.open(auth_url)

        server = HTTPServer(("localhost", self.server_port), CallbackHandler)
        server.auth_code = None
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

        response = requests.post(token_url, data=data)

        if response.status_code == 200:
            token_response = response.json()
            access_token = token_response.get("access_token")

            logger.info("Access token retrieved successfully")
            return access_token

        logger.error("Error retrieving token: %s", response.text)
        return None