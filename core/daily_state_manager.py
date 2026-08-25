"""Controle diário de vitórias/derrotas para estratégia supervisionada."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone


@dataclass
class DailyScore:
    day: date
    wins: int = 0
    losses: int = 0


class DailyStateManager:
    """Mantém a regra 5x2 sem permitir entrada neutra ou após 2 perdas."""

    def __init__(self, max_wins: int = 5, max_losses: int = 2):
        self.max_wins = max(1, int(max_wins))
        self.max_losses = max(1, int(max_losses))
        self._score = DailyScore(datetime.now(timezone.utc).date())

    def reset_daily_counters(self, now: datetime | None = None) -> DailyScore:
        current_day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
        self._score = DailyScore(current_day)
        return self._score

    def _ensure_current_day(self, now: datetime | None = None) -> DailyScore:
        current_day = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
        if current_day != self._score.day:
            self.reset_daily_counters(now)
        return self._score

    def check_entry(self, action: str, now: datetime | None = None) -> dict[str, object]:
        score = self._ensure_current_day(now)
        normalized = str(action or "hold").lower()
        reasons: list[str] = []
        if normalized not in {"buy", "sell"}:
            reasons.append("tendência neutra: nenhuma entrada autorizada")
        if score.losses >= self.max_losses:
            reasons.append(f"limite diário de {self.max_losses} perdas atingido")
        if score.wins >= self.max_wins:
            reasons.append(f"meta diária de {self.max_wins} vitórias atingida")
        return {
            "allowed": not reasons,
            "action": normalized,
            "wins": score.wins,
            "losses": score.losses,
            "max_wins": self.max_wins,
            "max_losses": self.max_losses,
            "reasons": reasons or ["placar diário permite avaliação"],
        }

    def record_trade(self, won: bool, now: datetime | None = None) -> dict[str, object]:
        score = self._ensure_current_day(now)
        if won:
            score.wins += 1
        else:
            score.losses += 1
        return self.status(now)

    def status(self, now: datetime | None = None) -> dict[str, object]:
        score = self._ensure_current_day(now)
        return {
            "day": score.day.isoformat(),
            "wins": score.wins,
            "losses": score.losses,
            "max_wins": self.max_wins,
            "max_losses": self.max_losses,
            "entry_blocked": score.wins >= self.max_wins or score.losses >= self.max_losses,
        }
