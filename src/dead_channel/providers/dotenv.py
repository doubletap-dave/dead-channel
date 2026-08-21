"""Load KEY=VALUE pairs from a .env file into a dict (no third-party deps).

File values never override existing environment entries.
"""

import re
from pathlib import Path

_LINE = re.compile(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$")


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def load_dotenv_into(env: dict[str, str], env_file: Path) -> int:
    if not env_file.exists():
        return 0
    loaded = 0
    for line in env_file.read_text(encoding="utf-8").splitlines():
        match = _LINE.match(line)
        if match is None or line.lstrip().startswith("#"):
            continue
        key, value = match.group(1), _unquote(match.group(2))
        if key not in env:
            env[key] = value
            loaded += 1
    return loaded
