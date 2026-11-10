from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


FAKE_REDIS_PASSWORD = "redis-test-secret-not-an-argument"


def _run_backup(
    tmp_path: Path,
    *,
    empty_redis_dump: bool = False,
    failed_bgsave: bool = False,
    pending_info_count: int = 2,
    never_completes: bool = False,
    info_failure: bool = False,
    malformed_info: bool = False,
    block_redis_docker: bool = False,
    max_attempts: int = 60,
    poll_interval: str = "0.01",
    redis_command_timeout: int = 75,
    block_operation: str | None = None,
    command_timeout: int = 600,
):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "bgsave-started"
    info_count = tmp_path / "info-count"
    redis_cli_log = tmp_path / "redis-cli.log"
    docker_args_log = tmp_path / "docker-args.log"

    redis_cli = fake_bin / "redis-cli"
    redis_cli.write_text(
        """#!/usr/bin/env bash
set -eu
[ "${REDISCLI_AUTH:-}" = "$FAKE_REDIS_PASSWORD" ] || { echo "REDISCLI_AUTH ausente" >&2; exit 92; }
printf '%s\\n' "$*" >> "$REDIS_CLI_LOG"
case "$*" in
  *"INFO persistence"*)
    count=0
    [ ! -f "$INFO_COUNT_FILE" ] || count="$(cat "$INFO_COUNT_FILE")"
    count=$((count + 1))
    printf '%s\\n' "$count" > "$INFO_COUNT_FILE"
    if [ -f "$BGSAVE_MARKER" ]; then
      if [ "${FAKE_BGSAVE_INFO_FAILURE:-false}" = "true" ]; then echo "redis INFO failed" >&2; exit 93; fi
      if [ "${FAKE_BGSAVE_MALFORMED_INFO:-false}" = "true" ]; then
        printf '# Persistence\\r\\nrdb_bgsave_in_progress:0\\r\\nrdb_last_bgsave_status:ok\\r\\n'
        exit 0
      fi
      post_count=$((count - 1))
      if [ "${FAKE_BGSAVE_NEVER_COMPLETES:-false}" = "true" ] || [ "$post_count" -le "$FAKE_BGSAVE_PENDING_INFO_COUNT" ]; then
        printf '# Persistence\\r\\nrdb_bgsave_in_progress:1\\r\\nrdb_saves:1\\r\\nrdb_last_bgsave_status:ok\\r\\n'
      elif [ "${FAKE_BGSAVE_FAILED:-false}" = "true" ]; then
        printf '# Persistence\\r\\nrdb_bgsave_in_progress:0\\r\\nrdb_saves:2\\r\\nrdb_last_bgsave_status:err\\r\\n'
      else
        printf '# Persistence\\r\\nrdb_bgsave_in_progress:0\\r\\nrdb_saves:2\\r\\nrdb_last_bgsave_status:ok\\r\\n'
      fi
    else
      printf '# Persistence\\r\\nrdb_bgsave_in_progress:0\\r\\nrdb_saves:1\\r\\nrdb_last_bgsave_status:ok\\r\\n'
    fi
    ;;
  *BGSAVE*) touch "$BGSAVE_MARKER"; printf 'Background saving started\\n' ;;
  *) echo "unexpected redis-cli invocation: $*" >&2; exit 91 ;;
esac
""",
        encoding="utf-8",
    )
    redis_cli.chmod(0o755)

    docker = fake_bin / "docker"
    docker.write_text(
        """#!/usr/bin/env bash
set -eu
joined="$*"
printf '%s\\n' "$joined" >> "$DOCKER_ARGS_LOG"
case "$joined" in
  *"exec -T db"*)
    if [ "${FAKE_DOCKER_BLOCK_OPERATION:-}" = "postgres_dump" ]; then sleep 10; fi
    printf 'postgres-dump-fixture'
    ;;
  *"exec -T -e"*redis*)
    if [ "${FAKE_DOCKER_REDIS_BLOCK:-false}" = "true" ]; then sleep 10; exit 0; fi
    args=("$@")
    container_script=""
    max_attempts=""
    poll_interval=""
    for ((i = 0; i < ${#args[@]}; i++)); do
      case "${args[$i]}" in
        -e)
          value="${args[$((i + 1))]}"
          case "$value" in
            REDIS_BGSAVE_MAX_ATTEMPTS=*) max_attempts="${value#*=}" ;;
            REDIS_BGSAVE_POLL_INTERVAL_SECONDS=*) poll_interval="${value#*=}" ;;
          esac
          ;;
        -ec) container_script="${args[$((i + 1))]}" ;;
      esac
    done
    [ -n "$container_script" ] && [ -n "$max_attempts" ] && [ -n "$poll_interval" ] || { echo "redis exec args ausentes" >&2; exit 94; }
    REDIS_PASSWORD="$FAKE_REDIS_PASSWORD" \\
      REDIS_BGSAVE_MAX_ATTEMPTS="$max_attempts" \\
      REDIS_BGSAVE_POLL_INTERVAL_SECONDS="$poll_interval" \\
      sh -ec "$container_script"
    ;;
  *"cp redis:/data/dump.rdb"*)
    if [ "${FAKE_DOCKER_BLOCK_OPERATION:-}" = "redis_copy" ]; then sleep 10; fi
    destination="${!#}"
    if [ "${EMPTY_REDIS_DUMP:-false}" = "true" ]; then : > "$destination"; else printf 'redis-rdb-fixture' > "$destination"; fi
    ;;
  *"cp api:/app/data"*|*"cp api:/app/models"*)
    if [[ "$joined" == *"cp api:/app/data"* && "${FAKE_DOCKER_BLOCK_OPERATION:-}" = "app_data_copy" ]]; then sleep 10; fi
    if [[ "$joined" == *"cp api:/app/models"* && "${FAKE_DOCKER_BLOCK_OPERATION:-}" = "app_models_copy" ]]; then sleep 10; fi
    destination="${!#}"
    mkdir -p "$destination"
    printf 'fixture' > "$destination/placeholder"
    ;;
  *) echo "unexpected docker invocation: $joined" >&2; exit 90 ;;
esac
""",
        encoding="utf-8",
    )
    docker.chmod(0o755)

    env_file = tmp_path / ".env.vps"
    env_file.write_text("placeholder=true\n", encoding="utf-8")
    backup_root = tmp_path / "backups"
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{fake_bin}:{env['PATH']}",
            "ENV_FILE": str(env_file),
            "BACKUP_ROOT": str(backup_root),
            "BACKUP_COMMAND_TIMEOUT_SECONDS": str(command_timeout),
            "COMPOSE_FILE": str(tmp_path / "compose.yml"),
            "BACKUP_REDIS_COMMAND_TIMEOUT_SECONDS": str(redis_command_timeout),
            "REDIS_BGSAVE_MAX_ATTEMPTS": str(max_attempts),
            "REDIS_BGSAVE_POLL_INTERVAL_SECONDS": poll_interval,
            "EMPTY_REDIS_DUMP": "true" if empty_redis_dump else "false",
            "FAKE_REDIS_PASSWORD": FAKE_REDIS_PASSWORD,
            "FAKE_BGSAVE_FAILED": "true" if failed_bgsave else "false",
            "FAKE_BGSAVE_PENDING_INFO_COUNT": str(pending_info_count),
            "FAKE_BGSAVE_NEVER_COMPLETES": "true" if never_completes else "false",
            "FAKE_BGSAVE_INFO_FAILURE": "true" if info_failure else "false",
            "FAKE_BGSAVE_MALFORMED_INFO": "true" if malformed_info else "false",
            "FAKE_DOCKER_REDIS_BLOCK": "true" if block_redis_docker else "false",
            "FAKE_DOCKER_BLOCK_OPERATION": block_operation or "",
            "BGSAVE_MARKER": str(marker),
            "INFO_COUNT_FILE": str(info_count),
            "REDIS_CLI_LOG": str(redis_cli_log),
            "DOCKER_ARGS_LOG": str(docker_args_log),
        }
    )
    result = subprocess.run(
        ["bash", str(Path(__file__).parents[1] / "scripts" / "vps_backup.sh")],
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=8,
    )
    backup_dirs = list(backup_root.iterdir()) if backup_root.exists() else []
    return result, backup_dirs, redis_cli_log, docker_args_log


def test_vps_backup_polls_while_redis_save_is_in_progress_then_copies_and_checksums(tmp_path):
    result, backup_dirs, redis_cli_log, docker_args_log = _run_backup(tmp_path)

    assert result.returncode == 0, result.stderr
    assert len(backup_dirs) == 1
    backup_dir = backup_dirs[0]
    assert (backup_dir / "redis_dump.rdb").read_bytes() == b"redis-rdb-fixture"
    assert "rdb_saves=2" in (backup_dir / "redis_bgsave.txt").read_text()
    assert (backup_dir / "app_data" / "placeholder").exists()
    assert (backup_dir / "app_models" / "placeholder").exists()

    redis_commands = redis_cli_log.read_text().splitlines()
    assert redis_commands == [
        "--no-auth-warning INFO persistence",
        "--no-auth-warning BGSAVE",
        "--no-auth-warning INFO persistence",
        "--no-auth-warning INFO persistence",
        "--no-auth-warning INFO persistence",
    ]
    docker_arguments = docker_args_log.read_text()
    assert "BGSAVE" in docker_arguments
    assert FAKE_REDIS_PASSWORD not in docker_arguments
    assert FAKE_REDIS_PASSWORD not in redis_cli_log.read_text()

    checked = subprocess.run(
        ["sha256sum", "--check", "SHA256SUMS"],
        cwd=backup_dir,
        capture_output=True,
        text=True,
        check=False,
    )
    assert checked.returncode == 0, checked.stderr
    manifest = (backup_dir / "MANIFEST").read_text()
    assert "redis_dump.rdb" in manifest
    assert "postgres.dump" in manifest
    assert "SHA256SUMS" in manifest


def test_vps_backup_fails_closed_when_redis_rdb_is_empty(tmp_path):
    result, _backup_dirs, _redis_log, _docker_log = _run_backup(tmp_path, empty_redis_dump=True)

    assert result.returncode != 0
    assert "Snapshot Redis ausente ou vazio" in result.stderr


def test_vps_backup_fails_closed_when_redis_bgsave_reports_failure(tmp_path):
    result, _backup_dirs, _redis_log, _docker_log = _run_backup(tmp_path, failed_bgsave=True)

    assert result.returncode != 0
    assert "Último BGSAVE Redis falhou" in result.stderr


def test_vps_backup_fails_closed_when_bgsave_never_increments_save_counter(tmp_path):
    result, _backup_dirs, redis_cli_log, _docker_log = _run_backup(
        tmp_path, never_completes=True, max_attempts=3
    )

    assert result.returncode != 0
    assert "Timeout aguardando incremento/conclusão" in result.stderr
    assert redis_cli_log.read_text().count("INFO persistence") == 4


def test_vps_backup_fails_closed_when_redis_info_command_fails(tmp_path):
    result, _backup_dirs, _redis_log, _docker_log = _run_backup(tmp_path, info_failure=True)

    assert result.returncode != 0
    assert "Falha ao ler INFO Redis durante BGSAVE" in result.stderr


def test_vps_backup_fails_closed_when_redis_info_fields_are_malformed(tmp_path):
    result, _backup_dirs, _redis_log, _docker_log = _run_backup(tmp_path, malformed_info=True)

    assert result.returncode != 0
    assert "Campo rdb_saves ausente/inválido" in result.stderr


def test_vps_backup_bounds_a_blocked_docker_redis_exec(tmp_path):
    result, _backup_dirs, _redis_log, _docker_log = _run_backup(
        tmp_path, block_redis_docker=True, redis_command_timeout=1
    )

    assert result.returncode != 0
    assert "Timeout em snapshot Redis após 1s" in result.stderr


@pytest.mark.parametrize(
    ("operation", "expected_label"),
    [
        ("postgres_dump", "dump PostgreSQL"),
        ("redis_copy", "cópia do RDB Redis"),
        ("app_data_copy", "cópia dos dados da API"),
        ("app_models_copy", "cópia dos modelos da API"),
    ],
)
def test_vps_backup_bounds_each_blocked_non_redis_docker_operation(
    tmp_path, operation: str, expected_label: str
):
    result, _backup_dirs, _redis_log, _docker_log = _run_backup(
        tmp_path, block_operation=operation, command_timeout=1
    )

    assert result.returncode != 0
    assert f"Timeout em {expected_label} após 1s" in result.stderr
