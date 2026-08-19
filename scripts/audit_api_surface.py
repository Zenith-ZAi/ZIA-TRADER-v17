#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from main import app


def main() -> None:
    routes = []
    for route in app.routes:
        methods = sorted(getattr(route, "methods", set()))
        path = getattr(route, "path", None)
        if path:
            routes.append({"path": path, "methods": methods, "name": getattr(route, "name", "")})
    result = {
        "route_count": len(routes),
        "routes": routes,
        "has_html_route": any(
            route["path"] not in {"/docs", "/redoc", "/openapi.json"}
            and route["methods"] == ["GET"]
            and route["path"] in {"/", "/dashboard", "/menu"}
            for route in routes
        ),
        "control_routes": [route for route in routes if route["path"].startswith(("/trading", "/sniper"))],
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
