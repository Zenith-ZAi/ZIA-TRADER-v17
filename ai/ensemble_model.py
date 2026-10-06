from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Dict, Tuple

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.ensemble import RandomForestClassifier

from ai.feature_pipeline import MODEL_FEATURE_COLUMNS

logger = logging.getLogger(__name__)


class EnsembleModel:
    """Ensemble auditável de Random Forest e XGBoost para ações 0/1/2."""

    ACTION_MAP = {0: "sell", 1: "hold", 2: "buy"}

    def __init__(self, model_dir: str = "models", random_state: int = 42):
        self.model_dir = Path(model_dir)
        self.random_state = int(random_state)
        self.rf_model = None
        self.xgb_model = None
        self.is_trained = False
        self.feature_columns: list[str] = []
        self.metadata: Dict[str, object] = {}
        self._ensure_model_dir()
        self._load_models()

    def _ensure_model_dir(self) -> None:
        self.model_dir.mkdir(parents=True, exist_ok=True)

    @property
    def _metadata_path(self) -> Path:
        return self.model_dir / "ensemble_metadata.json"

    def _initialize_untrained_models(self) -> None:
        self.rf_model = RandomForestClassifier(
            n_estimators=200,
            random_state=self.random_state,
            class_weight="balanced_subsample",
            n_jobs=1,
        )
        self.xgb_model = xgb.XGBClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.9,
            colsample_bytree=0.9,
            random_state=self.random_state,
            eval_metric="mlogloss",
            n_jobs=1,
        )
        self.is_trained = False
        self.feature_columns = []

    def _load_models(self) -> None:
        rf_path = self.model_dir / "rf_model.joblib"
        xgb_path = self.model_dir / "xgb_model.joblib"
        try:
            if not (rf_path.exists() and xgb_path.exists() and self._metadata_path.exists()):
                logger.warning("Artefatos Ensemble ausentes ou sem metadados; modo neutro ativado.")
                self._initialize_untrained_models()
                return
            with self._metadata_path.open("r", encoding="utf-8") as handle:
                metadata = json.load(handle)
            columns = metadata.get("feature_columns")
            if not isinstance(columns, list) or columns != MODEL_FEATURE_COLUMNS:
                raise ValueError("schema de features do Ensemble incompatível")
            self.rf_model = joblib.load(rf_path)
            self.xgb_model = joblib.load(xgb_path)
            if not set(getattr(self.rf_model, "classes_", [])) >= {0, 1, 2}:
                raise ValueError("Random Forest não contém as três classes esperadas")
            if not set(getattr(self.xgb_model, "classes_", [])) >= {0, 1, 2}:
                raise ValueError("XGBoost não contém as três classes esperadas")
            self.feature_columns = columns
            self.metadata = metadata
            self.is_trained = True
            logger.info("Ensemble treinado carregado: %s", self.metadata.get("trained_at", "sem data"))
        except Exception as exc:
            logger.error("Artefatos Ensemble rejeitados: %s", exc)
            self._initialize_untrained_models()

    def train(self, X: pd.DataFrame, y: pd.Series, metadata: Dict[str, object] | None = None) -> Dict[str, object]:
        """Treina, valida o schema e persiste o Ensemble aprovado pelo caller."""
        if not isinstance(X, pd.DataFrame) or X.empty:
            raise ValueError("X vazio ou inválido")
        if not isinstance(y, pd.Series) or len(y) != len(X):
            raise ValueError("y inválido ou desalinhado com X")
        columns = list(X.columns)
        if columns != MODEL_FEATURE_COLUMNS:
            raise ValueError(f"features incompatíveis; esperadas {MODEL_FEATURE_COLUMNS}")
        labels = pd.to_numeric(y, errors="raise").astype(int)
        if not set(labels.unique()) >= {0, 1, 2}:
            raise ValueError("o dataset precisa conter as classes sell=0, hold=1 e buy=2")
        if not np.isfinite(X.to_numpy(dtype=float)).all():
            raise ValueError("X contém valores não finitos")

        self._initialize_untrained_models()
        self.rf_model.fit(X, labels)
        self.xgb_model.fit(X, labels)
        self.feature_columns = columns
        self.is_trained = True
        self.metadata = {
            "feature_columns": columns,
            "classes": {"sell": 0, "hold": 1, "buy": 2},
            "rows": int(len(X)),
            **(metadata or {}),
        }
        joblib.dump(self.rf_model, self.model_dir / "rf_model.joblib")
        joblib.dump(self.xgb_model, self.model_dir / "xgb_model.joblib")
        with self._metadata_path.open("w", encoding="utf-8") as handle:
            json.dump(self.metadata, handle, ensure_ascii=False, indent=2, default=str)
        return self.metadata

    @staticmethod
    def _aligned_proba(model, features: pd.DataFrame) -> np.ndarray:
        raw = model.predict_proba(features)[0]
        aligned = np.zeros(3, dtype=float)
        for class_label, probability in zip(model.classes_, raw):
            label = int(class_label)
            if 0 <= label <= 2:
                aligned[label] = float(probability)
        return aligned

    @staticmethod
    def _aligned_proba_matrix(model, features: pd.DataFrame) -> np.ndarray:
        raw = np.asarray(model.predict_proba(features), dtype=float)
        aligned = np.zeros((len(features), 3), dtype=float)
        for column, class_label in enumerate(model.classes_):
            label = int(class_label)
            if 0 <= label <= 2:
                aligned[:, label] = raw[:, column]
        return aligned

    def _drift_hold_active(self) -> bool:
        """Estado ausente preserva compatibilidade; estado corrompido falha fechado."""
        status_path = self.model_dir / "drift_status.json"
        if not status_path.exists():
            return False
        try:
            with status_path.open("r", encoding="utf-8") as handle:
                status = json.load(handle)
            return bool(status.get("hold", True))
        except (OSError, json.JSONDecodeError, AttributeError) as exc:
            logger.error("Estado de drift ilegível; saída HOLD por segurança: %s", exc)
            return True

    def predict_proba(self, features: pd.DataFrame) -> np.ndarray:
        """Probabilidades médias RF/XGBoost alinhadas a sell/hold/buy; sem alterar o modelo."""
        if not self.is_trained or not self.feature_columns:
            return np.tile(np.asarray([0.25, 0.50, 0.25], dtype=float), (len(features), 1))
        if not isinstance(features, pd.DataFrame) or features.empty:
            raise ValueError("features vazias ou inválidas")
        if list(features.columns) != self.feature_columns:
            raise ValueError("schema de inferência incompatível")
        rf_probs = self._aligned_proba_matrix(self.rf_model, features)
        xgb_probs = self._aligned_proba_matrix(self.xgb_model, features)
        average = (rf_probs + xgb_probs) / 2.0
        if not np.isfinite(average).all() or not np.allclose(average.sum(axis=1), 1.0, atol=1e-6):
            raise ValueError("probabilidades inválidas ou não normalizadas")
        return average

    def predict(self, features: pd.DataFrame) -> Tuple[str, float]:
        """Retorna ação e probabilidade média; qualquer incompatibilidade vira HOLD."""
        if self._drift_hold_active():
            logger.error("Modelo em drift hold persistente; ação bloqueada até revisão manual.")
            return "hold", 0.5
        if not self.is_trained or not self.feature_columns:
            return "hold", 0.5
        try:
            avg_probs = self.predict_proba(features)[0]
            predicted_class_idx = int(np.argmax(avg_probs))
            return self.ACTION_MAP[predicted_class_idx], float(avg_probs[predicted_class_idx])
        except Exception as exc:
            logger.error("Erro na previsão do Ensemble: %s", exc)
            return "hold", 0.5
