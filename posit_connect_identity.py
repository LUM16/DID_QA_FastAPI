"""Resolve the authenticated Posit Connect username for the current request."""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Any

import requests


def _header(headers: Mapping[str, str], name: str) -> str:
    expected = name.casefold()
    for key, value in headers.items():
        if key.casefold() == expected:
            return str(value).strip()
    return ""


def _xsrf_token(cookie_header: str) -> str:
    for item in cookie_header.split(";"):
        name, separator, value = item.strip().partition("=")
        if separator and name == "RSC-XSRF-legacy":
            return value
    return ""


def _me_endpoint(headers: Mapping[str, str]) -> str:
    configured = os.environ.get("POSIT_CONNECT_ME_URL", "").strip()
    if configured:
        return configured
    host = _header(headers, "X-Forwarded-Host") or _header(headers, "Host")
    if not host:
        return ""
    protocol = (_header(headers, "X-Forwarded-Proto") or "https").split(",", 1)[0].strip()
    if protocol not in {"http", "https"}:
        return ""
    return f"{protocol}://{host}/__api__/me"


def current_ntid(headers: Mapping[str, str]) -> str:
    """Return the Posit Connect username from its authenticated ``/__api__/me`` API."""
    cookie_header = _header(headers, "Cookie")
    if not cookie_header:
        return ""
    endpoint = _me_endpoint(headers)
    if not endpoint:
        return ""
    request_headers = {"Accept": "application/json", "Cookie": cookie_header}
    xsrf_token = _xsrf_token(cookie_header)
    if xsrf_token:
        request_headers["X-RSC-XSRF"] = xsrf_token
    try:
        response = requests.get(endpoint, headers=request_headers, timeout=5)
        response.raise_for_status()
        payload: Any = response.json()
    except (requests.RequestException, ValueError):
        return ""
    if not isinstance(payload, dict):
        return ""
    profile = payload.get("profile") or payload.get("user") or payload
    if not isinstance(profile, dict):
        return ""
    return str(profile.get("username") or payload.get("username") or "").strip()