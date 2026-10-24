import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from .analysis import SCHEMA, normalize_for_provider


class ProviderError(RuntimeError):
    pass


class PromptTooLargeError(ProviderError):
    pass


def _gemini_schema(schema):
    result = {}
    for key, value in schema.items():
        if key == "additionalProperties":
            continue
        if key == "type" and isinstance(value, str):
            result[key] = value.upper()
        elif key == "properties":
            result[key] = {name: _gemini_schema(item) for name, item in value.items()}
        elif key == "items":
            result[key] = _gemini_schema(value)
        else:
            result[key] = value
    return result


def check_local():
    base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    if urllib.parse.urlparse(base).hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ProviderError("OLLAMA_URL must point to this computer.")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(f"{base}/api/tags", timeout=1) as response:
                models = [item["name"] for item in json.loads(response.read()).get("models", [])]
            if not any(name == model or name.startswith(f"{model}:") for name in models):
                raise ProviderError(f"Ollama is running, but model '{model}' is missing. Run `ollama pull {model}`.")
            return models
        except ProviderError:
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            if attempt == 2:
                raise ProviderError(
                    "Ollama at 127.0.0.1:11434 did not respond after 3 one-second checks. "
                    "Start Ollama Desktop or run `ollama serve`, then retry. No cloud provider was called."
                ) from None
            time.sleep(0.25)


def model_for(provider):
    return {
        "local": os.environ.get("OLLAMA_MODEL", "qwen2.5:1.5b"),
        "openai": os.environ.get("OPENAI_MODEL", "gpt-4o-mini"),
        "gemini": os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite"),
    }[provider]


def local_limits():
    context, output = 4096, 1536
    return context, output, context - output - 256


def _timeout_seconds(name, default):
    try:
        value = int(os.environ.get(name, default))
    except ValueError as exc:
        raise ProviderError(f"{name} must be an integer number of seconds.") from exc
    if not 1 <= value <= 1800:
        raise ProviderError(f"{name} must be between 1 and 1800 seconds.")
    return value


def _post(url, payload, headers=None, timeout=None):
    timeout = _timeout_seconds("AI_REQUEST_TIMEOUT_SECONDS", 180) if timeout is None else timeout
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", **(headers or {})},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        if exc.code == 429 and "generativelanguage.googleapis.com" in url:
            raise ProviderError(
                "Gemini Free Tier quota/rate limit exceeded (HTTP 429). Wait for quota reset or review AI Studio limits. "
                "Klipnara will not upgrade billing, retry automatically, or switch providers."
            ) from None
        if exc.code == 403 and "generativelanguage.googleapis.com" in url:
            raise ProviderError(
                "Gemini denied this request (HTTP 403). Check Free Tier key/model access; no paid or provider fallback was attempted."
            ) from None
        if urllib.parse.urlparse(url).hostname in {"127.0.0.1", "localhost", "::1"}:
            details = exc.read(4096).decode("utf-8", errors="ignore").lower()
            if "context" in details and any(term in details for term in ("exceed", "length", "token", "size")):
                raise PromptTooLargeError("Prompt exceeds Ollama model context.") from None
        raise ProviderError(f"AI provider rejected request (HTTP {exc.code}).") from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProviderError(f"AI provider unavailable: {type(exc).__name__}.") from None


def analyze(provider, prompt, schema=SCHEMA, schema_name="clip_candidates"):
    if provider == "local":
        response, model = _local_chat(prompt, schema)
        try:
            usage = {
                "prompt_tokens": response.get("prompt_eval_count"),
                "completion_tokens": response.get("eval_count"),
            }
            return normalize_for_provider(response["message"]["content"]), model, usage
        except (KeyError, TypeError):
            raise ProviderError("Ollama returned an unexpected response.") from None

    if provider == "openai":
        key = os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ProviderError("OPENAI_API_KEY is not configured on the backend.")
        model = model_for(provider)
        response = _post(
            "https://api.openai.com/v1/chat/completions",
            {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "response_format": {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "strict": True, "schema": schema},
                },
            },
            {"Authorization": f"Bearer {key}"},
        )
        try:
            return normalize_for_provider(response["choices"][0]["message"]["content"]), model, response.get("usage")
        except (KeyError, IndexError, TypeError):
            raise ProviderError("OpenAI returned an unexpected response.") from None

    if provider == "gemini":
        key = os.environ.get("GEMINI_API_KEY")
        if not key:
            raise ProviderError("GEMINI_API_KEY is not configured on the backend.")
        model = model_for(provider)
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{urllib.parse.quote(model, safe='-')}:generateContent"
        response = _post(
            url,
            {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"responseMimeType": "application/json", "responseSchema": _gemini_schema(schema)},
            },
            headers={"x-goog-api-key": key},
        )
        try:
            return normalize_for_provider(response["candidates"][0]["content"]["parts"][0]["text"]), model, response.get("usageMetadata")
        except (KeyError, IndexError, TypeError):
            raise ProviderError("Gemini returned an unexpected response.") from None

    raise ProviderError("Unknown AI provider.")


def _local_chat(prompt, schema, *, count_only=False):
    base = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
    model = model_for("local")
    context, output, _ = local_limits()
    check_local()
    try:
        response = _post(
            f"{base}/api/chat",
            {
                "model": model,
                "stream": False,
                "format": schema,
                "messages": [{"role": "user", "content": prompt}],
                "options": {"temperature": 0.2, "num_ctx": context, "num_predict": 1 if count_only else output},
            },
            timeout=_timeout_seconds("OLLAMA_TIMEOUT_SECONDS", 600),
        )
    except ProviderError as exc:
        if str(exc).startswith("AI provider unavailable"):
            raise ProviderError(
                "Ollama inference timed out or stopped responding. Check Ollama/model load and retry locally; no cloud fallback."
            ) from None
        raise
    return response, model


def count_prompt_tokens(prompt, schema=SCHEMA):
    """Ollama 0.40 has no tokenizer endpoint; one-token chat returns exact eval count."""
    response, model = _local_chat(prompt, schema, count_only=True)
    usage = {
        "prompt_tokens": response.get("prompt_eval_count"),
        "completion_tokens": response.get("eval_count"),
    }
    if not isinstance(usage["prompt_tokens"], int):
        raise ProviderError("Ollama did not return prompt_eval_count; cannot enforce context limit.")
    return usage["prompt_tokens"], model, usage
