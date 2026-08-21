"""API key management: read/write the repo .env, never echo secrets back."""

import os
import re
from pathlib import Path

KEY_ENV_NAMES: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "perplexity": "PPLX_API_KEY",
}
_PROVIDERS = tuple(KEY_ENV_NAMES)

_DEFAULT_TEMPLATE = """\
# Dead Channel - provider API keys (gitignored; editable from the config UI)

# OpenAI (platform.openai.com)
OPENAI_API_KEY=

# OpenRouter (openrouter.ai/keys)
OPENROUTER_API_KEY=

# Perplexity (perplexity.ai)
PPLX_API_KEY=
"""


def _env_path(env_file: Path | None) -> Path:
    return env_file if env_file is not None else Path(".env")


def mask(value: str) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:6]}…{value[-4:]}"


def read_keys(env_file: Path | None = None) -> dict[str, str]:
    """Provider -> raw value; empty string = unset. Process env wins over file."""
    path = _env_path(env_file)
    values = {provider: os.environ.get(env, "") for provider, env in KEY_ENV_NAMES.items()}
    if path.exists():
        pattern = re.compile(r"^\s*([A-Z0-9_]+)\s*=\s*(.*)$")
        file_values = {
            match.group(1): match.group(2).strip()
            for match in (
                pattern.match(line) for line in path.read_text(encoding="utf-8").splitlines()
            )
            if match
        }
        for provider, env in KEY_ENV_NAMES.items():
            if not values[provider]:
                values[provider] = file_values.get(env, "")
    return values


def write_key(provider: str, value: str, *, env_file: Path | None = None) -> dict[str, str]:
    """Persist one provider key to .env and refresh os.environ for this process."""
    if provider not in KEY_ENV_NAMES:
        raise KeyError(f"unknown provider: {provider!r}")
    name = KEY_ENV_NAMES[provider]
    path = _env_path(env_file)
    lines = (
        path.read_text(encoding="utf-8").splitlines()
        if path.exists()
        else _DEFAULT_TEMPLATE.splitlines()
    )
    pattern = re.compile(rf"^(\s*{name}\s*=\s*)(.*)$")
    replacement = f"{name}={value.strip()}"
    replaced = False
    updated: list[str] = []
    for line in lines:
        if pattern.match(line):
            updated.append(replacement)
            replaced = True
        else:
            updated.append(line)
    if not replaced:
        while updated and not updated[-1].strip():
            updated.pop()
        updated += ["", replacement]
    path.write_text("\n".join(updated) + "\n", encoding="utf-8")
    os.environ[name] = value.strip()
    return read_keys(path)
