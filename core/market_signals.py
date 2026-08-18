"""Leitura determinística de mercado e classificação de qualidade do sinal."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Dict, List

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class MarketSignal:
    """Resultado explicável de uma leitura de mercado."""

    action: str
    candidate_action: str
    confidence: float
    score: float
    status: str
    regime: str
    volatility: float
    indicators: Dict[str, float]
    reasons: List[str]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _clamp(value: float, lower: float = -1.0, upper: float = 1.0) -> float:
    return float(max(lower, min(upper, value)))


def _numeric_series(data: pd.DataFrame, name: str) -> pd.Series | None:
    if name not in data.columns:
        return None
    series = pd.to_numeric(data[name], errors="coerce").replace([np.inf, -np.inf], np.nan)
    return series.dropna()


def calculate_market_signal(
    data: pd.DataFrame,
    news_sentiment: float = 0.0,
    trend_score: float = 0.0,
    min_confidence: float = 0.70,
    max_volatility: float = 0.08,
) -> MarketSignal:
    """Calcula um sinal com motivos e indicadores, sem executar ordens.

    O método deliberadamente retorna ``hold`` quando há pouca história,
    baixa confluência ou volatilidade extrema. Isso transforma sinais ruins
    em rejeições explícitas, em vez de permitir que um modelo sem evidência
    opere por padrão.
    """

    if not isinstance(data, pd.DataFrame) or len(data) < 35:
        return MarketSignal(
            action="hold",
            candidate_action="hold",
            confidence=0.0,
            score=0.0,
            status="bad_data",
            regime="unknown",
            volatility=0.0,
            indicators={},
            reasons=["histórico insuficiente: são necessárias pelo menos 35 barras"],
        )

    close = _numeric_series(data, "close")
    if close is None or len(close) < 35 or close.iloc[-1] <= 0:
        return MarketSignal(
            action="hold",
            candidate_action="hold",
            confidence=0.0,
            score=0.0,
            status="bad_data",
            regime="unknown",
            volatility=0.0,
            indicators={},
            reasons=["preço de fechamento ausente ou inválido"],
        )

    close = close.reindex(data.index).ffill().dropna()
    returns = close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
    if len(returns) < 30:
        return MarketSignal(
            action="hold",
            candidate_action="hold",
            confidence=0.0,
            score=0.0,
            status="bad_data",
            regime="unknown",
            volatility=0.0,
            indicators={},
            reasons=["retornos insuficientes para medir volatilidade"],
        )

    ema_fast = close.ewm(span=12, adjust=False).mean()
    ema_slow = close.ewm(span=26, adjust=False).mean()
    macd = ema_fast - ema_slow
    macd_signal = macd.ewm(span=9, adjust=False).mean()

    delta = close.diff()
    gain = delta.clip(lower=0).rolling(14, min_periods=14).mean()
    loss = (-delta.clip(upper=0)).rolling(14, min_periods=14).mean()
    relative_strength = gain / loss.replace(0, np.nan)
    rsi = (100 - (100 / (1 + relative_strength))).fillna(50.0)

    high = _numeric_series(data, "high")
    low = _numeric_series(data, "low")
    if high is not None and low is not None:
        high = high.reindex(close.index).ffill()
        low = low.reindex(close.index).ffill()
        previous_close = close.shift(1)
        true_range = pd.concat(
            [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
            axis=1,
        ).max(axis=1)
        atr = true_range.rolling(14, min_periods=14).mean()
        volatility = float((atr.iloc[-1] / close.iloc[-1]) if close.iloc[-1] else 0.0)
    else:
        volatility = float(returns.rolling(14, min_periods=14).std().iloc[-1] * np.sqrt(14))
    volatility = max(0.0, volatility if np.isfinite(volatility) else 0.0)

    trend_component = _clamp((ema_fast.iloc[-1] / ema_slow.iloc[-1] - 1.0) * 40)
    momentum_component = _clamp(float(returns.tail(5).sum()) * 20)
    rsi_component = _clamp((float(rsi.iloc[-1]) - 50.0) / 20.0)
    macd_scale = max(float(close.iloc[-1]) * max(volatility, 0.001), 1e-9)
    macd_component = _clamp(float((macd.iloc[-1] - macd_signal.iloc[-1]) / macd_scale) * 3)

    volume_component = 0.0
    volume = _numeric_series(data, "volume")
    if volume is not None and len(volume) >= 20:
        volume = volume.reindex(data.index).ffill().dropna()
        average_volume = float(volume.tail(20).mean())
        if average_volume > 0:
            volume_ratio = float(volume.iloc[-1] / average_volume)
            volume_component = _clamp(np.sign(momentum_component) * (volume_ratio - 1.0))

    news_component = _clamp(float(news_sentiment))
    trend_component_external = _clamp(float(trend_score))
    components = {
        "trend": trend_component,
        "momentum": momentum_component,
        "rsi": rsi_component,
        "macd": macd_component,
        "volume": volume_component,
        "news": news_component,
        "external_trend": trend_component_external,
    }
    score = (
        0.25 * trend_component
        + 0.20 * momentum_component
        + 0.15 * rsi_component
        + 0.20 * macd_component
        + 0.10 * volume_component
        + 0.05 * news_component
        + 0.05 * trend_component_external
    )
    score = _clamp(score)
    confidence = 0.50 + (0.50 * abs(score))
    candidate_action = "buy" if score >= 0.15 else "sell" if score <= -0.15 else "hold"

    positive = sum(value >= 0.20 for value in components.values())
    negative = sum(value <= -0.20 for value in components.values())
    contradiction = positive >= 2 and negative >= 2
    if abs(score) < 0.15:
        regime = "lateral"
    elif trend_component > 0.20:
        regime = "alta"
    elif trend_component < -0.20:
        regime = "baixa"
    else:
        regime = "transição"

    reasons: List[str] = []
    if candidate_action == "buy":
        reasons.append("confluência compradora acima do limiar mínimo")
    elif candidate_action == "sell":
        reasons.append("confluência vendedora abaixo do limiar mínimo")
    else:
        reasons.append("componentes sem direção suficientemente convergente")
    if contradiction:
        reasons.append("indicadores relevantes estão contraditórios")
    if volatility > max_volatility:
        reasons.append("volatilidade acima do limite de entrada")
    if confidence < min_confidence:
        reasons.append("confiança abaixo do limiar operacional")
    if volume_component == 0.0:
        reasons.append("volume sem confirmação suficiente")

    good_signal = (
        candidate_action != "hold"
        and confidence >= min_confidence
        and not contradiction
        and volatility <= max_volatility
    )
    action = candidate_action if good_signal else "hold"
    status = "good" if good_signal else "rejected"
    return MarketSignal(
        action=action,
        candidate_action=candidate_action,
        confidence=float(confidence),
        score=float(score),
        status=status,
        regime=regime,
        volatility=float(volatility),
        indicators={"rsi": float(rsi.iloc[-1]), "atr_pct": float(volatility)},
        reasons=reasons,
    )


class MarketSignalCache:
    """Cache causal de indicadores para backtests walk-forward eficientes.

    Todas as séries são calculadas apenas com operações causais. Ao consultar
    ``at(position)``, nenhum valor posterior à posição é usado para o sinal.
    """

    def __init__(self, data: pd.DataFrame):
        self.data = data
        close = _numeric_series(data, "close")
        self.close = close.reindex(data.index).ffill().dropna() if close is not None else pd.Series(dtype=float)
        self.returns = self.close.pct_change().replace([np.inf, -np.inf], np.nan).dropna()
        self.ema_fast = self.close.ewm(span=12, adjust=False).mean()
        self.ema_slow = self.close.ewm(span=26, adjust=False).mean()
        self.macd = self.ema_fast - self.ema_slow
        self.macd_signal = self.macd.ewm(span=9, adjust=False).mean()

        delta = self.close.diff()
        gain = delta.clip(lower=0).rolling(14, min_periods=14).mean()
        loss = (-delta.clip(upper=0)).rolling(14, min_periods=14).mean()
        relative_strength = gain / loss.replace(0, np.nan)
        self.rsi = (100 - (100 / (1 + relative_strength))).fillna(50.0)

        high = _numeric_series(data, "high")
        low = _numeric_series(data, "low")
        self.high = high.reindex(self.close.index).ffill() if high is not None else None
        self.low = low.reindex(self.close.index).ffill() if low is not None else None
        if self.high is not None and self.low is not None:
            previous_close = self.close.shift(1)
            true_range = pd.concat(
                [self.high - self.low, (self.high - previous_close).abs(), (self.low - previous_close).abs()],
                axis=1,
            ).max(axis=1)
            self.volatility = (true_range.rolling(14, min_periods=14).mean() / self.close).replace([np.inf, -np.inf], np.nan)
        else:
            self.volatility = self.returns.rolling(14, min_periods=14).std() * np.sqrt(14)

        volume = _numeric_series(data, "volume")
        self.volume = volume.reindex(self.close.index).ffill().dropna() if volume is not None else None

    def at(
        self,
        position: int,
        news_sentiment: float = 0.0,
        trend_score: float = 0.0,
        min_confidence: float = 0.70,
        max_volatility: float = 0.08,
    ) -> MarketSignal:
        """Retorna o sinal na posição indicada usando somente dados até ela."""
        if position < 0 or position >= len(self.close) or len(self.close) < 35:
            return MarketSignal("hold", "hold", 0.0, 0.0, "bad_data", "unknown", 0.0, {}, ["histórico insuficiente: são necessárias pelo menos 35 barras"])

        close = self.close.iloc[: position + 1]
        returns = self.returns[self.returns.index <= close.index[-1]]
        if len(returns) < 30 or close.iloc[-1] <= 0:
            return MarketSignal("hold", "hold", 0.0, 0.0, "bad_data", "unknown", 0.0, {}, ["retornos insuficientes para medir volatilidade"])

        volatility_value = float(self.volatility.loc[close.index[-1]]) if close.index[-1] in self.volatility.index else 0.0
        volatility = max(0.0, volatility_value if np.isfinite(volatility_value) else 0.0)
        trend_component = _clamp((self.ema_fast.iloc[position] / self.ema_slow.iloc[position] - 1.0) * 40)
        momentum_component = _clamp(float(returns.tail(5).sum()) * 20)
        rsi_component = _clamp((float(self.rsi.iloc[position]) - 50.0) / 20.0)
        macd_scale = max(float(close.iloc[-1]) * max(volatility, 0.001), 1e-9)
        macd_component = _clamp(float((self.macd.iloc[position] - self.macd_signal.iloc[position]) / macd_scale) * 3)

        volume_component = 0.0
        if self.volume is not None and len(self.volume) >= 20 and close.index[-1] in self.volume.index:
            volume_until_now = self.volume[self.volume.index <= close.index[-1]]
            average_volume = float(volume_until_now.tail(20).mean())
            if average_volume > 0:
                volume_ratio = float(volume_until_now.iloc[-1] / average_volume)
                volume_component = _clamp(np.sign(momentum_component) * (volume_ratio - 1.0))

        components = {
            "trend": trend_component,
            "momentum": momentum_component,
            "rsi": rsi_component,
            "macd": macd_component,
            "volume": volume_component,
            "news": _clamp(float(news_sentiment)),
            "external_trend": _clamp(float(trend_score)),
        }
        score = _clamp(
            0.25 * trend_component
            + 0.20 * momentum_component
            + 0.15 * rsi_component
            + 0.20 * macd_component
            + 0.10 * volume_component
            + 0.05 * components["news"]
            + 0.05 * components["external_trend"]
        )
        confidence = 0.50 + (0.50 * abs(score))
        candidate_action = "buy" if score >= 0.15 else "sell" if score <= -0.15 else "hold"
        positive = sum(value >= 0.20 for value in components.values())
        negative = sum(value <= -0.20 for value in components.values())
        contradiction = positive >= 2 and negative >= 2
        regime = "lateral" if abs(score) < 0.15 else "alta" if trend_component > 0.20 else "baixa" if trend_component < -0.20 else "transição"

        reasons: List[str] = []
        if candidate_action == "buy":
            reasons.append("confluência compradora acima do limiar mínimo")
        elif candidate_action == "sell":
            reasons.append("confluência vendedora abaixo do limiar mínimo")
        else:
            reasons.append("componentes sem direção suficientemente convergente")
        if contradiction:
            reasons.append("indicadores relevantes estão contraditórios")
        if volatility > max_volatility:
            reasons.append("volatilidade acima do limite de entrada")
        if confidence < min_confidence:
            reasons.append("confiança abaixo do limiar operacional")
        if volume_component == 0.0:
            reasons.append("volume sem confirmação suficiente")

        good_signal = candidate_action != "hold" and confidence >= min_confidence and not contradiction and volatility <= max_volatility
        return MarketSignal(
            action=candidate_action if good_signal else "hold",
            candidate_action=candidate_action,
            confidence=float(confidence),
            score=float(score),
            status="good" if good_signal else "rejected",
            regime=regime,
            volatility=float(volatility),
            indicators={"rsi": float(self.rsi.iloc[position]), "atr_pct": float(volatility)},
            reasons=reasons,
        )
