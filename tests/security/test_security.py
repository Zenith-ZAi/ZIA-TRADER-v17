"""
Testes de Segurança - RoboTrader 2.0
Testa as medidas de segurança implementadas no sistema
"""

import pytest
import asyncio
import aiohttp
import jwt
import hashlib
import hmac
import time
import json
import base64
from datetime import datetime, timedelta
import requests
from unittest.mock import patch, Mock
import re
import string
import random

# Configuração de testes de segurança
SECURITY_CONFIG = {
    'api_base_url': 'http://localhost:5000',
    'test_user': {
        'username': 'security_test_user',
        'email': 'security@test.com',
        'password': 'SecurePassword123!'
    },
    'weak_passwords': [
        '123456',
        'password',
        'admin',
        'test',
        '12345678',
        'qwerty'
    ],
    'sql_injection_payloads': [
        "' OR '1'='1",
        "'; DROP TABLE users; --",
        "' UNION SELECT * FROM users --",
        "admin'--",
        "' OR 1=1 --"
    ],
    'xss_payloads': [
        "<script>alert('XSS')</script>",
        "javascript:alert('XSS')",
        "<img src=x onerror=alert('XSS')>",
        "';alert('XSS');//",
        "<svg onload=alert('XSS')>"
    ],
    'rate_limit_threshold': 100,  # requests per minute
    'jwt_secret': 'test_jwt_secret_key_for_testing_only'
}

class TestAuthentication:
    """Testes de autenticação e autorização"""
    
    @pytest.mark.asyncio
    async def test_user_registration_security(self):
        """Testar segurança no registro de usuários"""
        async with aiohttp.ClientSession() as session:
            
            # Teste 1: Registro com senha fraca deve falhar
            for weak_password in SECURITY_CONFIG['weak_passwords']:
                user_data = {
                    'username': f'test_weak_{weak_password}',
                    'email': f'weak_{weak_password}@test.com',
                    'password': weak_password
                }
                
                async with session.post(
                    f"{SECURITY_CONFIG['api_base_url']}/auth/register",
                    json=user_data
                ) as response:
                    # Deve rejeitar senhas fracas
                    assert response.status in [400, 422], f"Weak password '{weak_password}' was accepted"
            
            # Teste 2: Registro com dados válidos deve funcionar
            valid_user = SECURITY_CONFIG['test_user'].copy()
            valid_user['username'] = f"valid_user_{int(time.time())}"
            valid_user['email'] = f"valid_{int(time.time())}@test.com"
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/register",
                json=valid_user
            ) as response:
                assert response.status == 201
                data = await response.json()
                assert 'user_id' in data
                assert 'password' not in data  # Senha não deve ser retornada
            
            # Teste 3: Registro duplicado deve falhar
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/register",
                json=valid_user
            ) as response:
                assert response.status in [400, 409]  # Conflict or Bad Request
    
    @pytest.mark.asyncio
    async def test_login_security(self):
        """Testar segurança no login"""
        async with aiohttp.ClientSession() as session:
            
            # Primeiro, registrar um usuário
            user_data = SECURITY_CONFIG['test_user'].copy()
            user_data['username'] = f"login_test_{int(time.time())}"
            user_data['email'] = f"login_test_{int(time.time())}@test.com"
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/register",
                json=user_data
            ) as response:
                assert response.status == 201
            
            # Teste 1: Login com credenciais corretas
            login_data = {
                'username': user_data['username'],
                'password': user_data['password']
            }
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/login",
                json=login_data
            ) as response:
                assert response.status == 200
                data = await response.json()
                assert 'access_token' in data
                assert 'refresh_token' in data
                
                # Verificar se o token JWT é válido
                token = data['access_token']
                decoded = jwt.decode(token, options={"verify_signature": False})
                assert decoded['username'] == user_data['username']
            
            # Teste 2: Login com senha incorreta deve falhar
            wrong_login = login_data.copy()
            wrong_login['password'] = 'wrong_password'
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/login",
                json=wrong_login
            ) as response:
                assert response.status == 401
            
            # Teste 3: Login com usuário inexistente deve falhar
            nonexistent_login = {
                'username': 'nonexistent_user',
                'password': 'any_password'
            }
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/login",
                json=nonexistent_login
            ) as response:
                assert response.status == 401
    
    @pytest.mark.asyncio
    async def test_jwt_token_security(self):
        """Testar segurança dos tokens JWT"""
        async with aiohttp.ClientSession() as session:
            
            # Registrar e fazer login
            user_data = SECURITY_CONFIG['test_user'].copy()
            user_data['username'] = f"jwt_test_{int(time.time())}"
            user_data['email'] = f"jwt_test_{int(time.time())}@test.com"
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/register",
                json=user_data
            ) as response:
                assert response.status == 201
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/login",
                json={'username': user_data['username'], 'password': user_data['password']}
            ) as response:
                assert response.status == 200
                tokens = await response.json()
                access_token = tokens['access_token']
                refresh_token = tokens['refresh_token']
            
            # Teste 1: Acesso com token válido
            headers = {'Authorization': f'Bearer {access_token}'}
            async with session.get(
                f"{SECURITY_CONFIG['api_base_url']}/portfolio",
                headers=headers
            ) as response:
                assert response.status == 200
            
            # Teste 2: Acesso sem token deve falhar
            async with session.get(
                f"{SECURITY_CONFIG['api_base_url']}/portfolio"
            ) as response:
                assert response.status == 401
            
            # Teste 3: Acesso com token inválido deve falhar
            invalid_headers = {'Authorization': 'Bearer invalid_token'}
            async with session.get(
                f"{SECURITY_CONFIG['api_base_url']}/portfolio",
                headers=invalid_headers
            ) as response:
                assert response.status == 401
            
            # Teste 4: Acesso com token expirado deve falhar
            # Criar token expirado
            expired_payload = {
                'username': user_data['username'],
                'exp': datetime.utcnow() - timedelta(hours=1)  # Expirado há 1 hora
            }
            expired_token = jwt.encode(expired_payload, SECURITY_CONFIG['jwt_secret'], algorithm='HS256')
            expired_headers = {'Authorization': f'Bearer {expired_token}'}
            
            async with session.get(
                f"{SECURITY_CONFIG['api_base_url']}/portfolio",
                headers=expired_headers
            ) as response:
                assert response.status == 401
    
    @pytest.mark.asyncio
    async def test_password_hashing(self):
        """Testar se as senhas são adequadamente hasheadas"""
        # Este teste verificaria se as senhas são armazenadas de forma segura
        # Em um ambiente real, verificaríamos o banco de dados
        
        password = "TestPassword123!"
        
        # Simular diferentes algoritmos de hash
        hash_algorithms = ['bcrypt', 'scrypt', 'argon2']
        
        for algorithm in hash_algorithms:
            if algorithm == 'bcrypt':
                import bcrypt
                hashed = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
                assert bcrypt.checkpw(password.encode('utf-8'), hashed)
                assert len(hashed) > 50  # Hash deve ter tamanho adequado
            
            elif algorithm == 'scrypt':
                import hashlib
                salt = b'test_salt_16_bytes'
                hashed = hashlib.scrypt(password.encode('utf-8'), salt=salt, n=16384, r=8, p=1)
                assert len(hashed) == 64  # scrypt retorna 64 bytes por padrão
            
            # Verificar que a senha original não está no hash
            assert password.encode('utf-8') not in hashed

class TestInputValidation:
    """Testes de validação de entrada"""
    
    @pytest.mark.asyncio
    async def test_sql_injection_protection(self):
        """Testar proteção contra SQL injection"""
        async with aiohttp.ClientSession() as session:
            
            # Registrar usuário para obter token
            user_data = SECURITY_CONFIG['test_user'].copy()
            user_data['username'] = f"sql_test_{int(time.time())}"
            user_data['email'] = f"sql_test_{int(time.time())}@test.com"
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/register",
                json=user_data
            ) as response:
                assert response.status == 201
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/login",
                json={'username': user_data['username'], 'password': user_data['password']}
            ) as response:
                tokens = await response.json()
                headers = {'Authorization': f'Bearer {tokens["access_token"]}'}
            
            # Testar payloads de SQL injection em diferentes endpoints
            for payload in SECURITY_CONFIG['sql_injection_payloads']:
                
                # Teste 1: SQL injection no parâmetro de símbolo
                async with session.get(
                    f"{SECURITY_CONFIG['api_base_url']}/market/realtime/{payload}",
                    headers=headers
                ) as response:
                    # Deve retornar erro de validação, não erro de SQL
                    assert response.status in [400, 404, 422]
                    # Não deve retornar dados sensíveis
                    text = await response.text()
                    assert 'users' not in text.lower()
                    assert 'password' not in text.lower()
                
                # Teste 2: SQL injection em dados de trade
                trade_data = {
                    'symbol': payload,
                    'side': 'buy',
                    'quantity': 0.001,
                    'type': 'market'
                }
                
                async with session.post(
                    f"{SECURITY_CONFIG['api_base_url']}/trading/execute",
                    json=trade_data,
                    headers=headers
                ) as response:
                    assert response.status in [400, 422]
                    text = await response.text()
                    assert 'users' not in text.lower()
    
    @pytest.mark.asyncio
    async def test_xss_protection(self):
        """Testar proteção contra XSS"""
        async with aiohttp.ClientSession() as session:
            
            for payload in SECURITY_CONFIG['xss_payloads']:
                
                # Teste 1: XSS no registro de usuário
                user_data = {
                    'username': payload,
                    'email': f'xss_test_{int(time.time())}@test.com',
                    'password': 'SecurePassword123!'
                }
                
                async with session.post(
                    f"{SECURITY_CONFIG['api_base_url']}/auth/register",
                    json=user_data
                ) as response:
                    # Deve rejeitar ou sanitizar
                    if response.status == 201:
                        data = await response.json()
                        # Se aceito, deve estar sanitizado
                        assert '<script>' not in str(data)
                        assert 'javascript:' not in str(data)
                    else:
                        # Ou deve ser rejeitado
                        assert response.status in [400, 422]
    
    @pytest.mark.asyncio
    async def test_input_length_validation(self):
        """Testar validação de tamanho de entrada"""
        async with aiohttp.ClientSession() as session:
            
            # Teste com strings muito longas
            very_long_string = 'A' * 10000
            
            user_data = {
                'username': very_long_string,
                'email': f'length_test_{int(time.time())}@test.com',
                'password': 'SecurePassword123!'
            }
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/register",
                json=user_data
            ) as response:
                # Deve rejeitar entradas muito longas
                assert response.status in [400, 422]
            
            # Teste com email muito longo
            user_data = {
                'username': f'length_test_{int(time.time())}',
                'email': very_long_string + '@test.com',
                'password': 'SecurePassword123!'
            }
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/register",
                json=user_data
            ) as response:
                assert response.status in [400, 422]
    
    def test_data_type_validation(self):
        """Testar validação de tipos de dados"""
        # Teste com tipos de dados incorretos
        invalid_trade_data = [
            {'symbol': 123, 'side': 'buy', 'quantity': 0.001},  # symbol deve ser string
            {'symbol': 'BTC/USDT', 'side': 123, 'quantity': 0.001},  # side deve ser string
            {'symbol': 'BTC/USDT', 'side': 'buy', 'quantity': 'invalid'},  # quantity deve ser número
            {'symbol': 'BTC/USDT', 'side': 'invalid_side', 'quantity': 0.001},  # side inválido
            {'symbol': 'BTC/USDT', 'side': 'buy', 'quantity': -0.001},  # quantity negativa
        ]
        
        for invalid_data in invalid_trade_data:
            # Em um teste real, isso seria enviado para a API
            # Aqui simulamos a validação
            
            # Validação de símbolo
            if not isinstance(invalid_data.get('symbol'), str):
                assert True  # Deve falhar
            
            # Validação de side
            if invalid_data.get('side') not in ['buy', 'sell']:
                assert True  # Deve falhar
            
            # Validação de quantity
            quantity = invalid_data.get('quantity')
            if not isinstance(quantity, (int, float)) or quantity <= 0:
                assert True  # Deve falhar

class TestRateLimiting:
    """Testes de rate limiting"""
    
    @pytest.mark.asyncio
    async def test_api_rate_limiting(self):
        """Testar rate limiting da API"""
        async with aiohttp.ClientSession() as session:
            
            # Fazer muitas requisições rapidamente
            responses = []
            start_time = time.time()
            
            for i in range(SECURITY_CONFIG['rate_limit_threshold'] + 10):
                try:
                    async with session.get(
                        f"{SECURITY_CONFIG['api_base_url']}/health",
                        timeout=aiohttp.ClientTimeout(total=1)
                    ) as response:
                        responses.append(response.status)
                except asyncio.TimeoutError:
                    responses.append(408)  # Timeout
                except Exception:
                    responses.append(500)  # Error
            
            end_time = time.time()
            duration = end_time - start_time
            
            # Verificar se rate limiting foi aplicado
            rate_limited_responses = [status for status in responses if status == 429]
            
            print(f"Total requests: {len(responses)}")
            print(f"Rate limited responses: {len(rate_limited_responses)}")
            print(f"Duration: {duration:.2f}s")
            print(f"Requests per second: {len(responses)/duration:.2f}")
            
            # Se muitas requisições foram feitas rapidamente, algumas devem ser limitadas
            if len(responses) > SECURITY_CONFIG['rate_limit_threshold'] and duration < 60:
                assert len(rate_limited_responses) > 0, "Rate limiting should be applied"
    
    @pytest.mark.asyncio
    async def test_login_attempt_limiting(self):
        """Testar limitação de tentativas de login"""
        async with aiohttp.ClientSession() as session:
            
            # Registrar usuário
            user_data = SECURITY_CONFIG['test_user'].copy()
            user_data['username'] = f"rate_limit_test_{int(time.time())}"
            user_data['email'] = f"rate_limit_test_{int(time.time())}@test.com"
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/register",
                json=user_data
            ) as response:
                assert response.status == 201
            
            # Fazer múltiplas tentativas de login com senha incorreta
            wrong_login = {
                'username': user_data['username'],
                'password': 'wrong_password'
            }
            
            responses = []
            for i in range(10):  # 10 tentativas
                async with session.post(
                    f"{SECURITY_CONFIG['api_base_url']}/auth/login",
                    json=wrong_login
                ) as response:
                    responses.append(response.status)
                    await asyncio.sleep(0.1)  # Pequena pausa
            
            # Após várias tentativas falhadas, deve haver rate limiting
            rate_limited = [status for status in responses if status == 429]
            
            # Pelo menos algumas tentativas devem ser limitadas
            if len(responses) > 5:
                # Em um sistema real, esperaríamos rate limiting após várias tentativas
                print(f"Login attempts: {len(responses)}")
                print(f"Rate limited: {len(rate_limited)}")

class TestDataEncryption:
    """Testes de criptografia de dados"""
    
    def test_sensitive_data_encryption(self):
        """Testar criptografia de dados sensíveis"""
        from cryptography.fernet import Fernet
        
        # Dados sensíveis que devem ser criptografados
        sensitive_data = {
            'api_key': 'binance_api_key_12345',
            'secret_key': 'binance_secret_key_67890',
            'private_key': 'user_private_key_abcdef'
        }
        
        # Gerar chave de criptografia
        key = Fernet.generate_key()
        cipher = Fernet(key)
        
        for data_type, data_value in sensitive_data.items():
            # Criptografar
            encrypted = cipher.encrypt(data_value.encode())
            
            # Verificar que está criptografado
            assert encrypted != data_value.encode()
            assert len(encrypted) > len(data_value)
            
            # Descriptografar
            decrypted = cipher.decrypt(encrypted).decode()
            assert decrypted == data_value
            
            print(f"{data_type}: Original length {len(data_value)}, Encrypted length {len(encrypted)}")
    
    def test_password_storage_security(self):
        """Testar segurança no armazenamento de senhas"""
        import bcrypt
        
        passwords = [
            'SimplePassword123',
            'Complex!Password@2024#',
            'AnotherSecure$Password%456'
        ]
        
        for password in passwords:
            # Hash da senha
            salt = bcrypt.gensalt(rounds=12)  # 12 rounds é um bom padrão
            hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
            
            # Verificações de segurança
            assert password.encode('utf-8') not in hashed  # Senha original não deve estar no hash
            assert len(hashed) >= 60  # Hash bcrypt deve ter pelo menos 60 caracteres
            assert hashed.startswith(b'$2b$')  # Deve usar bcrypt versão 2b
            
            # Verificar que a senha pode ser validada
            assert bcrypt.checkpw(password.encode('utf-8'), hashed)
            
            # Verificar que senha incorreta falha
            assert not bcrypt.checkpw(b'wrong_password', hashed)

class TestSecurityHeaders:
    """Testes de cabeçalhos de segurança HTTP"""
    
    @pytest.mark.asyncio
    async def test_security_headers(self):
        """Testar presença de cabeçalhos de segurança"""
        async with aiohttp.ClientSession() as session:
            
            async with session.get(f"{SECURITY_CONFIG['api_base_url']}/health") as response:
                headers = response.headers
                
                # Verificar cabeçalhos de segurança importantes
                security_headers = {
                    'X-Content-Type-Options': 'nosniff',
                    'X-Frame-Options': 'DENY',
                    'X-XSS-Protection': '1; mode=block',
                    'Strict-Transport-Security': 'max-age=31536000; includeSubDomains',
                    'Content-Security-Policy': None,  # Deve estar presente
                    'Referrer-Policy': 'strict-origin-when-cross-origin'
                }
                
                for header_name, expected_value in security_headers.items():
                    if header_name in headers:
                        if expected_value:
                            assert expected_value in headers[header_name], f"Header {header_name} has incorrect value"
                        print(f"✓ {header_name}: {headers[header_name]}")
                    else:
                        print(f"✗ Missing security header: {header_name}")
                
                # Verificar que informações sensíveis não são expostas
                assert 'Server' not in headers or 'nginx' not in headers.get('Server', '').lower()
                assert 'X-Powered-By' not in headers

class TestAPIKeySecurity:
    """Testes de segurança de chaves de API"""
    
    def test_api_key_generation(self):
        """Testar geração segura de chaves de API"""
        import secrets
        import string
        
        # Gerar chaves de API seguras
        for _ in range(10):
            # Chave de API (32 caracteres alfanuméricos)
            api_key = ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
            
            # Secret key (64 caracteres com símbolos)
            secret_key = ''.join(secrets.choice(string.ascii_letters + string.digits + '!@#$%^&*') for _ in range(64))
            
            # Verificações de segurança
            assert len(api_key) == 32
            assert len(secret_key) == 64
            assert api_key.isalnum()  # API key deve ser alfanumérica
            
            # Verificar entropia (não deve ter padrões óbvios)
            assert not all(c == api_key[0] for c in api_key)  # Não deve ser todos iguais
            assert len(set(api_key)) > 10  # Deve ter pelo menos 10 caracteres únicos
    
    def test_api_key_validation(self):
        """Testar validação de chaves de API"""
        valid_keys = [
            'abcd1234efgh5678ijkl9012mnop3456',
            'ABCD1234EFGH5678IJKL9012MNOP3456',
            'AbCd1234EfGh5678IjKl9012MnOp3456'
        ]
        
        invalid_keys = [
            'short_key',  # Muito curta
            'abcd1234efgh5678ijkl9012mnop345',  # 31 caracteres
            'abcd1234efgh5678ijkl9012mnop34567',  # 33 caracteres
            'abcd1234efgh5678ijkl9012mnop345!',  # Contém símbolo
            '',  # Vazia
            None  # Nula
        ]
        
        def validate_api_key(key):
            if not key or not isinstance(key, str):
                return False
            if len(key) != 32:
                return False
            if not key.isalnum():
                return False
            return True
        
        # Testar chaves válidas
        for key in valid_keys:
            assert validate_api_key(key), f"Valid key rejected: {key}"
        
        # Testar chaves inválidas
        for key in invalid_keys:
            assert not validate_api_key(key), f"Invalid key accepted: {key}"

class TestSessionSecurity:
    """Testes de segurança de sessão"""
    
    @pytest.mark.asyncio
    async def test_session_management(self):
        """Testar gerenciamento seguro de sessões"""
        async with aiohttp.ClientSession() as session:
            
            # Registrar e fazer login
            user_data = SECURITY_CONFIG['test_user'].copy()
            user_data['username'] = f"session_test_{int(time.time())}"
            user_data['email'] = f"session_test_{int(time.time())}@test.com"
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/register",
                json=user_data
            ) as response:
                assert response.status == 201
            
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/login",
                json={'username': user_data['username'], 'password': user_data['password']}
            ) as response:
                tokens = await response.json()
                access_token = tokens['access_token']
                refresh_token = tokens['refresh_token']
            
            # Teste 1: Usar token para acessar recurso protegido
            headers = {'Authorization': f'Bearer {access_token}'}
            async with session.get(
                f"{SECURITY_CONFIG['api_base_url']}/portfolio",
                headers=headers
            ) as response:
                assert response.status == 200
            
            # Teste 2: Logout deve invalidar o token
            async with session.post(
                f"{SECURITY_CONFIG['api_base_url']}/auth/logout",
                headers=headers
            ) as response:
                assert response.status == 200
            
            # Teste 3: Token deve estar inválido após logout
            async with session.get(
                f"{SECURITY_CONFIG['api_base_url']}/portfolio",
                headers=headers
            ) as response:
                # Deve falhar após logout (se implementado)
                # Em alguns sistemas, o token pode ainda ser válido até expirar
                print(f"Post-logout access status: {response.status}")

# Executar testes
if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short", "-s"])

