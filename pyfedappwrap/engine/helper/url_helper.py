from urllib.parse import urlparse, urlunparse

from pyfedappwrap.engine.config.system_config import system_settings


def replace_domain(url: str, url_to_replaced_with: str) -> str:
    """
    Replace only scheme + domain (+ port) of `url`
    with the origin of `url_to_replaced_with`.

    Path/query/fragment of the original URL are preserved.

    Example:
        replace_domain(
            "http://localhost:8080/testembed/",
            "http://localhost:8081/sadf/"
        )
        -> "http://localhost:8081/testembed/"
    """

    original = urlparse(url)
    replacement = urlparse(url_to_replaced_with)

    new_url = original._replace(
        scheme=replacement.scheme,
        netloc=replacement.netloc
    )

    parsed = urlunparse(new_url)
    return _to_str(parsed)


def remove_path_prefix(url: str, prefix: str) -> str:
    """
    Remove a prefix from the path of a URL.

    Example:
        remove_path_prefix(
            "http://localhost:8080/api/v1/test",
            "/api/v1"
        )
        -> "http://localhost:8080/test"
    """

    parsed = urlparse(url)
    path = parsed.path

    if not prefix.startswith("/"):
        prefix = "/" + prefix

    if path.startswith(prefix):
        new_path = path[len(prefix):]
        if not new_path.startswith("/"):
            new_path = "/" + new_path
    else:
        new_path = path

    new_url = parsed._replace(path=new_path)

    parsed = urlunparse(new_url)
    return _to_str(parsed)


def get_request_header(token: str):
    headers = {"Authorization": "Bearer " + token}

    return headers

def _to_str(v: str | bytes) -> str:
    return v.decode() if isinstance(v, bytes) else v


def localhost_to_docker_host(url: str) -> str:
    """
    Replace localhost in the URL with host.docker.internal
    to allow access from within a Docker container.

    Example:
        localhost_to_docker_host("http://localhost:8080/test")
        -> "http://host.docker.internal:8080/test"
    """
    if "localhost" in url:
        return url.replace("localhost", system_settings.docker_host_internal)
    return url