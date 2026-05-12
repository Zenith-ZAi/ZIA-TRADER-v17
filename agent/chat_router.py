"""
agent/chat_router.py

Provides a lightweight REST + WebSocket chat interface for ZIA TRADER.
The agent can relay trading commands and status queries to the TradingManager.
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["agent"])


# ---------------------------------------------------------------------------
# Session Manager — keeps per-session context (trading manager ref, etc.)
# ---------------------------------------------------------------------------

class AgentSession:
    def __init__(
        self,
        session_id: str,
        api_key: str,
        trading_manager: Any = None,
        settings: Any = None,
    ):
        self.session_id = session_id
        self.api_key = api_key
        self.trading_manager = trading_manager
        self.settings = settings
        self.history: list[Dict[str, str]] = []

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})


class SessionManager:
    def __init__(self) -> None:
        self._sessions: Dict[str, AgentSession] = {}

    def get_or_create(
        self,
        session_id: str,
        api_key: str = "",
        trading_manager: Any = None,
        settings: Any = None,
    ) -> AgentSession:
        if session_id not in self._sessions:
            self._sessions[session_id] = AgentSession(
                session_id, api_key, trading_manager, settings
            )
        return self._sessions[session_id]

    def get(self, session_id: str) -> Optional[AgentSession]:
        return self._sessions.get(session_id)


session_manager = SessionManager()


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default"


class ChatResponse(BaseModel):
    reply: str
    session_id: str


# ---------------------------------------------------------------------------
# REST endpoint
# ---------------------------------------------------------------------------

@router.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest) -> ChatResponse:
    session = session_manager.get_or_create(req.session_id)
    session.add_message("user", req.message)

    reply = _build_reply(req.message, session)
    session.add_message("assistant", reply)

    return ChatResponse(reply=reply, session_id=req.session_id)


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/{session_id}")
async def websocket_chat(ws: WebSocket, session_id: str) -> None:
    await ws.accept()
    session = session_manager.get_or_create(session_id)
    logger.info("WebSocket connected: %s", session_id)

    try:
        while True:
            data = await ws.receive_text()
            session.add_message("user", data)
            reply = _build_reply(data, session)
            session.add_message("assistant", reply)
            await ws.send_text(reply)
    except WebSocketDisconnect:
        logger.info("WebSocket disconnected: %s", session_id)


# ---------------------------------------------------------------------------
# Simple rule-based reply (placeholder for real LLM integration)
# ---------------------------------------------------------------------------

def _build_reply(message: str, session: AgentSession) -> str:
    msg = message.lower().strip()

    if any(k in msg for k in ("status", "estado", "como está")):
        tm = session.trading_manager
        if tm:
            engine = getattr(tm, "trading_engine", None)
            running = getattr(engine, "is_running", False) if engine else False
            return f"Motor de trading: {'ativo' if running else 'inativo'}."
        return "TradingManager não conectado à sessão."

    if any(k in msg for k in ("ajuda", "help", "comandos")):
        return (
            "Comandos disponíveis:\n"
            "• status — estado do motor de trading\n"
            "• ajuda  — mostra esta mensagem\n"
            "Envie qualquer outra mensagem e tentarei ajudar."
        )

    return (
        f"Recebi sua mensagem: '{message}'. "
        "Use 'status' para verificar o motor ou 'ajuda' para listar comandos."
    )
