from __future__ import annotations

from typing import Any

import httpx

_WEB_FETCH_USER_AGENT = "FocusAgent/1.0 (+https://example.local/focus-agent)"


def pinned_fetch_target(
    parsed_url: Any,
    address: str,
    *,
    urllib_parse_module: Any,
) -> tuple[str, dict[str, str], dict[str, bytes]]:
    host = str(parsed_url.hostname or "").rstrip(".")
    ascii_host = host.encode("idna").decode("ascii")
    default_port = 443 if parsed_url.scheme == "https" else 80
    port = parsed_url.port or default_port
    authority_host = f"[{ascii_host}]" if ":" in ascii_host else ascii_host
    authority = authority_host if port == default_port else f"{authority_host}:{port}"
    pinned_host = f"[{address}]" if ":" in address else address
    pinned_netloc = pinned_host if port == default_port else f"{pinned_host}:{port}"
    pinned_url = urllib_parse_module.urlunparse(parsed_url._replace(netloc=pinned_netloc))
    return pinned_url, {"Host": authority}, {"sni_hostname": ascii_host.encode("ascii")}


def request_pinned_fetch_url(
    *,
    client: Any,
    parsed_url: Any,
    addresses: tuple[str, ...],
    urllib_parse_module: Any,
) -> Any:
    request_headers = {"User-Agent": _WEB_FETCH_USER_AGENT}
    last_connect_error: httpx.TransportError | None = None
    for address in addresses:
        pinned_url, authority_headers, extensions = pinned_fetch_target(
            parsed_url,
            address,
            urllib_parse_module=urllib_parse_module,
        )
        try:
            if client is None:
                with httpx.Client(follow_redirects=False, trust_env=False) as pinned_client:
                    return pinned_client.get(
                        pinned_url,
                        headers={**request_headers, **authority_headers},
                        timeout=30,
                        extensions=extensions,
                    )
            return client.get(
                pinned_url,
                headers={**request_headers, **authority_headers},
                timeout=30,
                extensions=extensions,
            )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            last_connect_error = exc
    if last_connect_error is not None:
        raise last_connect_error
    raise ValueError("Web fetch DNS resolution returned no usable public addresses.")


__all__ = ["pinned_fetch_target", "request_pinned_fetch_url"]
