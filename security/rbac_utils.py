from typing import List

def has_permission(user_roles: List[str], required_roles: List[str]) -> bool:
    """Verifica se o usuário possui alguma das roles necessárias."""
    return any(role in user_roles for role in required_roles)

def is_admin(user_roles: List[str]) -> bool:
    """Verifica se o usuário é um administrador."""
    return "admin" in user_roles

def is_trader(user_roles: List[str]) -> bool:
    """Verifica se o usuário é um trader."""
    return "trader" in user_roles
