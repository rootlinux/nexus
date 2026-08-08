from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _fake_path(tmp_path: Path) -> tuple[Path, Path]:
    log = tmp_path / "docker.log"
    docker = tmp_path / "docker"
    docker.write_text(
        """#!/bin/sh
printf '%s\\n' "$*" >> "$DOCKER_TEST_LOG"
case "$*" in
  info) exit 0 ;;
  *"config --services"*) printf 'postgres\\nredis\\nbackend\\nweb\\ncaddy\\n' ;;
  *"ps -q postgres"*) printf 'postgres-id\\n' ;;
  *"ps -q redis"*) printf 'redis-id\\n' ;;
  *"ps -q backend"*) printf 'backend-id\\n' ;;
  *"ps -q web"*) printf 'web-id\\n' ;;
  *"ps -q caddy"*) printf 'caddy-id\\n' ;;
  *"inspect"*) printf 'running healthy\\n' ;;
esac
""",
        encoding="utf-8",
    )
    docker.chmod(docker.stat().st_mode | stat.S_IXUSR)
    for name in ("curl", "open"):
        command = tmp_path / name
        command.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        command.chmod(command.stat().st_mode | stat.S_IXUSR)
    return tmp_path, log


def _run(script: str, tmp_path: Path) -> tuple[subprocess.CompletedProcess[str], str]:
    fake_path, log = _fake_path(tmp_path)
    env_file = tmp_path / "nexus.env"
    env_file.write_text("TEST_ONLY=1\n", encoding="utf-8")
    env_file.chmod(stat.S_IRUSR | stat.S_IWUSR)
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_path}:{env['PATH']}",
            "DOCKER_TEST_LOG": str(log),
            "DOCKER_LAUNCH_NO_OPEN": "1",
            "DOCKER_START_TIMEOUT": "2",
            "NEXUS_DOCKER_ENV_FILE": str(env_file),
        }
    )
    result = subprocess.run(
        [str(ROOT / script)],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    return result, log.read_text(encoding="utf-8") if log.exists() else ""


def test_start_launcher_builds_and_waits_for_every_nexus_service(tmp_path: Path) -> None:
    result, calls = _run("START-DOCKER.command", tmp_path)

    assert result.returncode == 0, result.stderr
    assert "--project-name deploy" in calls
    assert "up -d --build" in calls
    for service in ("postgres", "redis", "backend", "web", "caddy"):
        assert f"ps -q {service}" in calls


def test_stop_launcher_preserves_nexus_volumes(tmp_path: Path) -> None:
    result, calls = _run("STOP-DOCKER.command", tmp_path)

    assert result.returncode == 0, result.stderr
    assert "--project-name deploy" in calls
    assert " stop" in calls
    assert " -v" not in calls


def test_documented_local_compose_example_is_complete_and_persistent() -> None:
    result = subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(ROOT / "deploy" / ".env.local-smoke.example"),
            "-f",
            str(ROOT / "deploy" / "docker-compose.yml"),
            "-f",
            str(ROOT / "deploy" / "docker-compose.local.yml"),
            "config",
            "--format",
            "json",
        ],
        cwd=ROOT / "deploy",
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    config = json.loads(result.stdout)
    services = config["services"]
    backend = services["backend"]
    targets = {volume["target"] for volume in backend["volumes"]}
    assert "/app/uploads" in targets
    assert "/app/feedback_private_uploads" in targets
    assert backend["environment"]["API_PUBLIC_BASE_URL"] == "http://api.nexus.localtest.me"
    published = {(port["target"], port["published"], port["host_ip"]) for port in services["caddy"]["ports"]}
    assert published == {
        (80, "80", "127.0.0.1"),
        (443, "443", "127.0.0.1"),
    }
    assert "umask 077" in " ".join(backend["command"])
    assert services["web"].get("healthcheck")
    assert services["caddy"].get("healthcheck")
