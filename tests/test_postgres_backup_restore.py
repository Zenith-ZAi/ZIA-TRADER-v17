from __future__ import annotations

import os
import subprocess
import uuid
from pathlib import Path

import psycopg2
import pytest
from psycopg2 import sql
from sqlalchemy.engine import URL, make_url


pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="TEST_DATABASE_URL não configurada; integração roda no serviço PostgreSQL do CI",
)


def _libpq_url(url: str | URL) -> str:
    parsed = make_url(url)
    return parsed.set(drivername="postgresql").render_as_string(hide_password=False)


def _fingerprints(url: str | URL) -> dict[str, tuple[int, str | None]]:
    result: dict[str, tuple[int, str | None]] = {}
    with psycopg2.connect(_libpq_url(url)) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT tablename FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename"
            )
            tables = [row[0] for row in cursor.fetchall()]
            for table in tables:
                identifier = sql.Identifier("public", table)
                cursor.execute(sql.SQL("SELECT count(*) FROM {}").format(identifier))
                count = cursor.fetchone()[0]
                cursor.execute(
                    sql.SQL(
                        "SELECT md5(COALESCE(string_agg(row_to_json(t)::text, E'\\n' "
                        "ORDER BY row_to_json(t)::text), '')) FROM {} AS t"
                    ).format(identifier)
                )
                checksum = cursor.fetchone()[0]
                result[table] = (count, checksum)
    return result


def test_pg_dump_restore_matches_table_counts_and_checksums(tmp_path: Path):
    source_url = os.environ["TEST_DATABASE_URL"]
    source = make_url(source_url)
    target_name = f"zia_restore_{uuid.uuid4().hex[:12]}"
    admin_url = source.set(drivername="postgresql+psycopg2", database="postgres")
    target_url = source.set(database=target_name)
    created = False
    dump_path = tmp_path / "roundtrip.dump"
    try:
        with psycopg2.connect(_libpq_url(source_url)) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "INSERT INTO market_candles "
                    "(symbol, timeframe, timestamp, open, high, low, close, volume, source, created_at) "
                    "VALUES (%s, %s, %s, 1, 2, 0.5, 1.5, 10, 'backup-test', %s) "
                    "ON CONFLICT (symbol, timeframe, timestamp) DO NOTHING",
                    ("BACKUP-TEST", "1m", "2026-10-04 00:00:00", "2026-10-04 00:00:00"),
                )

        subprocess.run(
            ["pg_dump", "--dbname", _libpq_url(source_url), "--format=custom", "--no-owner", "--no-privileges", "--file", str(dump_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        before = _fingerprints(source_url)

        admin_connection = psycopg2.connect(_libpq_url(admin_url))
        admin_connection.autocommit = True
        try:
            connection = admin_connection
            with connection.cursor() as cursor:
                cursor.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(target_name)))
        finally:
            admin_connection.close()
        created = True
        subprocess.run(
            ["pg_restore", "--dbname", _libpq_url(target_url), "--exit-on-error", "--no-owner", "--no-privileges", str(dump_path)],
            check=True,
            capture_output=True,
            text=True,
        )
        assert _fingerprints(target_url) == before
    finally:
        if created:
            admin_connection = psycopg2.connect(_libpq_url(admin_url))
            admin_connection.autocommit = True
            try:
                connection = admin_connection
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                        (target_name,),
                    )
                    cursor.execute(sql.SQL("DROP DATABASE IF EXISTS {}").format(sql.Identifier(target_name)))
            finally:
                admin_connection.close()
