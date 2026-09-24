"""Pfizer Vox GenAI V2 client (OAuth + OpenAI-compatible chat)."""

from __future__ import annotations

import logging
import os
import time
from collections.abc import Generator
from contextlib import contextmanager
from importlib import import_module
from typing import Any

import requests
from openai import OpenAI

from neo4j_client import load_env

log = logging.getLogger(__name__)

_token_cache: dict[str, Any] = {"access_token": None, "expires_at": 0.0}
_client_cache: dict[str, Any] = {
    "client": None,
    "model": None,
    "base": None,
    "token": None,
}


def empty_usage() -> dict[str, int]:
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def _usage_from_response(resp: Any) -> dict[str, int]:
    usage = empty_usage()
    raw = getattr(resp, "usage", None)
    if raw is None:
        return usage
    usage["prompt_tokens"] = int(getattr(raw, "prompt_tokens", 0) or 0)
    usage["completion_tokens"] = int(getattr(raw, "completion_tokens", 0) or 0)
    usage["total_tokens"] = int(
        getattr(raw, "total_tokens", 0)
        or (usage["prompt_tokens"] + usage["completion_tokens"])
    )
    return usage


def add_usage(a: dict[str, int], b: dict[str, int]) -> dict[str, int]:
    return {
        "prompt_tokens": a.get("prompt_tokens", 0) + b.get("prompt_tokens", 0),
        "completion_tokens": a.get("completion_tokens", 0) + b.get("completion_tokens", 0),
        "total_tokens": a.get("total_tokens", 0) + b.get("total_tokens", 0),
    }


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip().strip('"').strip("'")


def _require_http_url(name: str) -> str:
    value = _env(name).rstrip("/")
    if not value:
        raise ValueError(f"{name} is empty.")
    if not value.lower().startswith(("http://", "https://")):
        raise ValueError(
            f"{name} must be a full URL starting with https://, not {value!r}. "
            "Example: https://mule4api-comm-amer.pfizer.com/vox-genai-api-v2"
        )
    return value


def _vox_configured() -> bool:
    load_env()
    return bool(
        _env("VOX_GENAI_API")
        and _env("VOX_TOKEN_GEN_URL")
        and _env("VOX_CLIENT_ID")
        and _env("VOX_CLIENT_SECRET")
    )


def vox_configured() -> bool:
    return _vox_configured()


def _describe_vox_error(exc: BaseException, *, stage: str) -> str:
    api = _env("VOX_GENAI_API").rstrip("/")
    token_url = _env("VOX_TOKEN_GEN_URL")
    model = _env("VOX_MODEL") or "gpt-4o"
    detail = str(exc).strip() or type(exc).__name__
    if stage == "token":
        return (
            f"Vox token request failed for {token_url}. "
            f"Original error: {detail}"
        )
    return (
        f"Vox chat API unreachable at {api} (model {model}). "
        "Neo4j can be fine while this still fails. "
        f"Original error: {detail}"
    )


def _langfuse_configured() -> bool:
    load_env()
    public_key = _env("LANGFUSE_PUBLIC_KEY")
    secret_key = _env("LANGFUSE_SECRET_KEY")
    if bool(public_key) != bool(secret_key):
        raise RuntimeError(
            "Incomplete Langfuse config. Set both LANGFUSE_PUBLIC_KEY and "
            "LANGFUSE_SECRET_KEY, or leave both empty to disable tracing."
        )
    return bool(public_key and secret_key)


@contextmanager
def _langfuse_generation(
    model: str,
    messages: list[dict[str, str]],
    temperature: float,
) -> Generator[Any | None, None, None]:
    if not _langfuse_configured():
        yield None
        return

    try:
        get_client = getattr(import_module("langfuse"), "get_client")
    except ImportError as exc:
        raise RuntimeError(
            "Langfuse is configured but the langfuse package is not installed. "
            "Install dependencies from requirements.txt."
        ) from exc

    langfuse = get_client()
    with langfuse.start_as_current_observation(
        name=_env("LANGFUSE_OBSERVATION_NAME") or "vox-chat-completion",
        as_type="generation",
        input=messages,
        model=model,
        model_parameters={"temperature": temperature},
        metadata={"provider": "vox-genai-v2"},
    ) as generation:
        yield generation


def vox_health() -> dict[str, Any]:
    load_env()
    api = _env("VOX_GENAI_API").rstrip("/")
    token_url = _env("VOX_TOKEN_GEN_URL")
    model = _env("VOX_MODEL") or "gpt-4o"
    if not _vox_configured():
        return {
            "ok": False,
            "configured": False,
            "primary": None,
            "api": api or None,
            "model": model,
            "error": "Vox Vars are not set",
        }
    try:
        api = _require_http_url("VOX_GENAI_API")
        token_url = _require_http_url("VOX_TOKEN_GEN_URL")
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "configured": True,
            "primary": "vox",
            "api": api,
            "token_url": token_url,
            "model": model,
            "error": str(exc),
        }
    try:
        get_vox_access_token()
    except Exception as exc:  # noqa: BLE001
        log.exception("Vox health: token request failed")
        return {
            "ok": False,
            "configured": True,
            "primary": "vox",
            "api": api,
            "token_url": token_url,
            "model": model,
            "error": _describe_vox_error(exc, stage="token"),
        }
    try:
        models_vox_genai()
    except Exception as exc:  # noqa: BLE001
        log.exception("Vox health: chat API unreachable")
        return {
            "ok": False,
            "configured": True,
            "primary": "vox",
            "api": api,
            "token_url": token_url,
            "model": model,
            "error": _describe_vox_error(exc, stage="chat"),
        }
    return {
        "ok": True,
        "configured": True,
        "primary": "vox",
        "api": api,
        "token_url": token_url,
        "model": model,
        "error": None,
    }


def get_vox_access_token(force_refresh: bool = False) -> str:
    load_env()
    now = time.time()
    if (
        not force_refresh
        and _token_cache["access_token"]
        and now < float(_token_cache["expires_at"]) - 60
    ):
        return str(_token_cache["access_token"])

    resp = requests.post(
        _require_http_url("VOX_TOKEN_GEN_URL"),
        data={
            "grant_type": "client_credentials",
            "client_id": _env("VOX_CLIENT_ID"),
            "client_secret": _env("VOX_CLIENT_SECRET"),
        },
        timeout=60,
    )
    if resp.status_code >= 400:
        raise RuntimeError(f"Vox token request failed ({resp.status_code}): {resp.text[:400]}")

    payload = resp.json()
    access_token = payload.get("access_token")
    if not access_token:
        raise RuntimeError(f"Vox token response missing access_token: {payload}")

    expires_in = int(payload.get("expires_in", 1800))
    _token_cache["access_token"] = access_token
    _token_cache["expires_at"] = now + expires_in
    return access_token


def build_llm_client() -> tuple[OpenAI, str]:
    load_env()

    if _vox_configured():
        token = get_vox_access_token()
        base = _require_http_url("VOX_GENAI_API")
        model = _env("VOX_MODEL") or "gpt-4o"
        cached = _client_cache.get("client")
        if (
            cached is not None
            and _client_cache.get("token") == token
            and _client_cache.get("base") == base
            and _client_cache.get("model") == model
        ):
            return cached, model
        client = OpenAI(api_key=token, base_url=f"{base}/v1")
        _client_cache.update(
            {"client": client, "model": model, "base": base, "token": token}
        )
        return client, model

    raise ValueError(
        "Missing Vox GenAI config. Set VOX_GENAI_API, VOX_TOKEN_GEN_URL, "
        "VOX_CLIENT_ID, and VOX_CLIENT_SECRET in Connect Vars or .env."
    )


def clear_llm_client_cache() -> None:
    client = _client_cache.get("client")
    close = getattr(client, "close", None)
    if callable(close):
        close()
    _client_cache.update({"client": None, "model": None, "base": None, "token": None})


def models_vox_genai() -> list[str]:
    client, _ = build_llm_client()
    response = client.models.list()
    data = getattr(response, "data", None)
    if data is None:
        raise RuntimeError("Vox models.list() response missing data")

    model_ids: list[str] = []
    for item in data:
        model_id = getattr(item, "id", None)
        if isinstance(model_id, str) and model_id.strip():
            model_ids.append(model_id.strip())

    # Keep order stable while de-duplicating.
    return list(dict.fromkeys(model_ids))


def chat(
    system: str,
    user: str,
    temperature: float = 0.1,
    max_tokens: int | None = None,
) -> tuple[str, dict[str, int]]:
    client, model = build_llm_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]

    request_options: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
    }
    if max_tokens is not None:
        request_options["max_tokens"] = max_tokens

    with _langfuse_generation(model, messages, temperature) as generation:
        def request_completion(options: dict[str, Any]) -> Any:
            nonlocal client, model
            try:
                return client.chat.completions.create(**options)
            except Exception as first_err:
                if not (_vox_configured() and "401" in str(first_err)):
                    log.exception("Vox chat failed")
                    raise RuntimeError(
                        _describe_vox_error(first_err, stage="chat")
                    ) from first_err
                try:
                    get_vox_access_token(force_refresh=True)
                    client, model = build_llm_client()
                    retry_options = dict(options)
                    retry_options["model"] = model
                    return client.chat.completions.create(**retry_options)
                except Exception as retry_err:
                    log.exception("Vox chat failed after 401 retry")
                    raise RuntimeError(
                        _describe_vox_error(retry_err, stage="chat")
                    ) from retry_err

        resp = request_completion(request_options)
        text = (resp.choices[0].message.content or "").strip()
        usage = _usage_from_response(resp)
        if not text and max_tokens is not None:
            log.warning(
                "Vox chat returned empty content with max_tokens=%s; retrying without max_tokens",
                max_tokens,
            )
            retry_options = dict(request_options)
            retry_options.pop("max_tokens", None)
            resp = request_completion(retry_options)
            text = (resp.choices[0].message.content or "").strip()
            usage = add_usage(usage, _usage_from_response(resp))
        if generation is not None:
            generation.update(output=text, usage_details=usage)
        return text, usage
