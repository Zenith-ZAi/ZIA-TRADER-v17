import pandas as pd
import numpy as np
import logging
from typing import Dict, Any, Tuple
from sklearn.ensemble import RandomForestClassifier
import xgboost as xgb
import joblib
import os

logger = logging.getLogger(__name__)

class EnsembleModel:
    """Modelo Ensemble combinando XGBoost e Random Forest para previsões mais robustas."""
    def __init__(self, model_dir: str = "models"):
        self.model_dir = model_dir
        self.rf_model = None
        self.xgb_model = None
        self.is_trained = False
        self._ensure_model_dir()
        self._load_models()

    def _ensure_model_dir(self):
        if not os.path.exists(self.model_dir):
            os.makedirs(self.model_dir)

    def _load_models(self):
        rf_path = os.path.join(self.model_dir, "rf_model.joblib")
        xgb_path = os.path.join(self.model_dir, "xgb_model.joblib")
        
        try:
            if os.path.exists(rf_path) and os.path.exists(xgb_path):
                self.rf_model = joblib.load(rf_path)
                self.xgb_model = joblib.load(xgb_path)
                self.is_trained = True
                logger.info("Modelos Ensemble carregados com sucesso.")
            else:
                logger.warning("Modelos Ensemble não encontrados. Necessário treinamento.")
                self._initialize_untrained_models()
        except Exception as e:
            logger.error(f"Erro ao carregar modelos Ensemble: {e}")
            self._initialize_untrained_models()

    def _initialize_untrained_models(self):
        self.rf_model = RandomForestClassifier(n_estimators=100, random_state=42)
        self.xgb_model = xgb.XGBClassifier(n_estimators=100, learning_rate=0.1, random_state=42, use_label_encoder=False, eval_metric='logloss')
        self.is_trained = False

    def train(self, X: pd.DataFrame, y: pd.Series):
        """Treina os modelos com os dados fornecidos."""
        logger.info("Iniciando treinamento dos modelos Ensemble...")
        try:
            self.rf_model.fit(X, y)
            self.xgb_model.fit(X, y)
            self.is_trained = True
            
            # Salvar modelos
            joblib.dump(self.rf_model, os.path.join(self.model_dir, "rf_model.joblib"))
            joblib.dump(self.xgb_model, os.path.join(self.model_dir, "xgb_model.joblib"))
            logger.info("Modelos Ensemble treinados e salvos com sucesso.")
        except Exception as e:
            logger.error(f"Erro durante o treinamento dos modelos Ensemble: {e}")

    def predict(self, features: pd.DataFrame) -> Tuple[str, float]:
        """Faz uma previsão usando o ensemble (votação/média de probabilidades)."""
        if not self.is_trained:
            logger.warning("Modelos não treinados. Retornando previsão neutra.")
            return "hold", 0.5

        try:
            # Assumindo que as classes são 0: sell, 1: hold, 2: buy
            rf_probs = self.rf_model.predict_proba(features)[0]
            xgb_probs = self.xgb_model.predict_proba(features)[0]
            
            # Média das probabilidades
            avg_probs = (rf_probs + xgb_probs) / 2.0
            
            predicted_class_idx = np.argmax(avg_probs)
            confidence = avg_probs[predicted_class_idx]
            
            action_map = {0: "sell", 1: "hold", 2: "buy"}
            prediction_action = action_map.get(predicted_class_idx, "hold")
            
            return prediction_action, float(confidence)
        except Exception as e:
            logger.error(f"Erro na previsão do Ensemble: {e}")
            return "hold", 0.5
