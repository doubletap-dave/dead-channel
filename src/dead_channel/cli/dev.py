"""Unified dev launcher: uvicorn backend + Vite viewer with prefixed output."""

import contextlib
import os
import subprocess
import sys
import threading
from collections.abc import Sequence
from pathlib import Path

from dead_channel.cli import _winjob
from dead_channel.providers.dotenv import load_dotenv_into
from dead_channel.providers.keys import KEY_ENV_NAMES

_VIEWER_DIR = Path(__file__).resolve().parents[3] / "viewer"
if not _VIEWER_DIR.is_dir():  # installed as a package, not a repo checkout
    _VIEWER_DIR = Path.cwd() / "viewer"

_PREFIX_PAD = 9
_CHILDREN: list[subprocess.Popen[bytes]] = []


def _env() -> dict[str, str]:
    env = dict(os.environ)
    # uvicorn does not read .env; without this, keys set in the UI's .env never
    # reach pydantic-ai and every run dies on "Set the OPENROUTER_API_KEY...".
    loaded = load_dotenv_into(env, Path(".env"))
    if any(env.get(name) for name in KEY_ENV_NAMES.values()):
        print(f"api keys loaded from .env ({loaded} entries)", flush=True)
    env["PYTHONUTF8"] = "1"
    return env


def _pump(pipe, prefix: str) -> None:
    for raw in iter(pipe.readline, b""):
        line = raw.decode(errors="replace").rstrip()
        if line:
            print(f"{prefix.ljust(_PREFIX_PAD)}| {line}", flush=True)
    code = pipe.close()
    if code not in (None, 0):
        print(f"{prefix.ljust(_PREFIX_PAD)}| exited with {code}", flush=True)


def _spawn(cmd: Sequence[str], prefix: str, cwd: Path | None = None) -> subprocess.Popen[bytes]:
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        env=_env(),
        cwd=str(cwd) if cwd else None,
    )
    assert process.stdout is not None
    threading.Thread(target=_pump, args=(process.stdout, prefix), daemon=True).start()
    _CHILDREN.append(process)
    return process


def _kill_tree(process: subprocess.Popen[bytes] | None) -> None:
    if process is None or process.poll() is not None:
        return
    # taskkill /T reaches the whole tree (npm.cmd -> node -> esbuild), which
    # terminate()/send_signal() cannot on Windows.
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
            )
        else:
            process.terminate()
    with contextlib.suppress(OSError, subprocess.SubprocessError):
        process.wait(timeout=5)


def _shutdown_all() -> None:
    for process in list(_CHILDREN):
        _kill_tree(process)


def main(argv: Sequence[str] | None = None) -> int:
    del argv  # no options yet; kept for entry-point symmetry
    # Child output (Vite arrows etc.) is UTF-8; the Windows console may not be.
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    npm = "npm.cmd" if sys.platform == "win32" else "npm"
    api = _spawn(
        [sys.executable, "-m", "uvicorn", "dead_channel.server.app:app", "--port", "8000"],
        "api",
    )
    viewer = (
        _spawn([npm, "run", "dev"], "viewer", cwd=_VIEWER_DIR) if _VIEWER_DIR.is_dir() else None
    )
    if viewer is None:
        print("viewer/ directory not found — starting API only", flush=True)

    if _CHILDREN:
        try:
            _winjob.assign_children_to_job([p.pid for p in _CHILDREN])
            print("job object armed — children cannot outlive this launcher", flush=True)
        except OSError as exc:
            print(
                f"WARNING: job object not armed ({exc}); orphans possible on hard kill",
                flush=True,
            )
    try:
        api.wait()
    except KeyboardInterrupt:
        print("\nshutting down…", flush=True)
    finally:
        _shutdown_all()
    return api.returncode or 0


if __name__ == "__main__":
    sys.exit(main())
