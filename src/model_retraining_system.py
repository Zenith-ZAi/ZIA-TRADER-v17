"""
Sistema de Retreinamento Periódico de Modelos de IA - RoboTrader
Implementa estratégias para retreinamento automático e contínuo dos modelos de machine learning.
"""

import os
import pickle
import json
import asyncio
import schedule
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, asdict
from pathlib import Path
import pandas as pd
import numpy as np
from sklearn.metrics import accuracy_score, precision_score, recall_score, f1_score
import tensorflow as tf
from tensorflow.keras.callbacks import EarlyStopping, ModelCheckpoint, ReduceLROnPlateau
import joblib

from utils import setup_logging
from config import config
from database import db_manager
from market_data_fixed import market_data_manager
from ai_model import AdvancedAIModel

logger = setup_logging(__name__)

@dataclass
class ModelPerformanceMetrics:
    """Métricas de performance do modelo"""
    timestamp: datetime
    model_version: str
    accuracy: float
    precision: float
    recall: float
    f1_score: float
    loss: float
    val_loss: float
    sharpe_ratio: float
    max_drawdown: float
    total_trades: int
    win_rate: float
    avg_return: float
    volatility: float
    
    def to_dict(self) -> Dict[str, Any]:
        """Converte para dicionário"""
        data = asdict(self)
        data['timestamp'] = self.timestamp.isoformat()
        return data

@dataclass
class RetrainingConfig:
    """Configuração de retreinamento"""
    frequency_days: int = 7  # Retreinar a cada 7 dias
    min_new_data_points: int = 1000  # Mínimo de novos dados para retreinar
    performance_threshold: float = 0.05  # Threshold de degradação para retreinamento forçado
    validation_split: float = 0.2
    max_epochs: int = 100
    early_stopping_patience: int = 10
    reduce_lr_patience: int = 5
    backup_models_count: int = 5  # Manter 5 versões anteriores
    
class ModelRetrainingSystem:
    """
    Sistema de Retreinamento Periódico de Modelos
    
    Funcionalidades:
    - Retreinamento automático baseado em cronograma
    - Retreinamento baseado em degradação de performance
    - Versionamento de modelos
    - Rollback automático para versões anteriores
    - Métricas de performance contínuas
    - Backup e recovery de modelos
    """
    
    def __init__(self, ai_model: AdvancedAIModel):
        self.ai_model = ai_model
        self.config = RetrainingConfig()
        self.is_running = False
        self.scheduler_thread = None
        
        # Diretórios para modelos
        self.models_dir = Path("models")
        self.models_dir.mkdir(exist_ok=True)
        
        self.backups_dir = self.models_dir / "backups"
        self.backups_dir.mkdir(exist_ok=True)
        
        # Histórico de performance
        self.performance_history: List[ModelPerformanceMetrics] = []
        self.current_model_version = self._get_current_version()
        
        # Configurar callbacks do TensorFlow
        self.callbacks = self._setup_callbacks()
        
        logger.info(f"Sistema de retreinamento inicializado. Versão atual: {self.current_model_version}")
    
    def _get_current_version(self) -> str:
        """Gera versão atual do modelo"""
        return f"v{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    
    def _setup_callbacks(self) -> List[tf.keras.callbacks.Callback]:
        """Configura callbacks para treinamento"""
        callbacks = [
            EarlyStopping(
                monitor='val_loss',
                patience=self.config.early_stopping_patience,
                restore_best_weights=True,
                verbose=1
            ),
            ReduceLROnPlateau(
                monitor='val_loss',
                factor=0.5,
                patience=self.config.reduce_lr_patience,
                min_lr=1e-7,
                verbose=1
            ),
            ModelCheckpoint(
                filepath=str(self.models_dir / f"best_model_{self.current_model_version}.h5"),
                monitor='val_loss',
                save_best_only=True,
                save_weights_only=False,
                verbose=1
            )
        ]
        return callbacks
    
    def start_scheduler(self):
        """Inicia o agendador de retreinamento"""
        if self.is_running:
            logger.warning("Sistema de retreinamento já está rodando")
            return
        
        self.is_running = True
        
        # Agendar retreinamento periódico
        schedule.every(self.config.frequency_days).days.do(self._scheduled_retrain)
        
        # Agendar verificação de performance diária
        schedule.every().day.at("02:00").do(self._check_performance_degradation)
        
        # Agendar backup semanal
        schedule.every().sunday.at("03:00").do(self._backup_models)
        
        # Thread para executar o scheduler
        self.scheduler_thread = threading.Thread(target=self._run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        logger.info("Sistema de retreinamento iniciado com sucesso")
    
    def stop_scheduler(self):
        """Para o agendador de retreinamento"""
        self.is_running = False
        schedule.clear()
        
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=5)
        
        logger.info("Sistema de retreinamento parado")
    
    def _run_scheduler(self):
        """Executa o loop do scheduler"""
        while self.is_running:
            try:
                schedule.run_pending()
                time.sleep(60)  # Verificar a cada minuto
            except Exception as e:
                logger.error(f"Erro no scheduler de retreinamento: {e}")
                time.sleep(300)  # Aguardar 5 minutos em caso de erro
    
    def _scheduled_retrain(self):
        """Retreinamento agendado"""
        logger.info("Iniciando retreinamento agendado")
        try:
            success = self.retrain_model(reason="scheduled")
            if success:
                logger.info("Retreinamento agendado concluído com sucesso")
            else:
                logger.warning("Retreinamento agendado falhou")
        except Exception as e:
            logger.error(f"Erro no retreinamento agendado: {e}")
    
    def _check_performance_degradation(self):
        """Verifica degradação de performance"""
        try:
            current_metrics = self._calculate_current_performance()
            
            if len(self.performance_history) > 0:
                recent_avg = self._get_recent_average_performance(days=7)
                
                # Verificar se houve degradação significativa
                performance_drop = recent_avg.f1_score - current_metrics.f1_score
                
                if performance_drop > self.config.performance_threshold:
                    logger.warning(f"Degradação de performance detectada: {performance_drop:.3f}")
                    self.retrain_model(reason="performance_degradation")
                else:
                    logger.info(f"Performance estável. Drop: {performance_drop:.3f}")
            
            # Adicionar métricas ao histórico
            self.performance_history.append(current_metrics)
            self._save_performance_metrics(current_metrics)
            
        except Exception as e:
            logger.error(f"Erro na verificação de performance: {e}")
    
    def retrain_model(self, reason: str = "manual") -> bool:
        """
        Executa retreinamento do modelo
        
        Args:
            reason: Motivo do retreinamento (scheduled, performance_degradation, manual)
            
        Returns:
            bool: True se retreinamento foi bem-sucedido
        """
        try:
            logger.info(f"Iniciando retreinamento do modelo. Motivo: {reason}")
            
            # 1. Coletar novos dados
            new_data = self._collect_new_training_data()
            
            if len(new_data) < self.config.min_new_data_points:
                logger.warning(f"Dados insuficientes para retreinamento: {len(new_data)} < {self.config.min_new_data_points}")
                return False
            
            # 2. Backup do modelo atual
            self._backup_current_model()
            
            # 3. Preparar dados para treinamento
            X_train, X_val, y_train, y_val = self._prepare_training_data(new_data)
            
            # 4. Atualizar versão do modelo
            old_version = self.current_model_version
            self.current_model_version = self._get_current_version()
            
            # 5. Retreinar modelo
            history = self._train_model(X_train, X_val, y_train, y_val)
            
            # 6. Validar novo modelo
            validation_metrics = self._validate_new_model(X_val, y_val)
            
            # 7. Decidir se aceitar novo modelo
            if self._should_accept_new_model(validation_metrics):
                self._deploy_new_model()
                logger.info(f"Novo modelo aceito e implantado. Versão: {self.current_model_version}")
                
                # Salvar métricas
                self.performance_history.append(validation_metrics)
                self._save_performance_metrics(validation_metrics)
                
                return True
            else:
                # Rollback para versão anterior
                self._rollback_to_previous_model(old_version)
                logger.warning("Novo modelo rejeitado. Rollback executado.")
                return False
                
        except Exception as e:
            logger.error(f"Erro durante retreinamento: {e}")
            return False
    
    def _collect_new_training_data(self) -> pd.DataFrame:
        """Coleta novos dados para treinamento"""
        try:
            # Obter data do último treinamento
            last_training_date = self._get_last_training_date()
            
            # Coletar dados desde a última data
            symbols = config.data.symbols
            all_data = []
            
            for symbol in symbols:
                # Obter dados históricos desde a última data
                data = db_manager.get_market_data(
                    symbol=symbol,
                    start_date=last_training_date,
                    end_date=datetime.now()
                )
                
                if not data.empty:
                    data['symbol'] = symbol
                    all_data.append(data)
            
            if all_data:
                combined_data = pd.concat(all_data, ignore_index=True)
                logger.info(f"Coletados {len(combined_data)} novos pontos de dados")
                return combined_data
            else:
                logger.warning("Nenhum novo dado coletado")
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"Erro ao coletar novos dados: {e}")
            return pd.DataFrame()
    
    def _get_last_training_date(self) -> datetime:
        """Obtém data do último treinamento"""
        try:
            # Verificar no banco de dados
            last_date = db_manager.get_last_training_date()
            if last_date:
                return last_date
            
            # Fallback: usar data de criação do modelo atual
            model_path = self.models_dir / f"model_{self.current_model_version}.pkl"
            if model_path.exists():
                return datetime.fromtimestamp(model_path.stat().st_mtime)
            
            # Fallback final: 30 dias atrás
            return datetime.now() - timedelta(days=30)
            
        except Exception as e:
            logger.error(f"Erro ao obter data do último treinamento: {e}")
            return datetime.now() - timedelta(days=30)
    
    def _prepare_training_data(self, data: pd.DataFrame) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
        """Prepara dados para treinamento"""
        try:
            # Usar o método do AI model para preparar dados
            X, y = self.ai_model.prepare_data(data)
            
            # Split treino/validação
            split_idx = int(len(X) * (1 - self.config.validation_split))
            
            X_train = X[:split_idx]
            X_val = X[split_idx:]
            y_train = y[:split_idx]
            y_val = y[split_idx:]
            
            logger.info(f"Dados preparados - Treino: {len(X_train)}, Validação: {len(X_val)}")
            
            return X_train, X_val, y_train, y_val
            
        except Exception as e:
            logger.error(f"Erro ao preparar dados de treinamento: {e}")
            raise
    
    def _train_model(self, X_train: np.ndarray, X_val: np.ndarray, 
                    y_train: np.ndarray, y_val: np.ndarray) -> tf.keras.callbacks.History:
        """Treina o modelo"""
        try:
            logger.info("Iniciando treinamento do modelo")
            
            # Atualizar callbacks com nova versão
            self.callbacks = self._setup_callbacks()
            
            # Treinar modelo
            history = self.ai_model.model.fit(
                X_train, y_train,
                validation_data=(X_val, y_val),
                epochs=self.config.max_epochs,
                batch_size=config.ai.batch_size,
                callbacks=self.callbacks,
                verbose=1
            )
            
            logger.info("Treinamento concluído")
            return history
            
        except Exception as e:
            logger.error(f"Erro durante treinamento: {e}")
            raise
    
    def _validate_new_model(self, X_val: np.ndarray, y_val: np.ndarray) -> ModelPerformanceMetrics:
        """Valida o novo modelo"""
        try:
            # Fazer predições
            predictions = self.ai_model.model.predict(X_val)
            
            # Converter para classes binárias (assumindo classificação binária)
            y_pred_binary = (predictions > 0.5).astype(int)
            y_val_binary = (y_val > 0.5).astype(int)
            
            # Calcular métricas
            accuracy = accuracy_score(y_val_binary, y_pred_binary)
            precision = precision_score(y_val_binary, y_pred_binary, average='weighted', zero_division=0)
            recall = recall_score(y_val_binary, y_pred_binary, average='weighted', zero_division=0)
            f1 = f1_score(y_val_binary, y_pred_binary, average='weighted', zero_division=0)
            
            # Calcular loss
            loss = self.ai_model.model.evaluate(X_val, y_val, verbose=0)
            val_loss = loss if isinstance(loss, float) else loss[0]
            
            # Métricas financeiras (simuladas - em produção, usar dados reais)
            sharpe_ratio = np.random.uniform(0.5, 2.0)  # Placeholder
            max_drawdown = np.random.uniform(0.05, 0.20)  # Placeholder
            total_trades = len(y_val)
            win_rate = accuracy * 100
            avg_return = np.mean(predictions)
            volatility = np.std(predictions)
            
            metrics = ModelPerformanceMetrics(
                timestamp=datetime.now(),
                model_version=self.current_model_version,
                accuracy=accuracy,
                precision=precision,
                recall=recall,
                f1_score=f1,
                loss=val_loss,
                val_loss=val_loss,
                sharpe_ratio=sharpe_ratio,
                max_drawdown=max_drawdown,
                total_trades=total_trades,
                win_rate=win_rate,
                avg_return=avg_return,
                volatility=volatility
            )
            
            logger.info(f"Validação concluída - F1: {f1:.3f}, Accuracy: {accuracy:.3f}")
            return metrics
            
        except Exception as e:
            logger.error(f"Erro na validação do modelo: {e}")
            raise
    
    def _should_accept_new_model(self, new_metrics: ModelPerformanceMetrics) -> bool:
        """Decide se deve aceitar o novo modelo"""
        try:
            if len(self.performance_history) == 0:
                logger.info("Primeiro modelo - aceito automaticamente")
                return True
            
            # Comparar com performance recente
            recent_avg = self._get_recent_average_performance(days=14)
            
            # Critérios de aceitação
            f1_improvement = new_metrics.f1_score > recent_avg.f1_score
            accuracy_improvement = new_metrics.accuracy > recent_avg.accuracy
            loss_improvement = new_metrics.val_loss < recent_avg.val_loss
            
            # Aceitar se pelo menos 2 de 3 métricas melhoraram
            improvements = sum([f1_improvement, accuracy_improvement, loss_improvement])
            
            accept = improvements >= 2
            
            logger.info(f"Decisão de aceitação: {accept} (melhorias: {improvements}/3)")
            logger.info(f"F1: {new_metrics.f1_score:.3f} vs {recent_avg.f1_score:.3f}")
            logger.info(f"Accuracy: {new_metrics.accuracy:.3f} vs {recent_avg.accuracy:.3f}")
            logger.info(f"Loss: {new_metrics.val_loss:.3f} vs {recent_avg.val_loss:.3f}")
            
            return accept
            
        except Exception as e:
            logger.error(f"Erro na decisão de aceitação: {e}")
            return False
    
    def _get_recent_average_performance(self, days: int = 7) -> ModelPerformanceMetrics:
        """Calcula performance média recente"""
        cutoff_date = datetime.now() - timedelta(days=days)
        recent_metrics = [m for m in self.performance_history if m.timestamp >= cutoff_date]
        
        if not recent_metrics:
            # Usar última métrica disponível
            recent_metrics = self.performance_history[-1:] if self.performance_history else []
        
        if not recent_metrics:
            # Retornar métricas padrão se não houver histórico
            return ModelPerformanceMetrics(
                timestamp=datetime.now(),
                model_version="baseline",
                accuracy=0.5,
                precision=0.5,
                recall=0.5,
                f1_score=0.5,
                loss=1.0,
                val_loss=1.0,
                sharpe_ratio=0.0,
                max_drawdown=0.2,
                total_trades=0,
                win_rate=50.0,
                avg_return=0.0,
                volatility=0.1
            )
        
        # Calcular médias
        avg_metrics = ModelPerformanceMetrics(
            timestamp=datetime.now(),
            model_version="average",
            accuracy=np.mean([m.accuracy for m in recent_metrics]),
            precision=np.mean([m.precision for m in recent_metrics]),
            recall=np.mean([m.recall for m in recent_metrics]),
            f1_score=np.mean([m.f1_score for m in recent_metrics]),
            loss=np.mean([m.loss for m in recent_metrics]),
            val_loss=np.mean([m.val_loss for m in recent_metrics]),
            sharpe_ratio=np.mean([m.sharpe_ratio for m in recent_metrics]),
            max_drawdown=np.mean([m.max_drawdown for m in recent_metrics]),
            total_trades=int(np.mean([m.total_trades for m in recent_metrics])),
            win_rate=np.mean([m.win_rate for m in recent_metrics]),
            avg_return=np.mean([m.avg_return for m in recent_metrics]),
            volatility=np.mean([m.volatility for m in recent_metrics])
        )
        
        return avg_metrics
    
    def _backup_current_model(self):
        """Faz backup do modelo atual"""
        try:
            current_model_path = self.models_dir / f"model_{self.current_model_version}.pkl"
            
            if current_model_path.exists():
                backup_path = self.backups_dir / f"model_{self.current_model_version}_backup.pkl"
                
                # Copiar modelo
                import shutil
                shutil.copy2(current_model_path, backup_path)
                
                # Salvar também o modelo TensorFlow
                tf_model_path = self.models_dir / f"best_model_{self.current_model_version}.h5"
                if tf_model_path.exists():
                    tf_backup_path = self.backups_dir / f"best_model_{self.current_model_version}_backup.h5"
                    shutil.copy2(tf_model_path, tf_backup_path)
                
                logger.info(f"Backup do modelo {self.current_model_version} criado")
            
        except Exception as e:
            logger.error(f"Erro ao fazer backup do modelo: {e}")
    
    def _deploy_new_model(self):
        """Implanta o novo modelo"""
        try:
            # Salvar modelo atual
            model_path = self.models_dir / f"model_{self.current_model_version}.pkl"
            
            with open(model_path, 'wb') as f:
                pickle.dump(self.ai_model, f)
            
            # Atualizar referência no sistema
            self.ai_model.model_version = self.current_model_version
            
            # Salvar metadados
            metadata = {
                'version': self.current_model_version,
                'timestamp': datetime.now().isoformat(),
                'config': asdict(self.config)
            }
            
            metadata_path = self.models_dir / f"metadata_{self.current_model_version}.json"
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            logger.info(f"Novo modelo implantado: {self.current_model_version}")
            
        except Exception as e:
            logger.error(f"Erro ao implantar novo modelo: {e}")
            raise
    
    def _rollback_to_previous_model(self, previous_version: str):
        """Faz rollback para versão anterior"""
        try:
            backup_path = self.backups_dir / f"model_{previous_version}_backup.pkl"
            
            if backup_path.exists():
                # Carregar modelo anterior
                with open(backup_path, 'rb') as f:
                    self.ai_model = pickle.load(f)
                
                self.current_model_version = previous_version
                logger.info(f"Rollback executado para versão: {previous_version}")
            else:
                logger.error(f"Backup não encontrado para versão: {previous_version}")
                
        except Exception as e:
            logger.error(f"Erro durante rollback: {e}")
    
    def _backup_models(self):
        """Faz backup periódico e limpa modelos antigos"""
        try:
            # Listar todos os modelos
            model_files = list(self.models_dir.glob("model_v*.pkl"))
            model_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
            
            # Manter apenas os N modelos mais recentes
            if len(model_files) > self.config.backup_models_count:
                for old_model in model_files[self.config.backup_models_count:]:
                    old_model.unlink()
                    logger.info(f"Modelo antigo removido: {old_model.name}")
            
            logger.info("Backup e limpeza de modelos concluída")
            
        except Exception as e:
            logger.error(f"Erro no backup de modelos: {e}")
    
    def _calculate_current_performance(self) -> ModelPerformanceMetrics:
        """Calcula performance atual do modelo"""
        try:
            # Em produção, isso seria baseado em trades reais
            # Por agora, simular métricas baseadas em dados recentes
            
            # Obter dados recentes para validação
            recent_data = self._get_recent_validation_data()
            
            if recent_data.empty:
                # Retornar métricas padrão se não houver dados
                return ModelPerformanceMetrics(
                    timestamp=datetime.now(),
                    model_version=self.current_model_version,
                    accuracy=0.5,
                    precision=0.5,
                    recall=0.5,
                    f1_score=0.5,
                    loss=1.0,
                    val_loss=1.0,
                    sharpe_ratio=0.0,
                    max_drawdown=0.2,
                    total_trades=0,
                    win_rate=50.0,
                    avg_return=0.0,
                    volatility=0.1
                )
            
            # Preparar dados e fazer predições
            X, y = self.ai_model.prepare_data(recent_data)
            predictions = self.ai_model.predict(X)
            
            # Calcular métricas (simplificado)
            accuracy = np.random.uniform(0.4, 0.8)  # Placeholder
            precision = np.random.uniform(0.4, 0.8)  # Placeholder
            recall = np.random.uniform(0.4, 0.8)  # Placeholder
            f1 = (2 * precision * recall) / (precision + recall)
            
            return ModelPerformanceMetrics(
                timestamp=datetime.now(),
                model_version=self.current_model_version,
                accuracy=accuracy,
                precision=precision,
                recall=recall,
                f1_score=f1,
                loss=np.random.uniform(0.3, 1.0),
                val_loss=np.random.uniform(0.3, 1.0),
                sharpe_ratio=np.random.uniform(0.5, 2.0),
                max_drawdown=np.random.uniform(0.05, 0.20),
                total_trades=len(predictions),
                win_rate=accuracy * 100,
                avg_return=np.mean(predictions),
                volatility=np.std(predictions)
            )
            
        except Exception as e:
            logger.error(f"Erro ao calcular performance atual: {e}")
            # Retornar métricas padrão em caso de erro
            return ModelPerformanceMetrics(
                timestamp=datetime.now(),
                model_version=self.current_model_version,
                accuracy=0.5,
                precision=0.5,
                recall=0.5,
                f1_score=0.5,
                loss=1.0,
                val_loss=1.0,
                sharpe_ratio=0.0,
                max_drawdown=0.2,
                total_trades=0,
                win_rate=50.0,
                avg_return=0.0,
                volatility=0.1
            )
    
    def _get_recent_validation_data(self) -> pd.DataFrame:
        """Obtém dados recentes para validação"""
        try:
            # Obter dados dos últimos 7 dias
            end_date = datetime.now()
            start_date = end_date - timedelta(days=7)
            
            symbols = config.data.symbols
            all_data = []
            
            for symbol in symbols:
                data = db_manager.get_market_data(
                    symbol=symbol,
                    start_date=start_date,
                    end_date=end_date
                )
                
                if not data.empty:
                    data['symbol'] = symbol
                    all_data.append(data)
            
            if all_data:
                return pd.concat(all_data, ignore_index=True)
            else:
                return pd.DataFrame()
                
        except Exception as e:
            logger.error(f"Erro ao obter dados de validação: {e}")
            return pd.DataFrame()
    
    def _save_performance_metrics(self, metrics: ModelPerformanceMetrics):
        """Salva métricas de performance no banco"""
        try:
            db_manager.save_model_performance(metrics.to_dict())
            logger.debug(f"Métricas salvas para modelo {metrics.model_version}")
        except Exception as e:
            logger.error(f"Erro ao salvar métricas: {e}")
    
    def get_performance_history(self, days: int = 30) -> List[ModelPerformanceMetrics]:
        """Obtém histórico de performance"""
        cutoff_date = datetime.now() - timedelta(days=days)
        return [m for m in self.performance_history if m.timestamp >= cutoff_date]
    
    def force_retrain(self) -> bool:
        """Força retreinamento manual"""
        logger.info("Retreinamento manual solicitado")
        return self.retrain_model(reason="manual")
    
    def get_model_info(self) -> Dict[str, Any]:
        """Obtém informações do modelo atual"""
        return {
            'current_version': self.current_model_version,
            'is_running': self.is_running,
            'performance_history_count': len(self.performance_history),
            'last_retrain': self._get_last_training_date().isoformat(),
            'config': asdict(self.config)
        }

# Instância global (será inicializada no main)
model_retraining_system: Optional[ModelRetrainingSystem] = None

def initialize_retraining_system(ai_model: AdvancedAIModel) -> ModelRetrainingSystem:
    """Inicializa o sistema de retreinamento"""
    global model_retraining_system
    model_retraining_system = ModelRetrainingSystem(ai_model)
    return model_retraining_system

