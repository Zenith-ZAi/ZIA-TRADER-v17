"""Client-scope SQL constraints/authorization on PostgreSQL; this is not RLS."""
import os
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.client_scope import ScopeResolutionError, resolve_client_scope
from database import BrokerAccountV1
from tests.test_client_scope import _caller, _new_account, _new_identity


def test_postgres_client_scope_constraints_and_cross_tenant_resolution():
    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL required for real PostgreSQL constraints")
    engine = create_engine(url)
    if engine.dialect.name != "postgresql":
        engine.dispose()
        pytest.fail("client-scope integration requires PostgreSQL")
    try:
        with engine.connect() as connection:
            outer = connection.begin()
            session = Session(bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False)
            try:
                suffix = str(uuid4())
                tenant_a, principal_a = _new_identity(session, tenant_name=f"pg-scope-a-{suffix}", issuer="test-ci", subject=f"a-{suffix}", role="trader")
                tenant_b, _ = _new_identity(session, tenant_name=f"pg-scope-b-{suffix}", issuer="test-ci", subject=f"b-{suffix}", role="trader")
                account = _new_account(session, tenant_a.id, venue="binance", environment="testnet", account_ref=f"ci-account-{suffix}")
                scope = resolve_client_scope(session, caller=_caller(principal_a), tenant_id=tenant_a.id, account_id=account.id, required_role="trader")
                assert scope.tenant_id == tenant_a.id and scope.environment == "testnet"
                with pytest.raises(ScopeResolutionError):
                    resolve_client_scope(session, caller=_caller(principal_a), tenant_id=tenant_b.id, account_id=account.id, required_role="viewer")
                with pytest.raises(IntegrityError):
                    with session.begin_nested():
                        _new_account(session, tenant_b.id, venue="binance", environment="testnet", account_ref=f"ci-account-{suffix}")
                with pytest.raises(IntegrityError):
                    with session.begin_nested():
                        session.add(BrokerAccountV1(tenant_id=str(uuid4()), venue="binance", environment="paper", account_ref=f"ci-orphan-{suffix}"))
                        session.flush()
                with pytest.raises(IntegrityError):
                    with session.begin_nested():
                        _new_account(session, tenant_a.id, venue="binance", environment="unsupported", account_ref=f"ci-invalid-{suffix}")
                # A simulated account and a testnet account are distinct identities.
                other = _new_account(session, tenant_a.id, venue="binance", environment="paper", account_ref=f"ci-account-{suffix}")
                assert other.id != account.id
                session.commit()  # Releases only its savepoint, never the outer fixture.
            finally:
                session.close()
                outer.rollback()
    finally:
        engine.dispose()
