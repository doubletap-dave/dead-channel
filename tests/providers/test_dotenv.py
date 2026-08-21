"""dotenv loader: parse, no-override semantics, comments, quotes."""

from pathlib import Path

from dead_channel.providers.dotenv import load_dotenv_into


def test_loads_keys_and_respects_existing_env(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "OPENROUTER_API_KEY=sk-or-v1-abc\n"
        "# comment line\n"
        "\n"
        "PPLX_API_KEY='pplx-quoted'\n"
        'export OPENAI_API_KEY="sk-openai"\n',
        encoding="utf-8",
    )
    env = {"OPENAI_API_KEY": "keep-me"}
    loaded = load_dotenv_into(env, env_file)
    assert env["OPENROUTER_API_KEY"] == "sk-or-v1-abc"
    assert env["PPLX_API_KEY"] == "pplx-quoted"
    assert env["OPENAI_API_KEY"] == "keep-me", "file must not override process env"
    assert loaded == 2


def test_missing_file_loads_nothing(tmp_path: Path) -> None:
    env: dict[str, str] = {}
    assert load_dotenv_into(env, tmp_path / "nope.env") == 0
    assert env == {}
