"""Inicializa o schema aditivo do ZIA-TRADER-v17.

Não apaga dados nem executa migrações destrutivas. Mudanças futuras devem ser
versionadas por uma ferramenta de migração antes de aplicar em produção.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from database_manager import DatabaseManager


def main() -> None:
    database_url = os.getenv("DATABASE_URL", "sqlite:///./data/zia_trader.db")
    manager = DatabaseManager(database_url)
    manager.create_tables()
    print(json.dumps({
        "status": "initialized",
        "database_endpoint": database_url.rsplit("@", 1)[-1],
        "destructive": False,
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
