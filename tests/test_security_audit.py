from __future__ import annotations

from pathlib import Path

from scripts.security_audit import audit_file


def audit_source(tmp_path: Path, source: str) -> list[str]:
    path = tmp_path / "sample.py"
    path.write_text(source, encoding="utf-8")
    return audit_file(path)


def test_parameterized_sql_is_not_reported_as_injection(tmp_path):
    findings = audit_source(
        tmp_path,
        'from sqlalchemy import text\n'
        'connection.execute(text("SELECT * FROM users WHERE id = :user_id"), {"user_id": user_id})\n',
    )
    assert findings == []


def test_dynamic_sql_interpolation_is_detected(tmp_path):
    source = (
        'connection.execute(text(f"SELECT * FROM users WHERE name = \'{name}\'"))\n'
        'connection.exec_driver_sql("UPDATE users SET name = \'%s\'" % name)\n'
        'connection.execute(text("DELETE FROM users WHERE id = {}".format(user_id)))\n'
        'def unsafe_lookup(user_id):\n'
        '    query = f"SELECT * FROM users WHERE id = {user_id}"\n'
        '    query_alias = query\n'
        '    connection.execute(query_alias)\n'
        '    query_with_limit = query_alias + " LIMIT 1"\n'
        '    connection.execute(query_with_limit)\n'
        '    self.sql = f"DELETE FROM users WHERE id = {user_id}"\n'
        '    connection.execute(self.sql)\n'
        '    connection.execute(statement=query_alias)\n'
        '    self.sql = "SELECT * FROM users WHERE "\n'
        '    self.sql += "id = " + user_id\n'
        '    connection.execute(self.sql)\n'
        '    connection.execute("TRUNCATE " + table_name)\n'
        '    connection.execute("MERGE INTO " + table_name)\n'
        '    cte = "WITH " + cte_clause\n'
        '    connection.execute(cte)\n'
    )
    findings = audit_source(tmp_path, source)
    assert len([item for item in findings if item.startswith("SQL dinâmico")]) == 11


def test_dangerous_dynamic_execution_primitives_remain_detected(tmp_path):
    findings = audit_source(
        tmp_path,
        "eval(user_input)\nexec(source)\nos.system(command)\n",
    )
    assert any("eval()" in item for item in findings)
    assert any("exec()" in item for item in findings)
    assert any("os.system()" in item for item in findings)
