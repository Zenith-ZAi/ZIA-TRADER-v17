from sqlalchemy.orm import Session
import hashlib
import math

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
from typing import List, Optional, Dict

from database import Base, AccountState, Position, RuntimePositionState, DailyPNL, WeeklyPNL, MonthlyPNL, Drawdown, OrderHistory, ExecutionHistory, Trade, WhaleActivity, NewsArticle, TrendSnapshot, AIObservation, MarketPattern, SystemLog, OrderIntent, ReconciliationSnapshot, ProtectionOrder, KillSwitchEvent, BacktestRun, DecisionSnapshot, MarketType, OrderStatus, utc_now

class DatabaseManager:
    def __init__(self, database_url: str):
        engine_options = {"pool_pre_ping": True, "pool_recycle": 1800}
        if "sqlite" in database_url:
            engine_options["connect_args"] = {"check_same_thread": False}
        self.engine = create_engine(database_url, **engine_options)
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)

    def create_tables(self):
        Base.metadata.create_all(self.engine)

    def get_db(self):
        db = self.SessionLocal()
        try:
            yield db
        finally:
            db.close()

    # AccountState Operations
    def create_or_update_account_state(self, account_id: str, balance: float, initial_capital: float) -> AccountState:
        db = self.SessionLocal()
        account_state = db.query(AccountState).filter(AccountState.account_id == account_id).first()
        if account_state:
            account_state.balance = balance
            account_state.initial_capital = initial_capital
        else:
            account_state = AccountState(account_id=account_id, balance=balance, initial_capital=initial_capital)
            db.add(account_state)
        db.commit()
        db.refresh(account_state)
        db.close()
        return account_state

    def get_account_state(self, account_id: str) -> Optional[AccountState]:
        db = self.SessionLocal()
        account_state = db.query(AccountState).filter(AccountState.account_id == account_id).first()
        db.close()
        return account_state

    # Position Operations
    def create_position(self, account_id: str, symbol: str, market_type: MarketType, quantity: float, entry_price: float, current_price: float) -> Position:
        db = self.SessionLocal()
        position = Position(account_id=account_id, symbol=symbol, market_type=market_type, quantity=quantity, entry_price=entry_price, current_price=current_price)
        db.add(position)
        db.commit()
        db.refresh(position)
        db.close()
        return position

    def update_position(self, position_id: int, current_price: float, unrealized_pnl: float, realized_pnl: float, is_open: bool, close_time: Optional[datetime] = None) -> Optional[Position]:
        db = self.SessionLocal()
        position = db.query(Position).filter(Position.id == position_id).first()
        if position:
            position.current_price = current_price
            position.unrealized_pnl = unrealized_pnl
            position.realized_pnl = realized_pnl
            position.is_open = is_open
            position.close_time = close_time
            db.commit()
            db.refresh(position)
        db.close()
        return position

    def get_open_positions(self, account_id: str) -> List[Position]:
        db = self.SessionLocal()
        positions = db.query(Position).filter(Position.account_id == account_id, Position.is_open == True).all()
        db.close()
        return positions

    def close_position(self, account_id: str, symbol: str) -> Optional[Position]:
        db = self.SessionLocal()
        position = db.query(Position).filter(Position.account_id == account_id, Position.symbol == symbol, Position.is_open == True).first()
        if position:
            position.is_open = False
            position.close_time = utc_now()
            db.commit()
            db.refresh(position)
        db.close()
        return position

    # Runtime position state operations
    def upsert_runtime_position(self, account_id: str, state: Dict) -> RuntimePositionState:
        db = self.SessionLocal()
        position = db.query(RuntimePositionState).filter(
            RuntimePositionState.account_id == account_id,
            RuntimePositionState.symbol == state["symbol"],
        ).first()
        if position is None:
            position = RuntimePositionState(account_id=account_id, symbol=state["symbol"])
            db.add(position)
        for field in ("action", "quantity", "entry_price", "stop_loss", "take_profit", "breakeven_trigger", "order_id"):
            if field in state:
                setattr(position, field, state[field])
        position.is_open = True
        db.commit()
        db.refresh(position)
        db.close()
        return position

    def get_open_runtime_positions(self, account_id: str) -> List[RuntimePositionState]:
        db = self.SessionLocal()
        rows = db.query(RuntimePositionState).filter(
            RuntimePositionState.account_id == account_id,
            RuntimePositionState.is_open.is_(True),
        ).all()
        db.close()
        return rows

    def close_runtime_position(self, account_id: str, symbol: str) -> Optional[RuntimePositionState]:
        db = self.SessionLocal()
        position = db.query(RuntimePositionState).filter(
            RuntimePositionState.account_id == account_id,
            RuntimePositionState.symbol == symbol,
            RuntimePositionState.is_open.is_(True),
        ).first()
        if position:
            position.is_open = False
            db.commit()
            db.refresh(position)
        db.close()
        return position

    # PnL Operations
    @staticmethod
    def _day_bounds(timestamp: datetime) -> tuple[datetime, datetime]:
        start = datetime.combine(timestamp.date(), datetime.min.time())
        return start, start + timedelta(days=1)

    def create_pnl(self, account_id: str, symbol: str, pnl_value: float, timestamp: datetime) -> DailyPNL:
        db = self.SessionLocal()
        day_start, _ = self._day_bounds(timestamp)
        pnl_entry = DailyPNL(account_id=account_id, date=day_start, pnl=pnl_value)
        db.add(pnl_entry)
        db.commit()
        db.refresh(pnl_entry)
        db.close()
        return pnl_entry

    def get_pnl_history(self, account_id: str) -> List[DailyPNL]:
        db = self.SessionLocal()
        pnls = db.query(DailyPNL).filter(DailyPNL.account_id == account_id).order_by(DailyPNL.date.desc()).all()
        db.close()
        return pnls

    # Drawdown Operations
    def create_drawdown(self, account_id: str, drawdown_value: float, timestamp: datetime) -> Drawdown:
        db = self.SessionLocal()
        drawdown_entry = Drawdown(account_id=account_id, start_time=timestamp, peak_balance=0.0, trough_balance=0.0, max_drawdown_percentage=0.0, drawdown=drawdown_value) # Simplified
        db.add(drawdown_entry)
        db.commit()
        db.refresh(drawdown_entry)
        db.close()
        return drawdown_entry

    def get_drawdown_history(self, account_id: str) -> List[Drawdown]:
        db = self.SessionLocal()
        drawdowns = db.query(Drawdown).filter(Drawdown.account_id == account_id).order_by(Drawdown.start_time.desc()).all()
        db.close()
        return drawdowns

    # PNL Operations
    def create_or_update_daily_pnl(self, account_id: str, date: datetime, pnl: float, drawdown: float) -> DailyPNL:
        db = self.SessionLocal()
        day_start, day_end = self._day_bounds(date)
        daily_pnl = db.query(DailyPNL).filter(
            DailyPNL.account_id == account_id,
            DailyPNL.date >= day_start,
            DailyPNL.date < day_end,
        ).first()
        if daily_pnl:
            daily_pnl.pnl = pnl
            daily_pnl.drawdown = drawdown
        else:
            daily_pnl = DailyPNL(account_id=account_id, date=day_start, pnl=pnl, drawdown=drawdown)
            db.add(daily_pnl)
        db.commit()
        db.refresh(daily_pnl)
        db.close()
        return daily_pnl

    def get_daily_pnl(self, account_id: str, date: datetime) -> Optional[DailyPNL]:
        db = self.SessionLocal()
        day_start, day_end = self._day_bounds(date)
        daily_pnl = db.query(DailyPNL).filter(
            DailyPNL.account_id == account_id,
            DailyPNL.date >= day_start,
            DailyPNL.date < day_end,
        ).first()
        db.close()
        return daily_pnl

    # News and trend persistence
    def create_news_article(self, article: Dict[str, object], symbol: Optional[str] = None) -> NewsArticle:
        db = self.SessionLocal()
        provider = str(article.get("provider") or article.get("source") or "unknown")
        title = str(article.get("title") or "Untitled")
        url = str(article.get("url") or "")
        external_id = hashlib.sha256(f"{provider}|{url}|{title}".encode("utf-8")).hexdigest()
        existing = db.query(NewsArticle).filter(NewsArticle.external_id == external_id).first()
        if existing:
            existing.sentiment_score = float(article.get("sentiment_score") or 0.0)
            db.commit()
            db.refresh(existing)
            db.close()
            return existing
        published_at = article.get("time_published")
        if isinstance(published_at, str):
            try:
                published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                published_at = None
        news_article = NewsArticle(
            external_id=external_id,
            provider=provider,
            symbol=symbol or article.get("ticker"),
            title=title,
            summary=str(article.get("summary") or ""),
            url=url,
            published_at=published_at,
            sentiment_score=float(article.get("sentiment_score") or 0.0),
            metadata_json={key: value for key, value in article.items() if key not in {"title", "summary", "url", "sentiment_score"}},
        )
        db.add(news_article)
        db.commit()
        db.refresh(news_article)
        db.close()
        return news_article

    def create_trend_snapshot(self, trend: Dict[str, object]) -> TrendSnapshot:
        db = self.SessionLocal()
        provider = str(trend.get("provider") or trend.get("source") or "unknown")
        symbol = str(trend.get("symbol") or "unknown")
        trend_score = float(trend.get("trend_score") or 0.0)
        market_cap_rank = trend.get("market_cap_rank")
        price_change_24h = trend.get("price_change_24h")
        metadata = dict(trend)
        existing = db.query(TrendSnapshot).filter(
            TrendSnapshot.provider == provider,
            TrendSnapshot.symbol == symbol,
            TrendSnapshot.trend_score == trend_score,
            TrendSnapshot.market_cap_rank == market_cap_rank,
            TrendSnapshot.price_change_24h == price_change_24h,
        ).order_by(TrendSnapshot.observed_at.desc()).first()
        if existing and existing.metadata_json == metadata:
            existing.observed_at = utc_now()
            db.commit()
            db.refresh(existing)
            db.close()
            return existing
        snapshot = TrendSnapshot(
            provider=provider,
            symbol=symbol,
            trend_score=trend_score,
            market_cap_rank=market_cap_rank,
            price_change_24h=price_change_24h,
            metadata_json=metadata,
        )
        db.add(snapshot)
        db.commit()
        db.refresh(snapshot)
        db.close()
        return snapshot

    # AI shadow observations
    def create_ai_observation(self, observation: Dict[str, object]) -> AIObservation:
        db = self.SessionLocal()
        record = AIObservation(
            symbol=str(observation.get("symbol") or "unknown"),
            observed_at=observation.get("observed_at") if isinstance(observation.get("observed_at"), datetime) else utc_now(),
            mode=str(observation.get("mode") or "shadow"),
            action=str(observation.get("action") or "hold"),
            candidate_action=str(observation.get("candidate_action") or "hold"),
            confidence=float(observation.get("confidence") or 0.0),
            model_action=str(observation.get("model_action") or "hold"),
            model_confidence=float(observation.get("model_confidence") or 0.0),
            market_signal_action=str(observation.get("market_signal_action") or "hold"),
            market_signal_confidence=float(observation.get("market_signal_confidence") or 0.0),
            price=float(observation.get("price") or 0.0),
            news_sentiment=float(observation.get("news_sentiment") or 0.0),
            trend_score=float(observation.get("trend_score") or 0.0),
            event_blocked=bool(observation.get("event_blocked", False)),
            risk_valid=bool(observation.get("risk_valid", False)),
            decision_latency_ms=float(observation.get("decision_latency_ms") or 0.0),
            news_latency_ms=float(observation.get("news_latency_ms") or 0.0),
            forward_return=observation.get("forward_return"),
            outcome_label=observation.get("outcome_label"),
            metadata_json=dict(observation.get("metadata_json") or {}),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        db.close()
        return record

    def get_ai_observations(self, symbol: Optional[str] = None, limit: int = 1000) -> List[AIObservation]:
        db = self.SessionLocal()
        query = db.query(AIObservation)
        if symbol:
            query = query.filter(AIObservation.symbol == symbol)
        observations = query.order_by(AIObservation.observed_at.desc()).limit(max(1, min(int(limit), 10000))).all()
        db.close()
        return observations

    def update_ai_observation_outcome(
        self,
        observation_id: int,
        forward_return: float,
        outcome_label: int,
        after_context: Optional[Dict[str, object]] = None,
    ) -> Optional[AIObservation]:
        db = self.SessionLocal()
        record = db.query(AIObservation).filter(AIObservation.id == int(observation_id)).first()
        if record:
            record.forward_return = float(forward_return)
            record.outcome_label = int(outcome_label)
            if after_context:
                metadata = dict(record.metadata_json or {})
                metadata.update(after_context)
                record.metadata_json = metadata
            db.commit()
            db.refresh(record)
        db.close()
        return record

    def create_decision_snapshot(self, snapshot: Dict[str, object]) -> DecisionSnapshot:
        observed_at = snapshot.get("observed_at") if isinstance(snapshot.get("observed_at"), datetime) else utc_now()
        symbol = str(snapshot.get("symbol") or "unknown")
        before_context = self._json_safe(dict(snapshot.get("before_context") or {}))
        snapshot_id = str(snapshot.get("snapshot_id") or hashlib.sha256(
            f"{symbol}:{observed_at.isoformat()}:{snapshot.get('action', 'hold')}".encode("utf-8")
        ).hexdigest()[:32])
        db = self.SessionLocal()
        try:
            record = db.query(DecisionSnapshot).filter(DecisionSnapshot.snapshot_id == snapshot_id).first()
            if record is None:
                record = DecisionSnapshot(
                    snapshot_id=snapshot_id,
                    symbol=symbol,
                    timeframe=str(snapshot.get("timeframe") or "1h"),
                    mode=str(snapshot.get("mode") or "shadow"),
                    observed_at=observed_at,
                    dataset_path=(str(snapshot["dataset_path"]) if snapshot.get("dataset_path") else None),
                    dataset_sha256=(str(snapshot["dataset_sha256"]) if snapshot.get("dataset_sha256") else None),
                    feature_hash=(str(snapshot["feature_hash"]) if snapshot.get("feature_hash") else None),
                    action=str(snapshot.get("action") or "hold"),
                    candidate_action=str(snapshot.get("candidate_action") or "hold"),
                    confidence=float(snapshot.get("confidence") or 0.0),
                    gate_status=str(snapshot.get("gate_status") or "blocked"),
                    before_context_json=before_context,
                    after_context_json=self._json_safe(dict(snapshot.get("after_context") or {})) if snapshot.get("after_context") else None,
                )
                db.add(record)
            db.commit()
            db.refresh(record)
            return record
        finally:
            db.close()

    def update_decision_snapshot_after(self, snapshot_id: str, after_context: Dict[str, object]) -> Optional[DecisionSnapshot]:
        db = self.SessionLocal()
        try:
            record = db.query(DecisionSnapshot).filter(DecisionSnapshot.snapshot_id == str(snapshot_id)).first()
            if record is not None:
                record.after_context_json = self._json_safe(dict(after_context or {}))
                db.commit()
                db.refresh(record)
            return record
        finally:
            db.close()

    def list_decision_snapshots(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict[str, object]]:
        db = self.SessionLocal()
        try:
            query = db.query(DecisionSnapshot)
            if symbol:
                query = query.filter(DecisionSnapshot.symbol == symbol)
            rows = query.order_by(DecisionSnapshot.observed_at.desc()).limit(max(1, min(int(limit), 1000))).all()
            return [
                {
                    "snapshot_id": row.snapshot_id,
                    "symbol": row.symbol,
                    "timeframe": row.timeframe,
                    "mode": row.mode,
                    "observed_at": row.observed_at.isoformat() if row.observed_at else None,
                    "dataset_path": row.dataset_path,
                    "dataset_sha256": row.dataset_sha256,
                    "feature_hash": row.feature_hash,
                    "action": row.action,
                    "candidate_action": row.candidate_action,
                    "confidence": row.confidence,
                    "gate_status": row.gate_status,
                    "before_context": row.before_context_json or {},
                    "after_context": row.after_context_json or {},
                }
                for row in rows
            ]
        finally:
            db.close()

    def get_unlabeled_ai_observations(self, symbol: Optional[str] = None, limit: int = 1000) -> List[AIObservation]:
        db = self.SessionLocal()
        query = db.query(AIObservation).filter(AIObservation.outcome_label.is_(None))
        if symbol:
            query = query.filter(AIObservation.symbol == symbol)
        records = query.order_by(AIObservation.observed_at.asc()).limit(max(1, min(int(limit), 10000))).all()
        db.close()
        return records

    # Market pattern memory
    def create_market_pattern(self, pattern: Dict[str, object]) -> MarketPattern:
        db = self.SessionLocal()
        record = MarketPattern(
            symbol=str(pattern.get("symbol") or "unknown"),
            strategy=str(pattern.get("strategy") or "pullback"),
            observed_at=pattern.get("observed_at") if isinstance(pattern.get("observed_at"), datetime) else utc_now(),
            pattern_type=str(pattern.get("pattern_type") or "pullback"),
            signature_json=dict(pattern.get("signature_json") or {}),
            entry_price=float(pattern.get("entry_price") or 0.0),
            atr=float(pattern.get("atr") or 0.0),
            outcome_atr=(float(pattern["outcome_atr"]) if pattern.get("outcome_atr") is not None else None),
            outcome_label=(int(pattern["outcome_label"]) if pattern.get("outcome_label") is not None else None),
            sample_size=max(1, int(pattern.get("sample_size") or 1)),
            source_observation_id=(int(pattern["source_observation_id"]) if pattern.get("source_observation_id") is not None else None),
            metadata_json=dict(pattern.get("metadata_json") or {}),
        )
        db.add(record)
        db.commit()
        db.refresh(record)
        db.close()
        return record

    def get_market_patterns(self, symbol: Optional[str] = None, strategy: Optional[str] = None, limit: int = 5000) -> List[MarketPattern]:
        db = self.SessionLocal()
        query = db.query(MarketPattern)
        if symbol:
            query = query.filter(MarketPattern.symbol == symbol)
        if strategy:
            query = query.filter(MarketPattern.strategy == strategy)
        records = query.order_by(MarketPattern.observed_at.desc()).limit(max(1, min(int(limit), 10000))).all()
        db.close()
        return records

    # OrderHistory Operations
    def create_order_history(self, account_id: str, order_id: str, symbol: str, market_type: MarketType, action: str, order_type: str, price: Optional[float], quantity: Optional[float], status: OrderStatus, metadata_json: Optional[dict] = None) -> OrderHistory:
        db = self.SessionLocal()
        order_history = OrderHistory(account_id=account_id, order_id=order_id, symbol=symbol, market_type=market_type, action=action, order_type=order_type, price=price, quantity=quantity, status=status, metadata_json=metadata_json)
        db.add(order_history)
        db.commit()
        db.refresh(order_history)
        db.close()
        return order_history

    def update_order_status(self, order_id: str, status: OrderStatus) -> Optional[OrderHistory]:
        db = self.SessionLocal()
        order_history = db.query(OrderHistory).filter(OrderHistory.order_id == order_id).first()
        if order_history:
            order_history.status = status
            db.commit()
            db.refresh(order_history)
        db.close()
        return order_history

    def get_order_history(self, account_id: str) -> List[OrderHistory]:
        db = self.SessionLocal()
        orders = db.query(OrderHistory).filter(OrderHistory.account_id == account_id).order_by(OrderHistory.timestamp.desc()).all()
        db.close()
        return orders

    # ExecutionHistory Operations
    def create_execution_history(self, account_id: str, execution_id: str, order_id: str, symbol: str, market_type: MarketType, action: str, filled_price: float, filled_quantity: float, commission: float, metadata_json: Optional[dict] = None) -> ExecutionHistory:
        db = self.SessionLocal()
        execution_history = ExecutionHistory(account_id=account_id, execution_id=execution_id, order_id=order_id, symbol=symbol, market_type=market_type, action=action, filled_price=filled_price, filled_quantity=filled_quantity, commission=commission, metadata_json=metadata_json)
        db.add(execution_history)
        db.commit()
        db.refresh(execution_history)
        db.close()
        return execution_history

    def get_execution_history(self, account_id: str) -> List[ExecutionHistory]:
        db = self.SessionLocal()
        executions = db.query(ExecutionHistory).filter(ExecutionHistory.account_id == account_id).order_by(ExecutionHistory.timestamp.desc()).all()
        db.close()
        return executions

    # SystemLog Operations
    def create_system_log(self, level: str, message: str, module: str, account_id: Optional[str] = None) -> SystemLog:
        db = self.SessionLocal()
        system_log = SystemLog(level=level, message=message, module=module, account_id=account_id)
        db.add(system_log)
        db.commit()
        db.refresh(system_log)
        db.close()
        return system_log

    def get_system_logs(self, account_id: str = None) -> List[SystemLog]:
        db = self.SessionLocal()
        if account_id:
            logs = db.query(SystemLog).filter(SystemLog.account_id == account_id).order_by(SystemLog.timestamp.desc()).all()
        else:
            logs = db.query(SystemLog).order_by(SystemLog.timestamp.desc()).all()
        db.close()
        return logs

    # Utility for PNL calculations (simplified for now)
    def calculate_pnl_metrics(self, account_id: str, end_date: datetime) -> Dict[str, float]:
        db = self.SessionLocal()
        # Placeholder for actual PNL, drawdown, etc. calculation logic
        # This would involve querying trades, positions, etc.
        total_pnl = 0.0
        current_balance = self.get_account_state(account_id).balance if self.get_account_state(account_id) else 0.0
        initial_capital = self.get_account_state(account_id).initial_capital if self.get_account_state(account_id) else 0.0

        if initial_capital > 0:
            total_pnl = current_balance - initial_capital

        # Simplified drawdown calculation
        drawdown = 0.0 # This needs proper implementation based on historical balance

        db.close()
        return {"total_pnl": total_pnl, "drawdown": drawdown}


    # Order intent, reconciliation and protection operations
    @staticmethod
    def _intent_dict(intent: OrderIntent) -> Dict:
        return {
            "client_order_id": intent.client_order_id,
            "account_id": intent.account_id,
            "symbol": intent.symbol,
            "action": intent.action,
            "order_type": intent.order_type,
            "quantity": intent.quantity,
            "price": intent.price,
            "status": intent.status,
            "exchange_order_id": intent.exchange_order_id,
            "attempts": intent.attempts,
            "last_error": intent.last_error,
        }

    def reserve_order_intent(self, account_id: str, client_order_id: str, order_data: Dict) -> Dict:
        db = self.SessionLocal()
        try:
            intent = db.query(OrderIntent).filter(OrderIntent.client_order_id == client_order_id).first()
            if intent is None:
                safe_payload = {
                    key: (value.value if hasattr(value, "value") else value)
                    for key, value in dict(order_data).items()
                }
                intent = OrderIntent(
                    account_id=account_id,
                    client_order_id=client_order_id,
                    symbol=str(order_data["symbol"]),
                    action=str(order_data["action"]).lower(),
                    order_type=str(order_data.get("order_type", "market")).lower(),
                    quantity=float(order_data["quantity"]),
                    price=float(order_data["price"]) if order_data.get("price") is not None else None,
                    payload_json=safe_payload,
                )
                db.add(intent)
                db.commit()
                db.refresh(intent)
            return self._intent_dict(intent)
        finally:
            db.close()

    def update_order_intent(self, client_order_id: str, **changes) -> Optional[Dict]:
        db = self.SessionLocal()
        try:
            intent = db.query(OrderIntent).filter(OrderIntent.client_order_id == client_order_id).first()
            if intent is None:
                return None
            allowed = {"status", "exchange_order_id", "attempts", "last_error", "payload_json"}
            for key, value in changes.items():
                if key in allowed:
                    setattr(intent, key, value)
            db.commit()
            db.refresh(intent)
            return self._intent_dict(intent)
        finally:
            db.close()

    def get_order_intent(self, client_order_id: str) -> Optional[Dict]:
        db = self.SessionLocal()
        try:
            intent = db.query(OrderIntent).filter(OrderIntent.client_order_id == client_order_id).first()
            return self._intent_dict(intent) if intent else None
        finally:
            db.close()

    def list_open_order_intents(self, account_id: str) -> List[Dict]:
        db = self.SessionLocal()
        try:
            rows = db.query(OrderIntent).filter(
                OrderIntent.account_id == account_id,
                OrderIntent.status.in_(["reserved", "submitted", "pending", "open", "partially_filled"]),
            ).all()
            return [self._intent_dict(row) for row in rows]
        finally:
            db.close()

    def create_reconciliation_snapshot(self, account_id: str, status: str, payload: Dict) -> Dict:
        db = self.SessionLocal()
        try:
            snapshot = ReconciliationSnapshot(
                account_id=account_id,
                status=status,
                open_orders_count=int(payload.get("open_orders_count", 0)),
                positions_count=int(payload.get("positions_count", 0)),
                payload_json=payload,
            )
            db.add(snapshot)
            db.commit()
            db.refresh(snapshot)
            return {"id": snapshot.id, "account_id": account_id, "status": status, **payload}
        finally:
            db.close()

    def upsert_protection_order(self, account_id: str, protection: Dict) -> Dict:
        db = self.SessionLocal()
        try:
            row = db.query(ProtectionOrder).filter(ProtectionOrder.client_order_id == protection["client_order_id"]).first()
            if row is None:
                row = ProtectionOrder(account_id=account_id, client_order_id=protection["client_order_id"])
                db.add(row)
            for key in ("parent_client_order_id", "exchange_order_id", "symbol", "action", "order_type", "quantity", "stop_price", "limit_price", "status"):
                if key in protection:
                    setattr(row, key, protection[key])
            db.commit()
            db.refresh(row)
            return {"id": row.id, "account_id": row.account_id, "client_order_id": row.client_order_id, "parent_client_order_id": row.parent_client_order_id, "exchange_order_id": row.exchange_order_id, "symbol": row.symbol, "action": row.action, "order_type": row.order_type, "quantity": row.quantity, "stop_price": row.stop_price, "limit_price": row.limit_price, "status": row.status}
        finally:
            db.close()

    def list_active_protection_orders(self, account_id: str, parent_client_order_id: Optional[str] = None) -> List[Dict]:
        db = self.SessionLocal()
        try:
            query = db.query(ProtectionOrder).filter(ProtectionOrder.account_id == account_id, ProtectionOrder.status.in_(["pending", "open", "partially_filled"]))
            if parent_client_order_id:
                query = query.filter(ProtectionOrder.parent_client_order_id == parent_client_order_id)
            rows = query.all()
            return [{"client_order_id": row.client_order_id, "parent_client_order_id": row.parent_client_order_id, "exchange_order_id": row.exchange_order_id, "symbol": row.symbol, "action": row.action, "order_type": row.order_type, "quantity": row.quantity, "stop_price": row.stop_price, "limit_price": row.limit_price, "status": row.status} for row in rows]
        finally:
            db.close()

    def update_protection_order(self, client_order_id: str, **changes) -> Optional[Dict]:
        db = self.SessionLocal()
        try:
            row = db.query(ProtectionOrder).filter(ProtectionOrder.client_order_id == client_order_id).first()
            if row is None:
                return None
            for key in ("exchange_order_id", "status"):
                if key in changes:
                    setattr(row, key, changes[key])
            db.commit()
            db.refresh(row)
            return {"client_order_id": row.client_order_id, "exchange_order_id": row.exchange_order_id, "status": row.status}
        finally:
            db.close()

    def record_kill_switch(self, account_id: str, enabled: bool, reason: str, actor: str = "system") -> Dict:
        db = self.SessionLocal()
        try:
            row = KillSwitchEvent(account_id=account_id, enabled=enabled, reason=reason, actor=actor)
            db.add(row)
            db.commit()
            db.refresh(row)
            return {"id": row.id, "account_id": account_id, "enabled": enabled, "reason": reason, "actor": actor}
        finally:
            db.close()

    @staticmethod
    def _json_safe(value):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {str(key): DatabaseManager._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [DatabaseManager._json_safe(item) for item in value]
        return value

    @staticmethod
    def _parse_datetime(value: object) -> datetime:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
            except ValueError:
                pass
        return utc_now()

    def create_backtest_run(
        self,
        run_id: str,
        symbol: str,
        timeframe: str,
        dataset_path: str,
        dataset_sha256: str,
        result: Dict,
        configuration: Optional[Dict] = None,
        mode: str = "historical",
    ) -> Dict:
        """Grava uma execução histórica sem alterar modelos ou habilitar ordens."""
        db = self.SessionLocal()
        try:
            safe_result = self._json_safe(dict(result))
            existing = db.query(BacktestRun).filter(BacktestRun.run_id == run_id).first()
            if existing is None:
                existing = BacktestRun(run_id=run_id, symbol=symbol, timeframe=timeframe, mode=mode, dataset_path=dataset_path, dataset_sha256=dataset_sha256)
                db.add(existing)
            existing.start_time = self._parse_datetime(result.get("start_date"))
            existing.end_time = self._parse_datetime(result.get("end_date"))
            existing.status = str(result.get("status", "completed"))
            existing.initial_capital = result.get("initial_capital")
            existing.final_capital = result.get("final_capital")
            existing.total_pnl = result.get("total_pnl")
            existing.return_pct = result.get("return_pct")
            existing.sharpe_ratio = result.get("sharpe_ratio")
            existing.maximum_drawdown = result.get("maximum_drawdown", result.get("max_drawdown"))
            existing.trades_executed = int(result.get("trades_executed", 0) or 0)
            existing.configuration_json = self._json_safe(configuration or {})
            existing.result_json = safe_result
            db.commit()
            db.refresh(existing)
            return {"run_id": existing.run_id, "id": existing.id, "symbol": existing.symbol, "status": existing.status}
        finally:
            db.close()

    def list_backtest_runs(self, symbol: Optional[str] = None, limit: int = 100) -> List[Dict]:
        db = self.SessionLocal()
        try:
            query = db.query(BacktestRun)
            if symbol:
                query = query.filter(BacktestRun.symbol == symbol)
            rows = query.order_by(BacktestRun.created_at.desc()).limit(max(1, min(int(limit), 1000))).all()
            return [
                {
                    "run_id": row.run_id,
                    "symbol": row.symbol,
                    "timeframe": row.timeframe,
                    "mode": row.mode,
                    "dataset_path": row.dataset_path,
                    "dataset_sha256": row.dataset_sha256,
                    "start_time": row.start_time.isoformat() if row.start_time else None,
                    "end_time": row.end_time.isoformat() if row.end_time else None,
                    "status": row.status,
                    "initial_capital": row.initial_capital,
                    "final_capital": row.final_capital,
                    "total_pnl": row.total_pnl,
                    "return_pct": row.return_pct,
                    "sharpe_ratio": row.sharpe_ratio,
                    "maximum_drawdown": row.maximum_drawdown,
                    "trades_executed": row.trades_executed,
                }
                for row in rows
            ]
        finally:
            db.close()
