"""ASGI compatibility entrypoint; application resources start in lifespan."""

import uvicorn

from api.application import create_app
from config.settings import settings

app = create_app(settings)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=settings.API_PORT)
