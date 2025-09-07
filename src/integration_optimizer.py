"""
Sistema de Otimização de Integrações - RoboTrader
Ferramentas para integrar novas bibliotecas e garantir compatibilidade.
"""

import os
import sys
import asyncio
import subprocess
import importlib
import pkg_resources
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
import warnings
from packaging import version
import platform

# Importações locais
from config import config
from utils import setup_logging

logger = setup_logging(__name__)

@dataclass
class DependencyInfo:
    """Informações de dependência"""
    name: str
    current_version: Optional[str] = None
    latest_version: Optional[str] = None
    is_installed: bool = False
    is_outdated: bool = False
    is_compatible: bool = True
    compatibility_issues: List[str] = field(default_factory=list)
    installation_command: str = ""
    description: str = ""
    category: str = "general"

@dataclass
class IntegrationReport:
    """Relatório de integração"""
    timestamp: str
    python_version: str
    platform_info: str
    total_dependencies: int
    installed_dependencies: int
    outdated_dependencies: int
    incompatible_dependencies: int
    dependencies: List[DependencyInfo] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    critical_issues: List[str] = field(default_factory=list)

class DependencyManager:
    """Gerenciador de dependências"""
    
    def __init__(self):
        self.required_dependencies = self._get_required_dependencies()
        self.optional_dependencies = self._get_optional_dependencies()
        self.development_dependencies = self._get_development_dependencies()
    
    def _get_required_dependencies(self) -> Dict[str, Dict[str, Any]]:
        """Obtém dependências obrigatórias"""
        return {
            # Core Python
            "numpy": {
                "min_version": "1.21.0",
                "preferred_version": "2.1.2",
                "category": "core",
                "description": "Numerical computing library",
                "critical": True
            },
            "pandas": {
                "min_version": "1.3.0",
                "preferred_version": "2.2.3",
                "category": "core",
                "description": "Data manipulation and analysis",
                "critical": True
            },
            "scipy": {
                "min_version": "1.7.0",
                "preferred_version": "1.14.1",
                "category": "core",
                "description": "Scientific computing library",
                "critical": True
            },
            
            # Machine Learning
            "scikit-learn": {
                "min_version": "1.0.0",
                "preferred_version": "1.5.2",
                "category": "ml",
                "description": "Machine learning library",
                "critical": True
            },
            "tensorflow": {
                "min_version": "2.8.0",
                "preferred_version": "2.18.0",
                "category": "ml",
                "description": "Deep learning framework",
                "critical": True
            },
            "joblib": {
                "min_version": "1.0.0",
                "preferred_version": "1.4.2",
                "category": "ml",
                "description": "Parallel computing for ML",
                "critical": False
            },
            
            # Async & Web
            "asyncio": {
                "min_version": "3.7.0",
                "preferred_version": "built-in",
                "category": "async",
                "description": "Asynchronous I/O",
                "critical": True,
                "builtin": True
            },
            "aiohttp": {
                "min_version": "3.8.0",
                "preferred_version": "3.10.11",
                "category": "async",
                "description": "Async HTTP client/server",
                "critical": True
            },
            "fastapi": {
                "min_version": "0.68.0",
                "preferred_version": "0.115.5",
                "category": "web",
                "description": "Modern web framework",
                "critical": True
            },
            "uvicorn": {
                "min_version": "0.15.0",
                "preferred_version": "0.32.1",
                "category": "web",
                "description": "ASGI server",
                "critical": True
            },
            
            # Financial Data
            "yfinance": {
                "min_version": "0.1.70",
                "preferred_version": "0.2.44",
                "category": "financial",
                "description": "Yahoo Finance data",
                "critical": True
            },
            "ccxt": {
                "min_version": "2.0.0",
                "preferred_version": "4.4.29",
                "category": "financial",
                "description": "Cryptocurrency exchange library",
                "critical": True
            },
            
            # Database
            "asyncpg": {
                "min_version": "0.25.0",
                "preferred_version": "0.30.0",
                "category": "database",
                "description": "Async PostgreSQL driver",
                "critical": True
            },
            "redis": {
                "min_version": "4.0.0",
                "preferred_version": "5.2.0",
                "category": "database",
                "description": "Redis client",
                "critical": False
            },
            
            # Utilities
            "psutil": {
                "min_version": "5.8.0",
                "preferred_version": "6.1.0",
                "category": "system",
                "description": "System and process utilities",
                "critical": True
            },
            "loguru": {
                "min_version": "0.6.0",
                "preferred_version": "0.7.2",
                "category": "logging",
                "description": "Advanced logging",
                "critical": True
            },
            
            # Visualization
            "plotly": {
                "min_version": "5.0.0",
                "preferred_version": "5.24.1",
                "category": "visualization",
                "description": "Interactive plotting",
                "critical": False
            },
            "matplotlib": {
                "min_version": "3.5.0",
                "preferred_version": "3.9.2",
                "category": "visualization",
                "description": "Static plotting",
                "critical": False
            }
        }
    
    def _get_optional_dependencies(self) -> Dict[str, Dict[str, Any]]:
        """Obtém dependências opcionais"""
        return {
            # Quantum Computing
            "qiskit": {
                "min_version": "0.40.0",
                "preferred_version": "1.2.4",
                "category": "quantum",
                "description": "Quantum computing framework",
                "critical": False
            },
            
            # Advanced ML
            "xgboost": {
                "min_version": "1.6.0",
                "preferred_version": "2.1.2",
                "category": "ml_advanced",
                "description": "Gradient boosting framework",
                "critical": False
            },
            "lightgbm": {
                "min_version": "3.3.0",
                "preferred_version": "4.5.0",
                "category": "ml_advanced",
                "description": "Light gradient boosting",
                "critical": False
            },
            
            # Time Series
            "prophet": {
                "min_version": "1.0.0",
                "preferred_version": "1.1.6",
                "category": "timeseries",
                "description": "Time series forecasting",
                "critical": False
            },
            
            # Performance
            "numba": {
                "min_version": "0.56.0",
                "preferred_version": "0.60.0",
                "category": "performance",
                "description": "JIT compiler for Python",
                "critical": False
            },
            
            # Monitoring
            "prometheus-client": {
                "min_version": "0.14.0",
                "preferred_version": "0.21.0",
                "category": "monitoring",
                "description": "Prometheus metrics",
                "critical": False
            }
        }
    
    def _get_development_dependencies(self) -> Dict[str, Dict[str, Any]]:
        """Obtém dependências de desenvolvimento"""
        return {
            "pytest": {
                "min_version": "6.0.0",
                "preferred_version": "8.3.4",
                "category": "testing",
                "description": "Testing framework",
                "critical": False
            },
            "black": {
                "min_version": "22.0.0",
                "preferred_version": "24.10.0",
                "category": "formatting",
                "description": "Code formatter",
                "critical": False
            },
            "mypy": {
                "min_version": "0.950",
                "preferred_version": "1.13.0",
                "category": "typing",
                "description": "Static type checker",
                "critical": False
            }
        }
    
    async def check_dependency(self, name: str, requirements: Dict[str, Any]) -> DependencyInfo:
        """Verifica uma dependência específica"""
        dep_info = DependencyInfo(
            name=name,
            category=requirements.get("category", "general"),
            description=requirements.get("description", ""),
            installation_command=f"pip install {name}"
        )
        
        try:
            # Verificar se está instalado
            if requirements.get("builtin", False):
                # Dependência built-in (como asyncio)
                dep_info.is_installed = True
                dep_info.current_version = "built-in"
                dep_info.latest_version = "built-in"
                dep_info.is_compatible = True
                return dep_info
            
            # Tentar importar
            try:
                module = importlib.import_module(name.replace("-", "_"))
                dep_info.is_installed = True
                
                # Obter versão atual
                if hasattr(module, "__version__"):
                    dep_info.current_version = module.__version__
                else:
                    # Tentar obter via pkg_resources
                    try:
                        dist = pkg_resources.get_distribution(name)
                        dep_info.current_version = dist.version
                    except:
                        dep_info.current_version = "unknown"
                
            except ImportError:
                dep_info.is_installed = False
                dep_info.current_version = None
            
            # Verificar versão mais recente (simulado)
            dep_info.latest_version = requirements.get("preferred_version", "unknown")
            
            # Verificar se está desatualizado
            if dep_info.is_installed and dep_info.current_version and dep_info.latest_version:
                if dep_info.current_version != "unknown" and dep_info.latest_version != "unknown":
                    try:
                        current_ver = version.parse(dep_info.current_version)
                        latest_ver = version.parse(dep_info.latest_version)
                        dep_info.is_outdated = current_ver < latest_ver
                    except:
                        dep_info.is_outdated = False
            
            # Verificar compatibilidade
            if dep_info.is_installed and dep_info.current_version:
                compatibility_result = await self._check_compatibility(name, dep_info.current_version, requirements)
                dep_info.is_compatible = compatibility_result["compatible"]
                dep_info.compatibility_issues = compatibility_result["issues"]
            
        except Exception as e:
            logger.error(f"Erro ao verificar dependência {name}: {e}")
            dep_info.compatibility_issues.append(f"Error checking dependency: {e}")
        
        return dep_info
    
    async def _check_compatibility(self, name: str, current_version: str, 
                                 requirements: Dict[str, Any]) -> Dict[str, Any]:
        """Verifica compatibilidade de uma dependência"""
        issues = []
        compatible = True
        
        try:
            # Verificar versão mínima
            min_version = requirements.get("min_version")
            if min_version and current_version != "unknown":
                try:
                    current_ver = version.parse(current_version)
                    min_ver = version.parse(min_version)
                    
                    if current_ver < min_ver:
                        compatible = False
                        issues.append(f"Version {current_version} is below minimum required {min_version}")
                except:
                    issues.append(f"Could not parse version {current_version}")
            
            # Verificar compatibilidade com Python
            python_version = sys.version_info
            if name == "tensorflow" and python_version >= (3, 12):
                issues.append("TensorFlow may have compatibility issues with Python 3.12+")
            
            # Verificar compatibilidade específica
            if name == "numpy" and current_version:
                try:
                    current_ver = version.parse(current_version)
                    if current_ver >= version.parse("2.0.0"):
                        issues.append("NumPy 2.0+ may have breaking changes with some libraries")
                except:
                    pass
            
        except Exception as e:
            issues.append(f"Error checking compatibility: {e}")
            compatible = False
        
        return {"compatible": compatible, "issues": issues}
    
    async def generate_integration_report(self) -> IntegrationReport:
        """Gera relatório completo de integração"""
        all_dependencies = {
            **self.required_dependencies,
            **self.optional_dependencies,
            **self.development_dependencies
        }
        
        dependencies_info = []
        
        # Verificar cada dependência
        for name, requirements in all_dependencies.items():
            dep_info = await self.check_dependency(name, requirements)
            dependencies_info.append(dep_info)
        
        # Calcular estatísticas
        total_deps = len(dependencies_info)
        installed_deps = len([d for d in dependencies_info if d.is_installed])
        outdated_deps = len([d for d in dependencies_info if d.is_outdated])
        incompatible_deps = len([d for d in dependencies_info if not d.is_compatible])
        
        # Gerar recomendações
        recommendations = self._generate_recommendations(dependencies_info)
        
        # Identificar problemas críticos
        critical_issues = self._identify_critical_issues(dependencies_info)
        
        report = IntegrationReport(
            timestamp=str(datetime.now()),
            python_version=sys.version,
            platform_info=platform.platform(),
            total_dependencies=total_deps,
            installed_dependencies=installed_deps,
            outdated_dependencies=outdated_deps,
            incompatible_dependencies=incompatible_deps,
            dependencies=dependencies_info,
            recommendations=recommendations,
            critical_issues=critical_issues
        )
        
        return report
    
    def _generate_recommendations(self, dependencies: List[DependencyInfo]) -> List[str]:
        """Gera recomendações baseadas no estado das dependências"""
        recommendations = []
        
        # Dependências não instaladas críticas
        missing_critical = [d for d in dependencies if not d.is_installed and 
                          self._is_critical_dependency(d.name)]
        
        if missing_critical:
            recommendations.append(
                f"Install critical missing dependencies: {', '.join([d.name for d in missing_critical])}"
            )
        
        # Dependências desatualizadas
        outdated = [d for d in dependencies if d.is_outdated]
        if outdated:
            recommendations.append(
                f"Update outdated dependencies: {', '.join([d.name for d in outdated])}"
            )
        
        # Problemas de compatibilidade
        incompatible = [d for d in dependencies if not d.is_compatible]
        if incompatible:
            recommendations.append(
                f"Fix compatibility issues for: {', '.join([d.name for d in incompatible])}"
            )
        
        # Recomendações específicas
        if any(d.name == "tensorflow" and not d.is_installed for d in dependencies):
            recommendations.append(
                "Consider installing TensorFlow with GPU support if available: pip install tensorflow[gpu]"
            )
        
        if any(d.name == "numpy" and d.current_version and 
               version.parse(d.current_version) >= version.parse("2.0.0") for d in dependencies):
            recommendations.append(
                "NumPy 2.0+ detected. Test thoroughly for compatibility with other libraries."
            )
        
        return recommendations
    
    def _identify_critical_issues(self, dependencies: List[DependencyInfo]) -> List[str]:
        """Identifica problemas críticos"""
        critical_issues = []
        
        # Dependências críticas não instaladas
        missing_critical = [d for d in dependencies if not d.is_installed and 
                          self._is_critical_dependency(d.name)]
        
        for dep in missing_critical:
            critical_issues.append(f"Critical dependency missing: {dep.name}")
        
        # Incompatibilidades críticas
        incompatible_critical = [d for d in dependencies if not d.is_compatible and 
                               self._is_critical_dependency(d.name)]
        
        for dep in incompatible_critical:
            critical_issues.append(f"Critical compatibility issue: {dep.name}")
        
        # Verificar Python version
        python_version = sys.version_info
        if python_version < (3, 8):
            critical_issues.append("Python version is too old. Minimum required: 3.8")
        elif python_version >= (3, 12):
            critical_issues.append("Python 3.12+ may have compatibility issues with some libraries")
        
        return critical_issues
    
    def _is_critical_dependency(self, name: str) -> bool:
        """Verifica se uma dependência é crítica"""
        all_deps = {**self.required_dependencies, **self.optional_dependencies}
        return all_deps.get(name, {}).get("critical", False)
    
    async def install_missing_dependencies(self, dependencies: List[str]) -> Dict[str, bool]:
        """Instala dependências ausentes"""
        results = {}
        
        for dep_name in dependencies:
            try:
                logger.info(f"Installing {dep_name}...")
                
                # Comando de instalação
                cmd = ["pip", "install", dep_name]
                
                # Executar instalação
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    logger.info(f"Successfully installed {dep_name}")
                    results[dep_name] = True
                else:
                    logger.error(f"Failed to install {dep_name}: {stderr.decode()}")
                    results[dep_name] = False
                
            except Exception as e:
                logger.error(f"Error installing {dep_name}: {e}")
                results[dep_name] = False
        
        return results
    
    async def update_dependencies(self, dependencies: List[str]) -> Dict[str, bool]:
        """Atualiza dependências"""
        results = {}
        
        for dep_name in dependencies:
            try:
                logger.info(f"Updating {dep_name}...")
                
                # Comando de atualização
                cmd = ["pip", "install", "--upgrade", dep_name]
                
                # Executar atualização
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode == 0:
                    logger.info(f"Successfully updated {dep_name}")
                    results[dep_name] = True
                else:
                    logger.error(f"Failed to update {dep_name}: {stderr.decode()}")
                    results[dep_name] = False
                
            except Exception as e:
                logger.error(f"Error updating {dep_name}: {e}")
                results[dep_name] = False
        
        return results

class CompatibilityChecker:
    """Verificador de compatibilidade"""
    
    def __init__(self):
        self.compatibility_matrix = self._build_compatibility_matrix()
    
    def _build_compatibility_matrix(self) -> Dict[str, Dict[str, List[str]]]:
        """Constrói matriz de compatibilidade"""
        return {
            "python": {
                "3.8": ["tensorflow>=2.8.0", "numpy>=1.19.0", "pandas>=1.2.0"],
                "3.9": ["tensorflow>=2.8.0", "numpy>=1.19.0", "pandas>=1.3.0"],
                "3.10": ["tensorflow>=2.8.0", "numpy>=1.21.0", "pandas>=1.3.0"],
                "3.11": ["tensorflow>=2.11.0", "numpy>=1.23.0", "pandas>=1.5.0"],
                "3.12": ["tensorflow>=2.16.0", "numpy>=1.26.0", "pandas>=2.1.0"]
            },
            "tensorflow": {
                "2.8": ["python>=3.7,<3.11", "numpy>=1.20.0,<1.24.0"],
                "2.11": ["python>=3.7,<3.12", "numpy>=1.20.0,<1.25.0"],
                "2.16": ["python>=3.9,<3.13", "numpy>=1.23.0,<2.1.0"],
                "2.18": ["python>=3.9,<3.13", "numpy>=1.23.0,<2.1.0"]
            },
            "numpy": {
                "1.21": ["python>=3.7,<3.11"],
                "1.23": ["python>=3.8,<3.12"],
                "1.26": ["python>=3.9,<3.13"],
                "2.0": ["python>=3.9,<3.13"],
                "2.1": ["python>=3.10,<3.13"]
            }
        }
    
    def check_python_compatibility(self, target_python: str) -> Dict[str, Any]:
        """Verifica compatibilidade com versão do Python"""
        current_python = f"{sys.version_info.major}.{sys.version_info.minor}"
        
        compatible_packages = self.compatibility_matrix.get("python", {}).get(target_python, [])
        
        return {
            "current_python": current_python,
            "target_python": target_python,
            "is_compatible": current_python == target_python,
            "compatible_packages": compatible_packages,
            "recommendations": self._get_python_recommendations(current_python, target_python)
        }
    
    def _get_python_recommendations(self, current: str, target: str) -> List[str]:
        """Gera recomendações para compatibilidade com Python"""
        recommendations = []
        
        current_ver = version.parse(current)
        target_ver = version.parse(target)
        
        if current_ver < target_ver:
            recommendations.append(f"Consider upgrading Python from {current} to {target}")
        elif current_ver > target_ver:
            recommendations.append(f"Consider downgrading Python from {current} to {target}")
        
        # Recomendações específicas
        if target == "3.11":
            recommendations.append("Python 3.11 offers significant performance improvements")
        elif target == "3.12":
            recommendations.append("Python 3.12 is cutting-edge but may have compatibility issues")
        
        return recommendations

class IntegrationOptimizer:
    """Otimizador de integrações"""
    
    def __init__(self):
        self.dependency_manager = DependencyManager()
        self.compatibility_checker = CompatibilityChecker()
    
    async def optimize_environment(self) -> Dict[str, Any]:
        """Otimiza ambiente completo"""
        logger.info("Starting environment optimization...")
        
        # Gerar relatório de integração
        report = await self.dependency_manager.generate_integration_report()
        
        # Identificar ações necessárias
        actions = self._identify_optimization_actions(report)
        
        # Executar otimizações
        results = await self._execute_optimizations(actions)
        
        # Gerar relatório final
        final_report = {
            "initial_report": report,
            "optimization_actions": actions,
            "execution_results": results,
            "final_status": await self._get_final_status()
        }
        
        return final_report
    
    def _identify_optimization_actions(self, report: IntegrationReport) -> Dict[str, List[str]]:
        """Identifica ações de otimização necessárias"""
        actions = {
            "install": [],
            "update": [],
            "fix_compatibility": [],
            "remove_conflicts": []
        }
        
        for dep in report.dependencies:
            if not dep.is_installed and dep.category in ["core", "ml", "async", "web", "financial"]:
                actions["install"].append(dep.name)
            elif dep.is_outdated and dep.is_installed:
                actions["update"].append(dep.name)
            elif not dep.is_compatible and dep.is_installed:
                actions["fix_compatibility"].append(dep.name)
        
        return actions
    
    async def _execute_optimizations(self, actions: Dict[str, List[str]]) -> Dict[str, Any]:
        """Executa otimizações"""
        results = {}
        
        # Instalar dependências ausentes
        if actions["install"]:
            logger.info(f"Installing missing dependencies: {actions['install']}")
            install_results = await self.dependency_manager.install_missing_dependencies(actions["install"])
            results["installations"] = install_results
        
        # Atualizar dependências
        if actions["update"]:
            logger.info(f"Updating dependencies: {actions['update']}")
            update_results = await self.dependency_manager.update_dependencies(actions["update"])
            results["updates"] = update_results
        
        # Corrigir compatibilidade
        if actions["fix_compatibility"]:
            logger.info(f"Fixing compatibility issues: {actions['fix_compatibility']}")
            compatibility_results = await self._fix_compatibility_issues(actions["fix_compatibility"])
            results["compatibility_fixes"] = compatibility_results
        
        return results
    
    async def _fix_compatibility_issues(self, dependencies: List[str]) -> Dict[str, bool]:
        """Corrige problemas de compatibilidade"""
        results = {}
        
        for dep_name in dependencies:
            try:
                # Estratégias específicas de correção
                if dep_name == "numpy":
                    # Para NumPy 2.0+, pode ser necessário downgrade
                    success = await self._fix_numpy_compatibility()
                    results[dep_name] = success
                elif dep_name == "tensorflow":
                    # Para TensorFlow, verificar versão compatível
                    success = await self._fix_tensorflow_compatibility()
                    results[dep_name] = success
                else:
                    # Estratégia genérica: reinstalar versão compatível
                    success = await self._reinstall_compatible_version(dep_name)
                    results[dep_name] = success
                    
            except Exception as e:
                logger.error(f"Error fixing compatibility for {dep_name}: {e}")
                results[dep_name] = False
        
        return results
    
    async def _fix_numpy_compatibility(self) -> bool:
        """Corrige compatibilidade do NumPy"""
        try:
            # Verificar se NumPy 2.0+ está causando problemas
            import numpy as np
            numpy_version = version.parse(np.__version__)
            
            if numpy_version >= version.parse("2.0.0"):
                logger.info("NumPy 2.0+ detected, checking for compatibility issues...")
                
                # Testar importações que podem ter problemas
                test_imports = ["sklearn", "tensorflow", "scipy"]
                
                for module_name in test_imports:
                    try:
                        importlib.import_module(module_name)
                    except ImportError as e:
                        if "numpy" in str(e).lower():
                            logger.warning(f"NumPy compatibility issue with {module_name}")
                            # Poderia fazer downgrade do NumPy aqui se necessário
                            return False
                
                return True
            
            return True
            
        except Exception as e:
            logger.error(f"Error fixing NumPy compatibility: {e}")
            return False
    
    async def _fix_tensorflow_compatibility(self) -> bool:
        """Corrige compatibilidade do TensorFlow"""
        try:
            python_version = sys.version_info
            
            # Verificar se a versão do Python é compatível
            if python_version >= (3, 12):
                logger.warning("Python 3.12+ may have issues with TensorFlow")
                # Sugerir versão específica do TensorFlow
                return await self._install_specific_version("tensorflow", ">=2.16.0")
            elif python_version >= (3, 11):
                return await self._install_specific_version("tensorflow", ">=2.11.0")
            
            return True
            
        except Exception as e:
            logger.error(f"Error fixing TensorFlow compatibility: {e}")
            return False
    
    async def _reinstall_compatible_version(self, package_name: str) -> bool:
        """Reinstala versão compatível de um pacote"""
        try:
            # Obter versão compatível recomendada
            all_deps = {
                **self.dependency_manager.required_dependencies,
                **self.dependency_manager.optional_dependencies
            }
            
            package_info = all_deps.get(package_name, {})
            preferred_version = package_info.get("preferred_version")
            
            if preferred_version:
                return await self._install_specific_version(package_name, f"=={preferred_version}")
            
            return False
            
        except Exception as e:
            logger.error(f"Error reinstalling {package_name}: {e}")
            return False
    
    async def _install_specific_version(self, package_name: str, version_spec: str) -> bool:
        """Instala versão específica de um pacote"""
        try:
            cmd = ["pip", "install", f"{package_name}{version_spec}"]
            
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                logger.info(f"Successfully installed {package_name}{version_spec}")
                return True
            else:
                logger.error(f"Failed to install {package_name}{version_spec}: {stderr.decode()}")
                return False
                
        except Exception as e:
            logger.error(f"Error installing {package_name}{version_spec}: {e}")
            return False
    
    async def _get_final_status(self) -> Dict[str, Any]:
        """Obtém status final após otimizações"""
        # Gerar novo relatório
        final_report = await self.dependency_manager.generate_integration_report()
        
        return {
            "total_dependencies": final_report.total_dependencies,
            "installed_dependencies": final_report.installed_dependencies,
            "outdated_dependencies": final_report.outdated_dependencies,
            "incompatible_dependencies": final_report.incompatible_dependencies,
            "critical_issues_remaining": len(final_report.critical_issues),
            "optimization_success_rate": self._calculate_success_rate(final_report)
        }
    
    def _calculate_success_rate(self, report: IntegrationReport) -> float:
        """Calcula taxa de sucesso da otimização"""
        if report.total_dependencies == 0:
            return 0.0
        
        successful_deps = report.installed_dependencies - report.incompatible_dependencies
        return (successful_deps / report.total_dependencies) * 100
    
    async def save_optimization_report(self, report: Dict[str, Any], filename: Optional[str] = None):
        """Salva relatório de otimização"""
        if not filename:
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"integration_optimization_report_{timestamp}.json"
        
        reports_dir = Path("optimization_reports")
        reports_dir.mkdir(exist_ok=True)
        
        with open(reports_dir / filename, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"Optimization report saved: {filename}")

# Instância global
integration_optimizer: Optional[IntegrationOptimizer] = None

def initialize_integration_optimizer() -> IntegrationOptimizer:
    """Inicializa otimizador de integração global"""
    global integration_optimizer
    integration_optimizer = IntegrationOptimizer()
    return integration_optimizer

def get_integration_optimizer() -> Optional[IntegrationOptimizer]:
    """Obtém otimizador de integração global"""
    return integration_optimizer

if __name__ == "__main__":
    # Exemplo de uso
    async def main():
        # Inicializar otimizador
        optimizer = initialize_integration_optimizer()
        
        # Executar otimização completa
        optimization_report = await optimizer.optimize_environment()
        
        # Salvar relatório
        await optimizer.save_optimization_report(optimization_report)
        
        # Exibir resumo
        final_status = optimization_report["final_status"]
        print(f"Optimization completed!")
        print(f"Success rate: {final_status['optimization_success_rate']:.1f}%")
        print(f"Dependencies installed: {final_status['installed_dependencies']}/{final_status['total_dependencies']}")
        print(f"Critical issues remaining: {final_status['critical_issues_remaining']}")
    
    # Executar exemplo
    # asyncio.run(main())

