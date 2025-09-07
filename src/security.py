"""
Módulo de segurança para RoboTrader
Gerencia criptografia, hashing e validação de dados sensíveis.
"""

import os
import base64
import hashlib
import time
from typing import Union, Optional
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import bcrypt
import re

from utils import setup_logging

logger = setup_logging(__name__)

class SecurityManager:
    """Gerenciador de segurança para criptografia e autenticação"""
    
    def __init__(self, encryption_key: Optional[str] = None):
        self._fernet = None
        self._encryption_key_bytes = None
        if encryption_key:
            self._encryption_key_bytes = self._derive_key_from_password(encryption_key)
        else:
            # Gerar chave aleatória se nenhuma for fornecida
            self._encryption_key_bytes = Fernet.generate_key()
            logger.warning("Nenhuma chave de criptografia fornecida. Gerando uma chave temporária. Use uma chave persistente em produção.")

        self._fernet = Fernet(self._encryption_key_bytes)

    def _derive_key_from_password(self, password: str) -> bytes:
        """Deriva uma chave Fernet de uma senha usando PBKDF2HMAC."""
        salt = os.urandom(16) # Gerar um salt aleatório para cada chave
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480000, # Iterações recomendadas para 2023
        )
        key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
        return key
    
    def encrypt_data(self, data: Union[str, bytes]) -> str:
        """
        Criptografa dados.
        
        Args:
            data: Dados para criptografar (string ou bytes).
            
        Returns:
            Dados criptografados em base64 (string).
        """
        if isinstance(data, str):
            data = data.encode("utf-8")
        
        encrypted_data = self._fernet.encrypt(data)
        return encrypted_data.decode("utf-8")
    
    def decrypt_data(self, encrypted_data: str) -> str:
        """
        Descriptografa dados.
        
        Args:
            encrypted_data: Dados criptografados em base64 (string).
            
        Returns:
            Dados descriptografados (string).
        """
        try:
            decrypted_data = self._fernet.decrypt(encrypted_data.encode("utf-8"))
            return decrypted_data.decode("utf-8")
        except Exception as e:
            logger.error(f"Erro ao descriptografar dados: {e}")
            raise ValueError("Dados criptografados inválidos ou chave incorreta.")
    
    def hash_password(self, password: str) -> str:
        """
        Gera hash de senha usando bcrypt.
        
        Args:
            password: Senha em texto plano.
            
        Returns:
            Hash da senha.
        """
        hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt())
        return hashed.decode("utf-8")
    
    def verify_password(self, password: str, hashed: str) -> bool:
        """
        Verifica senha contra hash usando bcrypt.
        
        Args:
            password: Senha em texto plano.
            hashed: Hash da senha.
            
        Returns:
            True se a senha estiver correta, False caso contrário.
        """
        try:
            return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
        except ValueError:
            logger.warning("Hash de senha inválido fornecido para verificação.")
            return False
    
    def generate_api_key(self, length: int = 32) -> str:
        """
        Gera chave de API aleatória e segura.
        
        Args:
            length: Comprimento da chave (padrão: 32).
            
        Returns:
            Chave de API gerada.
        """
        return base64.urlsafe_b64encode(os.urandom(length))[:length].decode("utf-8")
    
    def secure_store_credentials(self, api_key: str, secret_key: str) -> dict:
        """
        Armazena credenciais de forma segura criptografando-as.
        
        Args:
            api_key: Chave da API.
            secret_key: Chave secreta.
            
        Returns:
            Dicionário com credenciais criptografadas e timestamp.
        """
        return {
            "api_key": self.encrypt_data(api_key),
            "secret_key": self.encrypt_data(secret_key),
            "timestamp": int(time.time())
        }
    
    def retrieve_credentials(self, encrypted_credentials: dict) -> dict:
        """
        Recupera credenciais descriptografando-as.
        
        Args:
            encrypted_credentials: Dicionário com credenciais criptografadas.
            
        Returns:
            Dicionário com credenciais descriptografadas.
        """
        return {
            "api_key": self.decrypt_data(encrypted_credentials["api_key"]),
            "secret_key": self.decrypt_data(encrypted_credentials["secret_key"])
        }

    def hash_sensitive_data(self, data: str) -> str:
        """
        Gera hash SHA-256 de dados sensíveis.
        
        Args:
            data: Dados para hash.
            
        Returns:
            Hash SHA-256.
        """
        return hashlib.sha256(data.encode("utf-8")).hexdigest()

    def validate_api_credentials(self, api_key: str, secret_key: str) -> bool:
        """
        Valida o formato básico das credenciais da API.
        
        Args:
            api_key: Chave da API.
            secret_key: Chave secreta.
            
        Returns:
            True se as credenciais estiverem no formato correto, False caso contrário.
        """
        if not api_key or not secret_key:
            logger.warning("API Key ou Secret Key estão vazias.")
            return False
        
        # Validações básicas de comprimento e caracteres
        if len(api_key) < 16 or len(secret_key) < 32: # Comprimentos típicos para chaves de API
            logger.warning("API Key ou Secret Key muito curtas.")
            return False
        
        # Verificar se contém apenas caracteres alfanuméricos (ou outros caracteres permitidos se souber)
        if not re.match(r'^[A-Za-z0-9]+$', api_key):
            logger.warning("API Key contém caracteres inválidos.")
            return False
        
        if not re.match(r'^[A-Za-z0-9]+$', secret_key):
            logger.warning("Secret Key contém caracteres inválidos.")
            return False
        
        return True

# A instância do SecurityManager deve ser inicializada com a chave de criptografia
# Idealmente, a chave deve vir de uma variável de ambiente ou um serviço de gerenciamento de segredos.
# Exemplo: security_manager = SecurityManager(encryption_key=os.getenv("ROBOTRADER_ENCRYPTION_KEY"))
# Para este contexto, vamos usar uma chave gerada aleatoriamente se não for fornecida.
# Em um ambiente de produção, certifique-se de que esta chave seja persistente e segura.
security_manager = SecurityManager(encryption_key=os.getenv("ROBOTRADER_ENCRYPTION_KEY"))

# Funções de conveniência para acesso direto
encrypt_data = security_manager.encrypt_data
decrypt_data = security_manager.decrypt_data
hash_sensitive_data = security_manager.hash_sensitive_data
validate_api_credentials = security_manager.validate_api_credentials


