"""
Sistema Avançado de Depuração e Robustez - RoboTrader
Ferramentas completas para debugging, monitoramento e recuperação de falhas.
"""

import os
import sys
import asyncio
import traceback
import inspect
import logging
import json
import time
import psutil
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Callable, Tuple
from dataclasses import dataclass, field, asdict
from functools import wraps, partial
from contextlib import contextmanager, asynccontextmanager
from pathlib import Path
import warnings
import gc
import pickle
import hashlib
from collections import defaultdict, deque
import numpy as np
import pandas as pd

# Monitoramento e profiling
import memory_profiler
import line_profiler
import cProfile
import pstats
from pympler import tracker, muppy, summary

# Análise de código
import ast
import dis
from types import FrameType, TracebackType

# Notificações
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Importações locais
from config import config
from utils import setup_logging

logger = setup_logging(__name__)

@dataclass
class DebugConfig:
    """Configuração do sistema de depuração"""
    # Níveis de logging
    log_level: str = "INFO"
    detailed_logging: bool = True
    performance_logging: bool = True
    
    # Monitoramento de recursos
    monitor_memory: bool = True
    monitor_cpu: bool = True
    monitor_disk: bool = True
    monitor_network: bool = True
    
    # Profiling
    enable_profiling: bool = True
    profile_memory: bool = True
    profile_execution_time: bool = True
    
    # Recuperação de falhas
    auto_recovery: bool = True
    max_recovery_attempts: int = 3
    recovery_delay: float = 5.0
    
    # Alertas
    enable_alerts: bool = True
    alert_email: Optional[str] = None
    alert_thresholds: Dict[str, float] = field(default_factory=lambda: {
        'memory_usage': 80.0,  # %
        'cpu_usage': 90.0,     # %
        'disk_usage': 85.0,    # %
        'error_rate': 5.0      # %
    })
    
    # Debugging avançado
    enable_code_analysis: bool = True
    enable_state_tracking: bool = True
    enable_decision_tracking: bool = True
    
    # Persistência
    save_debug_data: bool = True
    debug_data_retention_days: int = 30

@dataclass
class ErrorInfo:
    """Informações de erro"""
    timestamp: datetime
    error_type: str
    error_message: str
    traceback: str
    function_name: str
    file_name: str
    line_number: int
    context: Dict[str, Any]
    severity: str  # 'low', 'medium', 'high', 'critical'
    recovery_attempted: bool = False
    recovery_successful: bool = False

@dataclass
class PerformanceMetrics:
    """Métricas de performance"""
    timestamp: datetime
    function_name: str
    execution_time: float
    memory_usage: float
    cpu_usage: float
    memory_delta: float
    call_count: int = 1

@dataclass
class SystemState:
    """Estado do sistema"""
    timestamp: datetime
    memory_usage: float
    cpu_usage: float
    disk_usage: float
    network_io: Dict[str, int]
    active_threads: int
    open_files: int
    database_connections: int
    api_connections: int

@dataclass
class DecisionTrace:
    """Rastreamento de decisões"""
    timestamp: datetime
    function_name: str
    decision_point: str
    inputs: Dict[str, Any]
    outputs: Dict[str, Any]
    confidence: float
    reasoning: str
    execution_path: List[str]

class AdvancedLogger:
    """Logger avançado com contexto e estruturação"""
    
    def __init__(self, config: DebugConfig):
        self.config = config
        self.context_stack = []
        self.structured_logs = []
        
        # Configurar logger
        self.logger = logging.getLogger('RoboTrader.Debug')
        self.logger.setLevel(getattr(logging, config.log_level))
        
        # Handler para arquivo estruturado
        if config.save_debug_data:
            handler = logging.FileHandler('debug_logs.jsonl')
            formatter = logging.Formatter('%(message)s')
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
    
    @contextmanager
    def context(self, **kwargs):
        """Context manager para adicionar contexto aos logs"""
        self.context_stack.append(kwargs)
        try:
            yield
        finally:
            self.context_stack.pop()
    
    def log_structured(self, level: str, message: str, **kwargs):
        """Log estruturado com contexto"""
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'level': level,
            'message': message,
            'context': dict(kwargs),
            'stack_context': self.context_stack.copy()
        }
        
        self.structured_logs.append(log_entry)
        
        if self.config.save_debug_data:
            self.logger.info(json.dumps(log_entry))
    
    def debug(self, message: str, **kwargs):
        self.log_structured('DEBUG', message, **kwargs)
    
    def info(self, message: str, **kwargs):
        self.log_structured('INFO', message, **kwargs)
    
    def warning(self, message: str, **kwargs):
        self.log_structured('WARNING', message, **kwargs)
    
    def error(self, message: str, **kwargs):
        self.log_structured('ERROR', message, **kwargs)
    
    def critical(self, message: str, **kwargs):
        self.log_structured('CRITICAL', message, **kwargs)

class MemoryProfiler:
    """Profiler de memória avançado"""
    
    def __init__(self):
        self.tracker = tracker.SummaryTracker()
        self.snapshots = []
        self.baseline = None
    
    def take_snapshot(self, label: str = ""):
        """Tira snapshot da memória"""
        snapshot = {
            'timestamp': datetime.now(),
            'label': label,
            'memory_usage': psutil.Process().memory_info().rss / 1024 / 1024,  # MB
            'objects': muppy.get_objects()
        }
        
        self.snapshots.append(snapshot)
        return snapshot
    
    def set_baseline(self):
        """Define baseline de memória"""
        self.baseline = self.take_snapshot("baseline")
    
    def compare_to_baseline(self) -> Dict[str, Any]:
        """Compara com baseline"""
        if not self.baseline:
            return {}
        
        current = self.take_snapshot("current")
        
        memory_diff = current['memory_usage'] - self.baseline['memory_usage']
        
        # Análise de objetos
        diff = summary.get_diff(self.baseline['objects'], current['objects'])
        
        return {
            'memory_diff_mb': memory_diff,
            'object_diff': summary.format_(diff),
            'current_usage': current['memory_usage'],
            'baseline_usage': self.baseline['memory_usage']
        }
    
    def get_top_consumers(self, n: int = 10) -> List[Dict[str, Any]]:
        """Obtém top consumidores de memória"""
        if not self.snapshots:
            return []
        
        latest = self.snapshots[-1]
        summ = summary.summarize(latest['objects'])
        
        return [
            {
                'type': row[0],
                'count': row[1],
                'size_mb': row[2] / 1024 / 1024
            }
            for row in summ[:n]
        ]

class PerformanceProfiler:
    """Profiler de performance"""
    
    def __init__(self):
        self.metrics = defaultdict(list)
        self.active_profiles = {}
        self.call_graph = defaultdict(list)
    
    @contextmanager
    def profile_function(self, function_name: str):
        """Context manager para profiling de função"""
        start_time = time.time()
        start_memory = psutil.Process().memory_info().rss
        start_cpu = psutil.cpu_percent()
        
        try:
            yield
        finally:
            end_time = time.time()
            end_memory = psutil.Process().memory_info().rss
            end_cpu = psutil.cpu_percent()
            
            metrics = PerformanceMetrics(
                timestamp=datetime.now(),
                function_name=function_name,
                execution_time=end_time - start_time,
                memory_usage=end_memory / 1024 / 1024,  # MB
                cpu_usage=end_cpu,
                memory_delta=(end_memory - start_memory) / 1024 / 1024  # MB
            )
            
            self.metrics[function_name].append(metrics)
    
    def get_function_stats(self, function_name: str) -> Dict[str, Any]:
        """Obtém estatísticas de uma função"""
        if function_name not in self.metrics:
            return {}
        
        metrics_list = self.metrics[function_name]
        execution_times = [m.execution_time for m in metrics_list]
        memory_usage = [m.memory_usage for m in metrics_list]
        memory_deltas = [m.memory_delta for m in metrics_list]
        
        return {
            'call_count': len(metrics_list),
            'avg_execution_time': np.mean(execution_times),
            'max_execution_time': np.max(execution_times),
            'min_execution_time': np.min(execution_times),
            'std_execution_time': np.std(execution_times),
            'avg_memory_usage': np.mean(memory_usage),
            'max_memory_usage': np.max(memory_usage),
            'avg_memory_delta': np.mean(memory_deltas),
            'total_memory_allocated': np.sum([d for d in memory_deltas if d > 0])
        }
    
    def get_slowest_functions(self, n: int = 10) -> List[Tuple[str, float]]:
        """Obtém funções mais lentas"""
        function_times = []
        
        for func_name, metrics_list in self.metrics.items():
            avg_time = np.mean([m.execution_time for m in metrics_list])
            function_times.append((func_name, avg_time))
        
        return sorted(function_times, key=lambda x: x[1], reverse=True)[:n]
    
    def get_memory_hungry_functions(self, n: int = 10) -> List[Tuple[str, float]]:
        """Obtém funções que mais consomem memória"""
        function_memory = []
        
        for func_name, metrics_list in self.metrics.items():
            total_allocated = np.sum([m.memory_delta for m in metrics_list if m.memory_delta > 0])
            function_memory.append((func_name, total_allocated))
        
        return sorted(function_memory, key=lambda x: x[1], reverse=True)[:n]

class ErrorTracker:
    """Rastreador de erros avançado"""
    
    def __init__(self, config: DebugConfig):
        self.config = config
        self.errors = []
        self.error_patterns = defaultdict(int)
        self.recovery_strategies = {}
    
    def track_error(self, error: Exception, context: Dict[str, Any] = None) -> ErrorInfo:
        """Rastreia um erro"""
        tb = traceback.extract_tb(error.__traceback__)
        last_frame = tb[-1] if tb else None
        
        error_info = ErrorInfo(
            timestamp=datetime.now(),
            error_type=type(error).__name__,
            error_message=str(error),
            traceback=traceback.format_exc(),
            function_name=last_frame.name if last_frame else "unknown",
            file_name=last_frame.filename if last_frame else "unknown",
            line_number=last_frame.lineno if last_frame else 0,
            context=context or {},
            severity=self._classify_error_severity(error)
        )
        
        self.errors.append(error_info)
        
        # Atualizar padrões de erro
        error_pattern = f"{error_info.error_type}:{error_info.function_name}"
        self.error_patterns[error_pattern] += 1
        
        return error_info
    
    def _classify_error_severity(self, error: Exception) -> str:
        """Classifica severidade do erro"""
        critical_errors = (SystemExit, KeyboardInterrupt, MemoryError, OSError)
        high_errors = (ValueError, TypeError, AttributeError, ImportError)
        medium_errors = (RuntimeError, IndexError, KeyError)
        
        if isinstance(error, critical_errors):
            return "critical"
        elif isinstance(error, high_errors):
            return "high"
        elif isinstance(error, medium_errors):
            return "medium"
        else:
            return "low"
    
    def get_error_statistics(self) -> Dict[str, Any]:
        """Obtém estatísticas de erros"""
        if not self.errors:
            return {}
        
        total_errors = len(self.errors)
        recent_errors = [e for e in self.errors if e.timestamp > datetime.now() - timedelta(hours=24)]
        
        severity_counts = defaultdict(int)
        for error in self.errors:
            severity_counts[error.severity] += 1
        
        most_common_patterns = sorted(
            self.error_patterns.items(),
            key=lambda x: x[1],
            reverse=True
        )[:10]
        
        return {
            'total_errors': total_errors,
            'recent_errors_24h': len(recent_errors),
            'error_rate_24h': len(recent_errors) / 24,  # errors per hour
            'severity_distribution': dict(severity_counts),
            'most_common_patterns': most_common_patterns,
            'recovery_success_rate': self._calculate_recovery_rate()
        }
    
    def _calculate_recovery_rate(self) -> float:
        """Calcula taxa de sucesso de recuperação"""
        recovery_attempts = [e for e in self.errors if e.recovery_attempted]
        if not recovery_attempts:
            return 0.0
        
        successful_recoveries = [e for e in recovery_attempts if e.recovery_successful]
        return len(successful_recoveries) / len(recovery_attempts) * 100

class StateTracker:
    """Rastreador de estado do sistema"""
    
    def __init__(self):
        self.state_history = deque(maxlen=1000)
        self.state_snapshots = {}
        self.anomaly_detector = None
    
    def capture_state(self, label: str = "") -> SystemState:
        """Captura estado atual do sistema"""
        process = psutil.Process()
        
        # Informações de rede
        net_io = psutil.net_io_counters()
        network_io = {
            'bytes_sent': net_io.bytes_sent,
            'bytes_recv': net_io.bytes_recv,
            'packets_sent': net_io.packets_sent,
            'packets_recv': net_io.packets_recv
        }
        
        state = SystemState(
            timestamp=datetime.now(),
            memory_usage=process.memory_percent(),
            cpu_usage=process.cpu_percent(),
            disk_usage=psutil.disk_usage('/').percent,
            network_io=network_io,
            active_threads=threading.active_count(),
            open_files=len(process.open_files()),
            database_connections=0,  # Será implementado com integração do DB
            api_connections=0        # Será implementado com monitoramento de APIs
        )
        
        self.state_history.append(state)
        
        if label:
            self.state_snapshots[label] = state
        
        return state
    
    def detect_anomalies(self) -> List[Dict[str, Any]]:
        """Detecta anomalias no estado do sistema"""
        if len(self.state_history) < 10:
            return []
        
        anomalies = []
        recent_states = list(self.state_history)[-10:]
        
        # Análise de memória
        memory_values = [s.memory_usage for s in recent_states]
        memory_mean = np.mean(memory_values)
        memory_std = np.std(memory_values)
        
        current_memory = recent_states[-1].memory_usage
        if abs(current_memory - memory_mean) > 2 * memory_std:
            anomalies.append({
                'type': 'memory_anomaly',
                'current_value': current_memory,
                'expected_range': (memory_mean - 2*memory_std, memory_mean + 2*memory_std),
                'severity': 'high' if current_memory > memory_mean + 2*memory_std else 'medium'
            })
        
        # Análise de CPU
        cpu_values = [s.cpu_usage for s in recent_states]
        cpu_mean = np.mean(cpu_values)
        cpu_std = np.std(cpu_values)
        
        current_cpu = recent_states[-1].cpu_usage
        if abs(current_cpu - cpu_mean) > 2 * cpu_std:
            anomalies.append({
                'type': 'cpu_anomaly',
                'current_value': current_cpu,
                'expected_range': (cpu_mean - 2*cpu_std, cpu_mean + 2*cpu_std),
                'severity': 'high' if current_cpu > cpu_mean + 2*cpu_std else 'medium'
            })
        
        return anomalies
    
    def get_state_trends(self, hours: int = 24) -> Dict[str, Any]:
        """Obtém tendências do estado do sistema"""
        cutoff_time = datetime.now() - timedelta(hours=hours)
        recent_states = [s for s in self.state_history if s.timestamp > cutoff_time]
        
        if not recent_states:
            return {}
        
        memory_values = [s.memory_usage for s in recent_states]
        cpu_values = [s.cpu_usage for s in recent_states]
        disk_values = [s.disk_usage for s in recent_states]
        
        return {
            'memory_trend': {
                'min': min(memory_values),
                'max': max(memory_values),
                'avg': np.mean(memory_values),
                'current': memory_values[-1],
                'trend': 'increasing' if memory_values[-1] > memory_values[0] else 'decreasing'
            },
            'cpu_trend': {
                'min': min(cpu_values),
                'max': max(cpu_values),
                'avg': np.mean(cpu_values),
                'current': cpu_values[-1],
                'trend': 'increasing' if cpu_values[-1] > cpu_values[0] else 'decreasing'
            },
            'disk_trend': {
                'min': min(disk_values),
                'max': max(disk_values),
                'avg': np.mean(disk_values),
                'current': disk_values[-1],
                'trend': 'increasing' if disk_values[-1] > disk_values[0] else 'decreasing'
            }
        }

class DecisionTracker:
    """Rastreador de decisões do sistema"""
    
    def __init__(self):
        self.decisions = []
        self.decision_patterns = defaultdict(list)
    
    def track_decision(self, function_name: str, decision_point: str,
                      inputs: Dict[str, Any], outputs: Dict[str, Any],
                      confidence: float, reasoning: str) -> DecisionTrace:
        """Rastreia uma decisão"""
        # Capturar stack trace para execution path
        stack = inspect.stack()
        execution_path = [f"{frame.filename}:{frame.function}:{frame.lineno}" for frame in stack[1:6]]
        
        decision = DecisionTrace(
            timestamp=datetime.now(),
            function_name=function_name,
            decision_point=decision_point,
            inputs=inputs,
            outputs=outputs,
            confidence=confidence,
            reasoning=reasoning,
            execution_path=execution_path
        )
        
        self.decisions.append(decision)
        self.decision_patterns[decision_point].append(decision)
        
        return decision
    
    def analyze_decision_patterns(self, decision_point: str) -> Dict[str, Any]:
        """Analisa padrões de decisão"""
        decisions = self.decision_patterns.get(decision_point, [])
        
        if not decisions:
            return {}
        
        confidences = [d.confidence for d in decisions]
        
        # Análise de inputs/outputs mais comuns
        input_patterns = defaultdict(int)
        output_patterns = defaultdict(int)
        
        for decision in decisions:
            for key, value in decision.inputs.items():
                input_patterns[f"{key}:{type(value).__name__}"] += 1
            
            for key, value in decision.outputs.items():
                output_patterns[f"{key}:{value}"] += 1
        
        return {
            'total_decisions': len(decisions),
            'avg_confidence': np.mean(confidences),
            'min_confidence': min(confidences),
            'max_confidence': max(confidences),
            'confidence_std': np.std(confidences),
            'common_inputs': sorted(input_patterns.items(), key=lambda x: x[1], reverse=True)[:5],
            'common_outputs': sorted(output_patterns.items(), key=lambda x: x[1], reverse=True)[:5],
            'recent_decisions': len([d for d in decisions if d.timestamp > datetime.now() - timedelta(hours=1)])
        }

class RecoveryManager:
    """Gerenciador de recuperação de falhas"""
    
    def __init__(self, config: DebugConfig):
        self.config = config
        self.recovery_strategies = {}
        self.recovery_history = []
    
    def register_recovery_strategy(self, error_type: str, strategy: Callable):
        """Registra estratégia de recuperação para tipo de erro"""
        self.recovery_strategies[error_type] = strategy
    
    async def attempt_recovery(self, error_info: ErrorInfo) -> bool:
        """Tenta recuperar de um erro"""
        if not self.config.auto_recovery:
            return False
        
        error_type = error_info.error_type
        
        if error_type not in self.recovery_strategies:
            logger.warning(f"Nenhuma estratégia de recuperação para {error_type}")
            return False
        
        strategy = self.recovery_strategies[error_type]
        
        for attempt in range(self.config.max_recovery_attempts):
            try:
                logger.info(f"Tentativa de recuperação {attempt + 1}/{self.config.max_recovery_attempts}")
                
                # Executar estratégia de recuperação
                if asyncio.iscoroutinefunction(strategy):
                    success = await strategy(error_info)
                else:
                    success = strategy(error_info)
                
                if success:
                    logger.info("Recuperação bem-sucedida")
                    error_info.recovery_attempted = True
                    error_info.recovery_successful = True
                    
                    self.recovery_history.append({
                        'timestamp': datetime.now(),
                        'error_type': error_type,
                        'attempt': attempt + 1,
                        'success': True
                    })
                    
                    return True
                
                # Aguardar antes da próxima tentativa
                await asyncio.sleep(self.config.recovery_delay)
                
            except Exception as recovery_error:
                logger.error(f"Erro na recuperação: {recovery_error}")
        
        # Todas as tentativas falharam
        error_info.recovery_attempted = True
        error_info.recovery_successful = False
        
        self.recovery_history.append({
            'timestamp': datetime.now(),
            'error_type': error_type,
            'attempt': self.config.max_recovery_attempts,
            'success': False
        })
        
        return False

class AlertManager:
    """Gerenciador de alertas"""
    
    def __init__(self, config: DebugConfig):
        self.config = config
        self.alert_history = []
        self.alert_cooldowns = defaultdict(datetime)
    
    async def check_and_send_alerts(self, system_state: SystemState, error_stats: Dict[str, Any]):
        """Verifica e envia alertas se necessário"""
        if not self.config.enable_alerts:
            return
        
        alerts_to_send = []
        
        # Verificar thresholds
        thresholds = self.config.alert_thresholds
        
        if system_state.memory_usage > thresholds['memory_usage']:
            alerts_to_send.append({
                'type': 'memory_high',
                'message': f"Uso de memória alto: {system_state.memory_usage:.1f}%",
                'severity': 'high'
            })
        
        if system_state.cpu_usage > thresholds['cpu_usage']:
            alerts_to_send.append({
                'type': 'cpu_high',
                'message': f"Uso de CPU alto: {system_state.cpu_usage:.1f}%",
                'severity': 'high'
            })
        
        if system_state.disk_usage > thresholds['disk_usage']:
            alerts_to_send.append({
                'type': 'disk_high',
                'message': f"Uso de disco alto: {system_state.disk_usage:.1f}%",
                'severity': 'medium'
            })
        
        if error_stats.get('error_rate_24h', 0) > thresholds['error_rate']:
            alerts_to_send.append({
                'type': 'error_rate_high',
                'message': f"Taxa de erro alta: {error_stats['error_rate_24h']:.1f} erros/hora",
                'severity': 'high'
            })
        
        # Enviar alertas (com cooldown)
        for alert in alerts_to_send:
            await self._send_alert_if_needed(alert)
    
    async def _send_alert_if_needed(self, alert: Dict[str, Any]):
        """Envia alerta se não estiver em cooldown"""
        alert_type = alert['type']
        now = datetime.now()
        
        # Verificar cooldown (1 hora)
        if alert_type in self.alert_cooldowns:
            if now - self.alert_cooldowns[alert_type] < timedelta(hours=1):
                return
        
        # Enviar alerta
        await self._send_alert(alert)
        
        # Atualizar cooldown
        self.alert_cooldowns[alert_type] = now
        
        # Registrar histórico
        self.alert_history.append({
            'timestamp': now,
            'type': alert_type,
            'message': alert['message'],
            'severity': alert['severity']
        })
    
    async def _send_alert(self, alert: Dict[str, Any]):
        """Envia alerta por email"""
        if not self.config.alert_email:
            logger.warning("Email de alerta não configurado")
            return
        
        try:
            # Configurar email (usar variáveis de ambiente para credenciais)
            smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
            smtp_port = int(os.getenv('SMTP_PORT', '587'))
            smtp_user = os.getenv('SMTP_USER')
            smtp_password = os.getenv('SMTP_PASSWORD')
            
            if not smtp_user or not smtp_password:
                logger.warning("Credenciais SMTP não configuradas")
                return
            
            # Criar mensagem
            msg = MIMEMultipart()
            msg['From'] = smtp_user
            msg['To'] = self.config.alert_email
            msg['Subject'] = f"RoboTrader Alert: {alert['type']}"
            
            body = f"""
            Alerta do RoboTrader
            
            Tipo: {alert['type']}
            Severidade: {alert['severity']}
            Mensagem: {alert['message']}
            Timestamp: {datetime.now().isoformat()}
            
            Este é um alerta automático do sistema de monitoramento do RoboTrader.
            """
            
            msg.attach(MIMEText(body, 'plain'))
            
            # Enviar email
            server = smtplib.SMTP(smtp_server, smtp_port)
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
            server.quit()
            
            logger.info(f"Alerta enviado: {alert['type']}")
            
        except Exception as e:
            logger.error(f"Erro ao enviar alerta: {e}")

class DebugDecorator:
    """Decorador para debugging automático"""
    
    def __init__(self, debug_system: 'DebugSystem'):
        self.debug_system = debug_system
    
    def __call__(self, func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            function_name = f"{func.__module__}.{func.__name__}"
            
            with self.debug_system.performance_profiler.profile_function(function_name):
                try:
                    result = await func(*args, **kwargs)
                    return result
                except Exception as e:
                    error_info = self.debug_system.error_tracker.track_error(e, {
                        'function': function_name,
                        'args': str(args)[:200],
                        'kwargs': str(kwargs)[:200]
                    })
                    
                    # Tentar recuperação
                    if self.debug_system.config.auto_recovery:
                        recovery_success = await self.debug_system.recovery_manager.attempt_recovery(error_info)
                        if recovery_success:
                            # Tentar executar novamente
                            return await func(*args, **kwargs)
                    
                    raise
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            function_name = f"{func.__module__}.{func.__name__}"
            
            with self.debug_system.performance_profiler.profile_function(function_name):
                try:
                    result = func(*args, **kwargs)
                    return result
                except Exception as e:
                    error_info = self.debug_system.error_tracker.track_error(e, {
                        'function': function_name,
                        'args': str(args)[:200],
                        'kwargs': str(kwargs)[:200]
                    })
                    
                    raise
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

class DebugSystem:
    """Sistema principal de depuração"""
    
    def __init__(self, config: DebugConfig = None):
        self.config = config or DebugConfig()
        
        # Componentes
        self.logger = AdvancedLogger(self.config)
        self.memory_profiler = MemoryProfiler()
        self.performance_profiler = PerformanceProfiler()
        self.error_tracker = ErrorTracker(self.config)
        self.state_tracker = StateTracker()
        self.decision_tracker = DecisionTracker()
        self.recovery_manager = RecoveryManager(self.config)
        self.alert_manager = AlertManager(self.config)
        
        # Decorador
        self.debug_decorator = DebugDecorator(self)
        
        # Estado
        self.monitoring_active = False
        self.monitoring_task = None
        
        # Configurar recuperação padrão
        self._setup_default_recovery_strategies()
    
    def _setup_default_recovery_strategies(self):
        """Configura estratégias de recuperação padrão"""
        
        async def memory_error_recovery(error_info: ErrorInfo) -> bool:
            """Recuperação de erro de memória"""
            logger.info("Tentando recuperar de erro de memória...")
            
            # Forçar garbage collection
            gc.collect()
            
            # Limpar caches se disponível
            if hasattr(self, 'clear_caches'):
                self.clear_caches()
            
            # Verificar se memória foi liberada
            current_memory = psutil.Process().memory_percent()
            if current_memory < 80:  # Threshold arbitrário
                return True
            
            return False
        
        async def connection_error_recovery(error_info: ErrorInfo) -> bool:
            """Recuperação de erro de conexão"""
            logger.info("Tentando recuperar de erro de conexão...")
            
            # Aguardar um pouco antes de tentar reconectar
            await asyncio.sleep(2)
            
            # Aqui seria implementada a lógica específica de reconexão
            # Por exemplo, reinicializar conexões de API, banco de dados, etc.
            
            return True
        
        async def value_error_recovery(error_info: ErrorInfo) -> bool:
            """Recuperação de erro de valor"""
            logger.info("Tentando recuperar de erro de valor...")
            
            # Para erros de valor, geralmente não há recuperação automática
            # Mas podemos logar informações adicionais para debugging
            
            return False
        
        # Registrar estratégias
        self.recovery_manager.register_recovery_strategy('MemoryError', memory_error_recovery)
        self.recovery_manager.register_recovery_strategy('ConnectionError', connection_error_recovery)
        self.recovery_manager.register_recovery_strategy('ValueError', value_error_recovery)
    
    async def start_monitoring(self):
        """Inicia monitoramento contínuo"""
        if self.monitoring_active:
            return
        
        self.monitoring_active = True
        self.monitoring_task = asyncio.create_task(self._monitoring_loop())
        
        # Definir baseline de memória
        self.memory_profiler.set_baseline()
        
        logger.info("Sistema de monitoramento iniciado")
    
    async def stop_monitoring(self):
        """Para monitoramento"""
        self.monitoring_active = False
        
        if self.monitoring_task:
            self.monitoring_task.cancel()
            try:
                await self.monitoring_task
            except asyncio.CancelledError:
                pass
        
        logger.info("Sistema de monitoramento parado")
    
    async def _monitoring_loop(self):
        """Loop principal de monitoramento"""
        while self.monitoring_active:
            try:
                # Capturar estado do sistema
                system_state = self.state_tracker.capture_state()
                
                # Detectar anomalias
                anomalies = self.state_tracker.detect_anomalies()
                if anomalies:
                    self.logger.warning("Anomalias detectadas", anomalies=anomalies)
                
                # Obter estatísticas de erro
                error_stats = self.error_tracker.get_error_statistics()
                
                # Verificar alertas
                await self.alert_manager.check_and_send_alerts(system_state, error_stats)
                
                # Log de status
                if self.config.performance_logging:
                    self.logger.info("Status do sistema", 
                                   memory_usage=system_state.memory_usage,
                                   cpu_usage=system_state.cpu_usage,
                                   disk_usage=system_state.disk_usage,
                                   active_threads=system_state.active_threads)
                
                # Aguardar próximo ciclo
                await asyncio.sleep(60)  # Monitorar a cada minuto
                
            except Exception as e:
                logger.error(f"Erro no loop de monitoramento: {e}")
                await asyncio.sleep(60)
    
    def get_debug_report(self) -> Dict[str, Any]:
        """Gera relatório completo de debug"""
        return {
            'timestamp': datetime.now().isoformat(),
            'system_state': asdict(self.state_tracker.capture_state()),
            'memory_analysis': self.memory_profiler.compare_to_baseline(),
            'top_memory_consumers': self.memory_profiler.get_top_consumers(),
            'performance_stats': {
                'slowest_functions': self.performance_profiler.get_slowest_functions(),
                'memory_hungry_functions': self.performance_profiler.get_memory_hungry_functions()
            },
            'error_statistics': self.error_tracker.get_error_statistics(),
            'state_trends': self.state_tracker.get_state_trends(),
            'recent_alerts': self.alert_manager.alert_history[-10:],
            'recovery_history': self.recovery_manager.recovery_history[-10:]
        }
    
    async def save_debug_report(self, filename: Optional[str] = None):
        """Salva relatório de debug"""
        if not self.config.save_debug_data:
            return
        
        report = self.get_debug_report()
        
        if not filename:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"debug_report_{timestamp}.json"
        
        debug_dir = Path("debug_reports")
        debug_dir.mkdir(exist_ok=True)
        
        with open(debug_dir / filename, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"Relatório de debug salvo: {filename}")
    
    def cleanup_old_data(self):
        """Limpa dados antigos de debug"""
        if not self.config.save_debug_data:
            return
        
        cutoff_date = datetime.now() - timedelta(days=self.config.debug_data_retention_days)
        
        # Limpar erros antigos
        self.error_tracker.errors = [
            e for e in self.error_tracker.errors 
            if e.timestamp > cutoff_date
        ]
        
        # Limpar decisões antigas
        self.decision_tracker.decisions = [
            d for d in self.decision_tracker.decisions 
            if d.timestamp > cutoff_date
        ]
        
        # Limpar alertas antigos
        self.alert_manager.alert_history = [
            a for a in self.alert_manager.alert_history 
            if a['timestamp'] > cutoff_date
        ]
        
        logger.info(f"Dados de debug anteriores a {cutoff_date} foram limpos")

# Instância global
debug_system: Optional[DebugSystem] = None

def initialize_debug_system(config: DebugConfig = None) -> DebugSystem:
    """Inicializa sistema de debug global"""
    global debug_system
    debug_system = DebugSystem(config)
    return debug_system

def get_debug_system() -> Optional[DebugSystem]:
    """Obtém sistema de debug global"""
    return debug_system

# Decoradores de conveniência
def debug_function(func):
    """Decorador para debugging de função"""
    if debug_system:
        return debug_system.debug_decorator(func)
    return func

def track_decision(decision_point: str, confidence: float = 1.0, reasoning: str = ""):
    """Decorador para rastrear decisões"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            inputs = {'args': args, 'kwargs': kwargs}
            result = await func(*args, **kwargs)
            outputs = {'result': result}
            
            if debug_system:
                debug_system.decision_tracker.track_decision(
                    func.__name__, decision_point, inputs, outputs, confidence, reasoning
                )
            
            return result
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            inputs = {'args': args, 'kwargs': kwargs}
            result = func(*args, **kwargs)
            outputs = {'result': result}
            
            if debug_system:
                debug_system.decision_tracker.track_decision(
                    func.__name__, decision_point, inputs, outputs, confidence, reasoning
                )
            
            return result
        
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

@contextmanager
def debug_context(**kwargs):
    """Context manager para adicionar contexto de debug"""
    if debug_system:
        with debug_system.logger.context(**kwargs):
            yield
    else:
        yield

if __name__ == "__main__":
    # Exemplo de uso
    async def main():
        # Configurar sistema de debug
        config = DebugConfig(
            enable_alerts=True,
            alert_email="admin@robotrader.com",
            auto_recovery=True,
            save_debug_data=True
        )
        
        debug_sys = initialize_debug_system(config)
        
        # Iniciar monitoramento
        await debug_sys.start_monitoring()
        
        # Simular algumas operações
        @debug_function
        async def test_function():
            await asyncio.sleep(1)
            return "success"
        
        @track_decision("test_decision", confidence=0.8, reasoning="Test decision")
        async def decision_function():
            return "buy"
        
        # Executar funções de teste
        with debug_context(operation="test", user="system"):
            result1 = await test_function()
            result2 = await decision_function()
        
        # Gerar relatório
        await debug_sys.save_debug_report()
        
        # Parar monitoramento
        await debug_sys.stop_monitoring()
    
    # Executar exemplo
    # asyncio.run(main())

