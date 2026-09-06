"""Gerenciador de Controle de Acesso Baseado em Funções (RBAC).
Define permissões para Admin (Full), Trader (Execução) e Auditor (Leitura).
"""

from __future__ import annotations

from enum import Enum
from typing import List, Set

class Role(Enum):
    ADMIN = "admin"
    TRADER = "trader"
    AUDITOR = "auditor"

class Permission(Enum):
    READ_DATA = "read_data"
    EXECUTE_ORDER = "execute_order"
    MANAGE_CONFIG = "manage_config"
    VIEW_LOGS = "view_logs"

ROLE_PERMISSIONS = {
    Role.ADMIN: {Permission.READ_DATA, Permission.EXECUTE_ORDER, Permission.MANAGE_CONFIG, Permission.VIEW_LOGS},
    Role.TRADER: {Permission.READ_DATA, Permission.EXECUTE_ORDER, Permission.VIEW_LOGS},
    Role.AUDITOR: {Permission.READ_DATA, Permission.VIEW_LOGS},
}

def has_permission(role_name: str, permission: Permission) -> bool:
    try:
        role = Role(role_name.lower())
        return permission in ROLE_PERMISSIONS.get(role, set())
    except ValueError:
        return False
