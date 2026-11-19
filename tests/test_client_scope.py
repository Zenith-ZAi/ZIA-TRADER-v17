from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from core.client_scope import (
    ClientScope,
    ScopeResolutionError,
    TrustedCaller,
    resolve_client_scope,
    trusted_authenticated_caller,
)
from database import (
    Base,
    BrokerAccountV1,
    PrincipalV1,
    TenantMembershipV1,
    TenantV1,
)


ROOT = Path(__file__).resolve().parents[1]
_SCOPE_TABLE_NAMES = (
    "tenant_v1",
    "principal_v1",
    "tenant_membership_v1",
    "broker_account_v1",
)
_SCOPE_TABLES = tuple(Base.metadata.tables[name] for name in _SCOPE_TABLE_NAMES)


def _sqlite_engine(url: str = "sqlite:///:memory:"):
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    for table in _SCOPE_TABLES:
        table.create(engine, checkfirst=True)
    return engine


def _new_identity(session, *, tenant_name: str, issuer: str, subject: str, role: str = "viewer"):
    tenant = TenantV1(name=tenant_name)
    principal = PrincipalV1(issuer=issuer, subject=subject)
    session.add_all([tenant, principal])
    session.flush()
    session.add(TenantMembershipV1(tenant_id=tenant.id, principal_id=principal.id, role=role))
    session.flush()
    return tenant, principal


def _new_account(session, tenant_id: str, *, venue: str, environment: str, account_ref: str, status: str = "active"):
    account = BrokerAccountV1(
        tenant_id=tenant_id,
        venue=venue,
        environment=environment,
        account_ref=account_ref,
        status=status,
    )
    session.add(account)
    session.flush()
    return account


def _caller(principal: PrincipalV1) -> TrustedCaller:
    return trusted_authenticated_caller(issuer=principal.issuer, subject=principal.subject)


@pytest.fixture
def session():
    engine = _sqlite_engine()
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as db:
        yield db
    engine.dispose()


def test_scope_resolves_only_explicit_active_tenant_account_and_role(session):
    tenant_a, viewer = _new_identity(
        session, tenant_name="tenant-a", issuer="issuer-a", subject="user-viewer", role="viewer"
    )
    tenant_b, trader = _new_identity(
        session, tenant_name="tenant-b", issuer="issuer-b", subject="user-trader", role="trader"
    )
    account_a = _new_account(
        session, tenant_a.id, venue="broker-a", environment="paper", account_ref="opaque-a"
    )
    account_b = _new_account(
        session, tenant_b.id, venue="broker-a", environment="testnet", account_ref="opaque-b"
    )
    session.commit()

    scope = resolve_client_scope(
        session,
        caller=_caller(viewer),
        tenant_id=tenant_a.id,
        account_id=account_a.id,
        required_role="viewer",
    )
    assert isinstance(scope, ClientScope)
    assert scope == ClientScope(
        tenant_id=tenant_a.id,
        principal_id=viewer.id,
        account_id=account_a.id,
        venue="broker-a",
        environment="paper",
        role="viewer",
    )
    with pytest.raises(ScopeResolutionError, match="^client scope unavailable$") as cross_tenant:
        resolve_client_scope(
            session,
            caller=_caller(viewer),
            tenant_id=tenant_b.id,
            account_id=account_b.id,
            required_role="viewer",
        )
    assert tenant_b.id not in str(cross_tenant.value)
    assert account_b.id not in str(cross_tenant.value)

    with pytest.raises(ScopeResolutionError, match="^client scope unavailable$"):
        resolve_client_scope(
            session,
            caller=_caller(viewer),
            tenant_id=tenant_a.id,
            account_id=account_a.id,
            required_role="trader",
        )
    trader_scope = resolve_client_scope(
        session,
        caller=_caller(trader),
        tenant_id=tenant_b.id,
        account_id=account_b.id,
        required_role="viewer",
    )
    assert trader_scope.role == "trader"
    assert trader_scope.environment == "testnet"


def test_scope_rejects_inactive_unknown_and_unverified_inputs(session):
    tenant, principal = _new_identity(
        session, tenant_name="tenant-inactive", issuer="issuer", subject="subject"
    )
    account = _new_account(
        session, tenant.id, venue="broker", environment="demo", account_ref="opaque"
    )
    session.commit()

    fake_payload = {"iss": principal.issuer, "sub": principal.subject}
    with pytest.raises(ScopeResolutionError, match="^client scope unavailable$"):
        resolve_client_scope(
            session,
            caller=fake_payload,  # type: ignore[arg-type]
            tenant_id=tenant.id,
            account_id=account.id,
            required_role="viewer",
        )
    with pytest.raises(ScopeResolutionError, match="^client scope unavailable$"):
        resolve_client_scope(
            session,
            caller=trusted_authenticated_caller(issuer="issuer", subject="unknown"),
            tenant_id=tenant.id,
            account_id=account.id,
            required_role="viewer",
        )
    with pytest.raises(ScopeResolutionError, match="^client scope unavailable$"):
        resolve_client_scope(
            session,
            caller=_caller(principal),
            tenant_id=tenant.id,
            account_id=str(uuid4()),
            required_role="viewer",
        )

    membership = session.get(TenantMembershipV1, (tenant.id, principal.id))
    assert membership is not None
    membership.status = "inactive"
    session.commit()
    with pytest.raises(ScopeResolutionError, match="^client scope unavailable$"):
        resolve_client_scope(
            session,
            caller=_caller(principal),
            tenant_id=tenant.id,
            account_id=account.id,
            required_role="viewer",
        )

    membership.status = "active"
    account.status = "inactive"
    session.commit()
    with pytest.raises(ScopeResolutionError, match="^client scope unavailable$"):
        resolve_client_scope(
            session,
            caller=_caller(principal),
            tenant_id=tenant.id,
            account_id=account.id,
            required_role="viewer",
        )


def test_scope_is_frozen_and_trusted_boundary_is_not_a_process_security_boundary(session):
    tenant, principal = _new_identity(
        session, tenant_name="tenant-admin", issuer="issuer-admin", subject="admin", role="admin"
    )
    account = _new_account(
        session, tenant.id, venue="broker", environment="live", account_ref="opaque-live"
    )
    session.commit()
    scope = resolve_client_scope(
        session,
        caller=_caller(principal),
        tenant_id=tenant.id,
        account_id=account.id,
        required_role="admin",
    )
    with pytest.raises((AttributeError, TypeError)):
        scope.tenant_id = str(uuid4())  # type: ignore[misc]
    assert scope.role == "admin"
    # A TrustedCaller is an explicit hand-off type, not proof that this Python
    # process itself is hostile-code resistant.
    assert isinstance(_caller(principal), TrustedCaller)


def test_schema_constraints_cover_fk_environment_uuid_and_opaque_reference(session):
    tenant_a, principal = _new_identity(
        session, tenant_name="tenant-one", issuer="issuer-one", subject="one"
    )
    tenant_b, _ = _new_identity(session, tenant_name="tenant-two", issuer="issuer-two", subject="two")
    first = _new_account(
        session, tenant_a.id, venue="venue", environment="paper", account_ref="same-ref"
    )
    session.commit()

    duplicate = BrokerAccountV1(
        tenant_id=tenant_b.id,
        venue="venue",
        environment="paper",
        account_ref="same-ref",
    )
    session.add(duplicate)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    invalid_environment = BrokerAccountV1(
        tenant_id=tenant_a.id,
        venue="venue",
        environment="sandbox",
        account_ref="other-ref",
    )
    session.add(invalid_environment)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    orphan_account = BrokerAccountV1(
        tenant_id=str(uuid4()),
        venue="venue",
        environment="paper",
        account_ref="orphan-ref",
    )
    session.add(orphan_account)
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()

    assert {column["name"] for column in inspect(session.bind).get_columns("broker_account_v1")} >= {
        "id",
        "tenant_id",
        "venue",
        "environment",
        "account_ref",
        "status",
    }
    assert not {
        "password",
        "password_hash",
        "api_key",
        "secret",
        "secret_key",
        "token",
    }.intersection(column.name for column in BrokerAccountV1.__table__.columns)
    assert first.id
    assert principal.id


def test_client_scope_migration_is_additive_and_downgrade_requires_empty_tables(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'scope-migration.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENABLE_TIMESCALEDB_HYPERTABLES", "false")
    cfg = Config(str(ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")

    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == "c3f1e2a9b7d4"
            assert set(_SCOPE_TABLE_NAMES).issubset(set(inspect(engine).get_table_names()))
            assert {fk["referred_table"] for fk in inspect(engine).get_foreign_keys("broker_account_v1")} == {
                "tenant_v1"
            }
        with pytest.raises(RuntimeError, match="client-scope tables contain data"):
            with engine.begin() as connection:
                connection.execute(
                    text(
                        "INSERT INTO tenant_v1 (id, name, status, created_at) "
                        "VALUES (:id, 'persisted', 'active', CURRENT_TIMESTAMP)"
                    ),
                    {"id": str(uuid4())},
                )
            command.downgrade(cfg, "a5c74e8d2b91")
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM tenant_v1"))
        command.downgrade(cfg, "a5c74e8d2b91")
        with engine.connect() as connection:
            assert not set(_SCOPE_TABLE_NAMES).intersection(inspect(engine).get_table_names())
    finally:
        engine.dispose()


def test_client_scope_migration_refuses_preexisting_new_table(tmp_path, monkeypatch):
    database_url = f"sqlite:///{tmp_path / 'scope-preexisting.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ENABLE_TIMESCALEDB_HYPERTABLES", "false")
    cfg = Config(str(ROOT / "alembic.ini"))
    command.upgrade(cfg, "a5c74e8d2b91")
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(text("CREATE TABLE tenant_v1 (id TEXT PRIMARY KEY)"))
        with pytest.raises(RuntimeError, match="already exist before their Alembic revision"):
            command.upgrade(cfg, "head")
        with engine.connect() as connection:
            assert [row[1] for row in connection.exec_driver_sql("PRAGMA table_info(tenant_v1)")] == ["id"]
            assert not set(_SCOPE_TABLE_NAMES[1:]).intersection(inspect(engine).get_table_names())
    finally:
        engine.dispose()


@pytest.mark.parametrize("issuer,subject", [(" issuer", "alice"), ("issuer", "alice ")])
def test_trusted_identity_rejects_whitespace_aliases_instead_of_collapsing_principals(issuer, subject):
    with pytest.raises(ValueError, match="canonical"):
        trusted_authenticated_caller(issuer=issuer, subject=subject)
