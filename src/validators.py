"""
Módulo de Validadores para RoboTrader
Fornece funções robustas para validação de dados de entrada.
"""

import re
from typing import Union, List, Optional, Dict, Any
from decimal import Decimal, InvalidOperation
from datetime import datetime

from utils import setup_logging

logger = setup_logging(__name__)

class ValidationError(Exception):
    """Exceção customizada para erros de validação."""
    pass

class DataValidator:
    """
    Classe para centralizar e gerenciar funções de validação de dados.
    """

    @staticmethod
    def validate_symbol(symbol: str) -> str:
        """
        Valida o formato do símbolo de trading (ex: BTC/USDT).
        Retorna o símbolo em maiúsculas se válido, levanta ValidationError caso contrário.
        """
        if not isinstance(symbol, str) or not symbol:
            raise ValidationError("Símbolo deve ser uma string não vazia.")
        
        # Padrão: BASE/QUOTE onde BASE e QUOTE são 2-10 caracteres alfanuméricos
        pattern = r'^[A-Z0-9]{2,10}/[A-Z0-9]{2,10}$'
        upper_symbol = symbol.upper()
        if not re.match(pattern, upper_symbol):
            raise ValidationError(f"Formato de símbolo inválido: {symbol}. Esperado BASE/QUOTE.")
        return upper_symbol

    @staticmethod
    def validate_list_of_symbols(symbols: List[str]) -> List[str]:
        """
        Valida uma lista de símbolos de trading.
        Retorna a lista de símbolos validados, levanta ValidationError caso contrário.
        """
        if not isinstance(symbols, list):
            raise ValidationError("A lista de símbolos deve ser uma lista.")
        
        validated_symbols = []
        for s in symbols:
            try:
                validated_symbols.append(DataValidator.validate_symbol(s))
            except ValidationError as e:
                raise ValidationError(f"Símbolo inválido na lista: {s} - {e}")
        return validated_symbols

    @staticmethod
    def validate_timeframe(timeframe: str) -> str:
        """
        Valida o formato do timeframe (ex: 1m, 5m, 1h, 1d).
        Retorna o timeframe se válido, levanta ValidationError caso contrário.
        """
        if not isinstance(timeframe, str) or not timeframe:
            raise ValidationError("Timeframe deve ser uma string não vazia.")
        
        valid_timeframes = [
            '1m', '3m', '5m', '15m', '30m',
            '1h', '2h', '4h', '6h', '8h', '12h',
            '1d', '3d', '1w', '1M'
        ]
        if timeframe not in valid_timeframes:
            raise ValidationError(f"Timeframe inválido: {timeframe}. Valores permitidos: {', '.join(valid_timeframes)}.")
        return timeframe

    @staticmethod
    def validate_positive_number(value: Union[str, int, float, Decimal], field_name: str = "Valor") -> Union[int, float, Decimal]:
        """
        Valida se um valor é um número positivo.
        Retorna o valor convertido para Decimal, levanta ValidationError caso contrário.
        """
        try:
            decimal_value = Decimal(str(value))
            if decimal_value <= 0:
                raise ValidationError(f"{field_name} deve ser um número positivo.")
            return decimal_value
        except (InvalidOperation, ValueError, TypeError):
            raise ValidationError(f"{field_name} inválido: {value}. Esperado um número positivo.")

    @staticmethod
    def validate_percentage(percentage: Union[str, int, float], field_name: str = "Porcentagem") -> float:
        """
        Valida se um valor é uma porcentagem válida (0-100).
        Retorna o valor como float, levanta ValidationError caso contrário.
        """
        try:
            value = float(percentage)
            if not (0 <= value <= 100):
                raise ValidationError(f"{field_name} deve estar entre 0 e 100. Recebido: {value}.")
            return value
        except (ValueError, TypeError):
            raise ValidationError(f"{field_name} inválida: {percentage}. Esperado um número entre 0 e 100.")

    @staticmethod
    def validate_confidence(confidence: Union[str, int, float]) -> float:
        """
        Valida o nível de confiança (0-100).
        Retorna o valor como float, levanta ValidationError caso contrário.
        """
        return DataValidator.validate_percentage(confidence, field_name="Confiança")

    @staticmethod
    def validate_email(email: str) -> str:
        """
        Valida o formato de email.
        Retorna o email se válido, levanta ValidationError caso contrário.
        """
        if not isinstance(email, str) or not email:
            raise ValidationError("Email deve ser uma string não vazia.")
        
        pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(pattern, email):
            raise ValidationError(f"Formato de email inválido: {email}.")
        return email

    @staticmethod
    def validate_trading_signal(signal: str) -> str:
        """
        Valida um sinal de trading (buy, sell, hold).
        Retorna o sinal em minúsculas se válido, levanta ValidationError caso contrário.
        """
        if not isinstance(signal, str) or not signal:
            raise ValidationError("Sinal de trading deve ser uma string não vazia.")
        
        valid_signals = ['buy', 'sell', 'hold']
        lower_signal = signal.lower()
        if lower_signal not in valid_signals:
            raise ValidationError(f"Sinal de trading inválido: {signal}. Esperado 'buy', 'sell' ou 'hold'.")
        return lower_signal

    @staticmethod
    def validate_order_type(order_type: str) -> str:
        """
        Valida o tipo de ordem (market, limit, stop, stop_limit).
        Retorna o tipo de ordem em minúsculas se válido, levanta ValidationError caso contrário.
        """
        if not isinstance(order_type, str) or not order_type:
            raise ValidationError("Tipo de ordem deve ser uma string não vazia.")
        
        valid_types = ['market', 'limit', 'stop', 'stop_limit']
        lower_order_type = order_type.lower()
        if lower_order_type not in valid_types:
            raise ValidationError(f"Tipo de ordem inválido: {order_type}. Esperado 'market', 'limit', 'stop' ou 'stop_limit'.")
        return lower_order_type

    @staticmethod
    def validate_risk_level(risk_level: Union[str, int]) -> int:
        """
        Valida o nível de risco (1-5).
        Retorna o nível de risco como int, levanta ValidationError caso contrário.
        """
        try:
            level = int(risk_level)
            if not (1 <= level <= 5):
                raise ValidationError(f"Nível de risco inválido: {risk_level}. Esperado um inteiro entre 1 e 5.")
            return level
        except (ValueError, TypeError):
            raise ValidationError(f"Nível de risco inválido: {risk_level}. Esperado um inteiro.")

    @staticmethod
    def validate_portfolio_allocation(allocations: Dict[str, Union[int, float]]) -> Dict[str, float]:
        """
        Valida a alocação de portfólio (soma das porcentagens deve ser ~100%).
        Retorna o dicionário de alocações com porcentagens como float, levanta ValidationError caso contrário.
        """
        if not isinstance(allocations, dict):
            raise ValidationError("Alocação de portfólio deve ser um dicionário.")
        
        total_allocation = 0.0
        validated_allocations = {}
        for symbol, allocation in allocations.items():
            DataValidator.validate_symbol(symbol) # Valida cada símbolo
            validated_percentage = DataValidator.validate_percentage(allocation, field_name=f"Alocação para {symbol}")
            validated_allocations[symbol] = validated_percentage
            total_allocation += validated_percentage
        
        if not (99.0 <= total_allocation <= 101.0): # Permitir pequena margem de erro de float
            raise ValidationError(f"A soma das alocações do portfólio deve ser aproximadamente 100%. Recebido: {total_allocation:.2f}%")
        return validated_allocations

    @staticmethod
    def validate_date_range(start_date_str: str, end_date_str: str, date_format: str = '%Y-%m-%d') -> Tuple[datetime, datetime]:
        """
        Valida um intervalo de datas.
        Retorna um tuple de objetos datetime, levanta ValidationError caso contrário.
        """
        try:
            start_date = datetime.strptime(start_date_str, date_format)
            end_date = datetime.strptime(end_date_str, date_format)
            
            if start_date > end_date:
                raise ValidationError("Data inicial não pode ser posterior à data final.")
            return start_date, end_date
        except ValueError:
            raise ValidationError(f"Formato de data inválido. Esperado {date_format}. Recebido: {start_date_str}, {end_date_str}.")

    @staticmethod
    def sanitize_input(input_str: str, max_length: int = 255) -> str:
        """
        Sanitiza uma string de entrada para prevenir injeção e limitar comprimento.
        """
        if not isinstance(input_str, str):
            logger.warning(f"Input não é string, convertendo para vazio: {input_str}")
            return ""
        
        # Remover caracteres que podem ser usados em ataques de injeção (SQL, XSS, etc.)
        # Mantém caracteres alfanuméricos, espaços, e alguns símbolos comuns em texto.
        sanitized = re.sub(r'[^a-zA-Z0-9\s.,!?-]', '', input_str)
        
        # Limitar comprimento
        sanitized = sanitized[:max_length]
        
        # Remover múltiplos espaços e trim
        sanitized = ' '.join(sanitized.split()).strip()
        
        return sanitized

    @staticmethod
    def validate_required_fields(data: Dict[str, Any], required_fields: List[str]) -> None:
        """
        Valida a presença de campos obrigatórios em um dicionário.
        Levanta ValidationError se algum campo estiver ausente ou vazio.
        """
        missing_fields = []
        for field in required_fields:
            if field not in data or data[field] is None or (isinstance(data[field], str) and not data[field].strip()):
                missing_fields.append(field)
        
        if missing_fields:
            raise ValidationError(f"Campos obrigatórios ausentes ou vazios: {', '.join(missing_fields)}.")

    @staticmethod
    def validate_data_types(data: Dict[str, Any], type_mapping: Dict[str, type]) -> None:
        """
        Valida os tipos de dados de campos em um dicionário.
        Levanta ValidationError se algum tipo estiver incorreto.
        """
        type_errors = []
        for field, expected_type in type_mapping.items():
            if field in data and not isinstance(data[field], expected_type):
                type_errors.append(f"{field}: esperado {expected_type.__name__}, recebido {type(data[field]).__name__}")
        
        if type_errors:
            raise ValidationError(f"Tipos de dados incorretos: {'; '.join(type_errors)}.")

# Instância global para acesso fácil
validator = DataValidator()


