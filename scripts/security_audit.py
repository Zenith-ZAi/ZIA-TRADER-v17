"""Auditoria de segurança refinada para detecção de injeções e vulnerabilidades."""

from __future__ import annotations

import ast
import os
import re
import sys
from pathlib import Path

SQL_WORD = re.compile(
    r"\b(SELECT|INSERT|UPDATE|DELETE|ALTER|DROP|CREATE|TRUNCATE|MERGE|WITH|"
    r"REPLACE|GRANT|REVOKE|CALL|EXECUTE|EXPLAIN|VACUUM|ANALYZE|COPY|PRAGMA|"
    r"SHOW|DESCRIBE|RENAME)\b",
    re.IGNORECASE,
)
EXEC_METHODS = {"execute", "exec_driver_sql"}
SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "node_modules", "build", "dist"}


def _call_name(node: ast.Call) -> str | None:
    if isinstance(node.func, ast.Name):
        return node.func.id
    if isinstance(node.func, ast.Attribute):
        return node.func.attr
    return None


def _sql_shape(node: ast.AST) -> tuple[str, bool]:
    """Return visible literal SQL and whether its construction is dynamic."""
    if isinstance(node, ast.Call) and _call_name(node) == "text" and node.args:
        return _sql_shape(node.args[0])
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value, False
    if isinstance(node, ast.JoinedStr):
        literals = " ".join(
            item.value for item in node.values
            if isinstance(item, ast.Constant) and isinstance(item.value, str)
        )
        dynamic = any(isinstance(item, ast.FormattedValue) for item in node.values)
        return literals, dynamic
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Mod)):
        left_sql, _ = _sql_shape(node.left)
        right_sql, _ = _sql_shape(node.right)
        try:
            ast.literal_eval(node)
            dynamic = False
        except (ValueError, TypeError, SyntaxError):
            dynamic = True
        return f"{left_sql} {right_sql}", dynamic
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "format":
        template, _ = _sql_shape(node.func.value)
        values = [*node.args, *(keyword.value for keyword in node.keywords)]
        dynamic = any(_is_dynamic_expression(value) for value in values)
        return template, dynamic
    return "", False


def _is_dynamic_expression(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return False
    if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
        return any(_is_dynamic_expression(item) for item in node.elts)
    if isinstance(node, ast.Dict):
        return any(
            _is_dynamic_expression(item)
            for item in [*node.keys, *node.values]
            if item is not None
        )
    if isinstance(node, ast.BinOp):
        try:
            ast.literal_eval(node)
            return False
        except (ValueError, TypeError, SyntaxError):
            return True
    if isinstance(node, ast.JoinedStr):
        return any(isinstance(item, ast.FormattedValue) for item in node.values)
    if isinstance(node, ast.Call) and _call_name(node) == "text" and node.args:
        return _is_dynamic_expression(node.args[0])
    return True


class _AuditVisitor(ast.NodeVisitor):
    """Conservative intra-scope tracker for SQL strings assigned to names."""

    def __init__(
        self,
        findings: list[str],
        dynamic_sql_names: set[str] | None = None,
        sql_text_names: set[str] | None = None,
    ):
        self.findings = findings
        self.dynamic_sql_names = set(dynamic_sql_names or ())
        self.sql_text_names = set(sql_text_names or ())

    @staticmethod
    def _target_names(target: ast.AST) -> set[str]:
        symbol = _AuditVisitor._symbol(target)
        if symbol is not None:
            return {symbol}
        if isinstance(target, (ast.Tuple, ast.List)):
            result: set[str] = set()
            for item in target.elts:
                result.update(_AuditVisitor._target_names(item))
            return result
        return set()

    @staticmethod
    def _symbol(node: ast.AST) -> str | None:
        if isinstance(node, ast.Name):
            return node.id
        if isinstance(node, ast.Attribute):
            parent = _AuditVisitor._symbol(node.value)
            return f"{parent}.{node.attr}" if parent else None
        return None

    def _value_is_dynamic_sql(self, value: ast.AST) -> bool:
        referenced_names = {
            symbol
            for item in ast.walk(value)
            if (symbol := self._symbol(item)) is not None
        }
        if referenced_names & self.dynamic_sql_names:
            return True
        visible_sql, dynamic = _sql_shape(value)
        return dynamic and bool(SQL_WORD.search(visible_sql))

    def _value_is_sql_text(self, value: ast.AST) -> bool:
        referenced_names = {
            symbol
            for item in ast.walk(value)
            if (symbol := self._symbol(item)) is not None
        }
        visible_sql, _ = _sql_shape(value)
        return bool(SQL_WORD.search(visible_sql)) or bool(
            referenced_names & (self.sql_text_names | self.dynamic_sql_names)
        )

    @staticmethod
    def _execution_argument(node: ast.Call) -> ast.AST | None:
        if node.args:
            return node.args[0]
        for keyword in node.keywords:
            if keyword.arg in {"statement", "sql"}:
                return keyword.value
        return None

    def _visit_function_scope(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        # Defaults/decorators execute in the parent scope; the body gets its own
        # assignment set seeded with dynamic module-level SQL names.
        for expression in [*node.decorator_list, *node.args.defaults, *node.args.kw_defaults]:
            if expression is not None:
                self.visit(expression)
        local = _AuditVisitor(self.findings, self.dynamic_sql_names, self.sql_text_names)
        for statement in node.body:
            local.visit(statement)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_scope(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_scope(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        self.visit(node.value)
        dynamic = self._value_is_dynamic_sql(node.value)
        sql_text = self._value_is_sql_text(node.value)
        for target in node.targets:
            for name in self._target_names(target):
                if dynamic:
                    self.dynamic_sql_names.add(name)
                    self.sql_text_names.add(name)
                elif sql_text:
                    self.dynamic_sql_names.discard(name)
                    self.sql_text_names.add(name)
                else:
                    self.dynamic_sql_names.discard(name)
                    self.sql_text_names.discard(name)

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if node.value is not None:
            self.visit(node.value)
            dynamic = self._value_is_dynamic_sql(node.value)
            sql_text = self._value_is_sql_text(node.value)
            for name in self._target_names(node.target):
                if dynamic:
                    self.dynamic_sql_names.add(name)
                    self.sql_text_names.add(name)
                elif sql_text:
                    self.dynamic_sql_names.discard(name)
                    self.sql_text_names.add(name)
                else:
                    self.dynamic_sql_names.discard(name)
                    self.sql_text_names.discard(name)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        dynamic = self._value_is_dynamic_sql(node.value)
        sql_text = self._value_is_sql_text(node.value)
        for name in self._target_names(node.target):
            if dynamic:
                self.dynamic_sql_names.add(name)
                self.sql_text_names.add(name)
            elif sql_text:
                self.dynamic_sql_names.discard(name)
                self.sql_text_names.add(name)
            else:
                self.dynamic_sql_names.discard(name)
                self.sql_text_names.discard(name)

    def visit_AugAssign(self, node: ast.AugAssign) -> None:
        targets = self._target_names(node.target)
        self.visit(node.value)
        if targets & self.sql_text_names and _is_dynamic_expression(node.value):
            self.dynamic_sql_names.update(targets)

    def visit_Call(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in {"eval", "exec"}:
            self.findings.append(f"Uso de {node.func.id}() detectado na linha {node.lineno}")
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "system"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        ):
            self.findings.append(f"Uso de os.system() detectado na linha {node.lineno}")
        argument = self._execution_argument(node) if _call_name(node) in EXEC_METHODS else None
        if argument is not None:
            visible_sql, dynamic = _sql_shape(argument)
            dynamic_name = self._value_is_dynamic_sql(argument)
            if dynamic_name or (dynamic and bool(SQL_WORD.search(visible_sql))):
                self.findings.append(
                    f"SQL dinâmico interpolado em chamada de execução na linha {node.lineno}"
                )
        self.generic_visit(node)


def audit_file(path: Path) -> list[str]:
    findings: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except (OSError, UnicodeError, SyntaxError) as exc:
        return [f"Erro ao analisar AST: {exc}"]
    _AuditVisitor(findings).visit(tree)
    return findings


def main() -> None:
    project_root = Path(__file__).resolve().parents[1]
    findings: list[str] = []
    for root, directories, files in os.walk(project_root):
        directories[:] = [name for name in directories if name not in SKIP_DIRS]
        for filename in files:
            if not filename.endswith(".py") or filename == Path(__file__).name:
                continue
            path = Path(root) / filename
            for finding in audit_file(path):
                findings.append(f"{path.relative_to(project_root)}: {finding}")

    if findings:
        print("Achados AST (triagem estática; não substitui revisão de segurança):")
        for finding in findings:
            print(f" - {finding}")
        sys.exit(1)
    print(
        "Triagem AST heurística: nenhum padrão suportado detectado. "
        "Isto não é auditoria de segurança nem substitui SAST/DAST/revisão humana."
    )

if __name__ == "__main__":
    main()
