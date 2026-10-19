"""Minimal client for the internal GitHub Copilot token vault."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import time
from typing import Any

import requests

from neo4j_client import load_env

DEFAULT_VAULT_URL = "http://10.109.2.165:7101/api/github-token-vault"
NTID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")


def normalize_ntid(ntid: str) -> str:
    value = ntid.strip()
    if not NTID_PATTERN.fullmatch(value):
        raise ValueError(
            "Enter a valid NTID using letters, numbers, dots, hyphens, or underscores."
        )
    return value


def _vault_config() -> tuple[str, str]:
    load_env()
    access_key = os.environ.get("GITHUB_TOKEN_VAULT_ACCESS_KEY", "").strip()
    if not access_key:
        raise RuntimeError(
            "GitHub Token Vault is not configured. Set GITHUB_TOKEN_VAULT_ACCESS_KEY."
        )
    base_url = os.environ.get("GITHUB_TOKEN_VAULT_URL", DEFAULT_VAULT_URL).rstrip("/")
    return base_url, access_key


def _signed_headers(method: str, endpoint: str, body: bytes) -> dict[str, str]:
    secret = os.environ.get("BACKEND_SHARED_SECRET", "").strip()
    if not secret:
        raise RuntimeError("GitHub Token Vault is not configured. Set BACKEND_SHARED_SECRET.")
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    message = "\n".join((method, endpoint, timestamp, nonce, hashlib.sha256(body).hexdigest()))
    signature = hmac.new(
        secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return {
        "Content-Type": "application/json",
        "X-SDI-Timestamp": timestamp,
        "X-SDI-Nonce": nonce,
        "X-SDI-Signature": signature,
    }


def _post(action: str, payload: dict[str, str]) -> dict[str, Any]:
    base_url, access_key = _vault_config()
    endpoint = f"/api/github-token-vault/{action}"
    body = json.dumps(
        {**payload, "accessKey": access_key}, separators=(",", ":")
    ).encode("utf-8")
    try:
        response = requests.post(
            f"{base_url}/{action}",
            data=body,
            headers=_signed_headers("POST", endpoint, body),
            timeout=20,
        )
    except requests.RequestException as exc:
        raise RuntimeError("Could not reach GitHub Token Vault.") from exc
    if response.status_code == 403:
        raise RuntimeError("GitHub Token Vault authorization failed.")
    if response.status_code >= 400:
        raise RuntimeError("GitHub Token Vault request failed.")
    try:
        result = response.json()
    except ValueError as exc:
        raise RuntimeError("GitHub Token Vault returned an invalid response.") from exc
    if not isinstance(result, dict) or result.get("ok") is not True:
        raise RuntimeError("GitHub Token Vault did not confirm the request.")
    return result


def save_copilot_token(ntid: str, token: str) -> None:
    normalized_ntid = normalize_ntid(ntid)
    if not token.strip():
        raise ValueError("Enter a GitHub Copilot token.")
    _post("upsert", {"ntid": normalized_ntid, "copilot_github_token": token.strip()})


def retrieve_copilot_token(ntid: str) -> str:
    result = _post("retrieve", {"ntid": normalize_ntid(ntid)})
    token = result.get("copilot_github_token")
    if not isinstance(token, str) or not token.strip():
        raise RuntimeError("No GitHub Copilot token is saved for this NTID.")
    return token.strip()