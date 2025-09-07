#!/usr/bin/env python3
"""
Script de Execução de Testes - RoboTrader 2.0
Executa todos os tipos de testes e gera relatórios de cobertura
"""

import os
import sys
import subprocess
import argparse
import time
import json
from datetime import datetime
from pathlib import Path
import shutil

# Configuração
TEST_CONFIG = {
    'project_root': Path(__file__).parent,
    'test_directories': {
        'unit': 'tests/unit',
        'integration': 'tests/integration', 
        'performance': 'tests/performance',
        'security': 'tests/security'
    },
    'coverage_threshold': 80,  # Mínimo de 80% de cobertura
    'output_dir': 'test_reports',
    'requirements_file': 'requirements_updated.txt'
}

class TestRunner:
    """Classe principal para executar testes"""
    
    def __init__(self, verbose=False):
        self.verbose = verbose
        self.project_root = TEST_CONFIG['project_root']
        self.output_dir = self.project_root / TEST_CONFIG['output_dir']
        self.results = {}
        
        # Criar diretório de saída
        self.output_dir.mkdir(exist_ok=True)
        
    def log(self, message, level='INFO'):
        """Log com timestamp"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"[{timestamp}] [{level}] {message}")
        
    def run_command(self, command, cwd=None, capture_output=True):
        """Executar comando e capturar saída"""
        if cwd is None:
            cwd = self.project_root
            
        self.log(f"Executing: {' '.join(command)}")
        
        try:
            result = subprocess.run(
                command,
                cwd=cwd,
                capture_output=capture_output,
                text=True,
                timeout=300  # 5 minutos timeout
            )
            
            if result.returncode != 0 and self.verbose:
                self.log(f"Command failed with return code {result.returncode}", 'ERROR')
                self.log(f"STDOUT: {result.stdout}", 'ERROR')
                self.log(f"STDERR: {result.stderr}", 'ERROR')
                
            return result
            
        except subprocess.TimeoutExpired:
            self.log("Command timed out", 'ERROR')
            return None
        except Exception as e:
            self.log(f"Command execution failed: {e}", 'ERROR')
            return None
    
    def check_dependencies(self):
        """Verificar se as dependências estão instaladas"""
        self.log("Checking dependencies...")
        
        required_packages = [
            'pytest',
            'pytest-cov',
            'pytest-asyncio',
            'pytest-xdist',
            'coverage',
            'bandit',
            'safety'
        ]
        
        missing_packages = []
        
        for package in required_packages:
            result = self.run_command(['python', '-c', f'import {package}'])
            if result and result.returncode != 0:
                missing_packages.append(package)
        
        if missing_packages:
            self.log(f"Installing missing packages: {missing_packages}")
            install_cmd = ['pip', 'install'] + missing_packages
            result = self.run_command(install_cmd)
            
            if result and result.returncode != 0:
                self.log("Failed to install dependencies", 'ERROR')
                return False
        
        self.log("All dependencies are available")
        return True
    
    def run_unit_tests(self):
        """Executar testes unitários"""
        self.log("Running unit tests...")
        
        unit_dir = self.project_root / TEST_CONFIG['test_directories']['unit']
        if not unit_dir.exists():
            self.log("Unit tests directory not found", 'WARNING')
            return {'status': 'skipped', 'reason': 'directory not found'}
        
        # Comando pytest com cobertura
        cmd = [
            'python', '-m', 'pytest',
            str(unit_dir),
            '--cov=.',
            '--cov-report=html:' + str(self.output_dir / 'coverage_html'),
            '--cov-report=xml:' + str(self.output_dir / 'coverage.xml'),
            '--cov-report=term-missing',
            '--junit-xml=' + str(self.output_dir / 'unit_tests.xml'),
            '-v',
            '--tb=short'
        ]
        
        if not self.verbose:
            cmd.append('-q')
        
        result = self.run_command(cmd)
        
        if result is None:
            return {'status': 'error', 'reason': 'execution failed'}
        
        # Analisar cobertura
        coverage_file = self.output_dir / 'coverage.xml'
        coverage_percentage = self.parse_coverage_xml(coverage_file)
        
        return {
            'status': 'passed' if result.returncode == 0 else 'failed',
            'return_code': result.returncode,
            'coverage': coverage_percentage,
            'output': result.stdout,
            'errors': result.stderr
        }
    
    def run_integration_tests(self):
        """Executar testes de integração"""
        self.log("Running integration tests...")
        
        integration_dir = self.project_root / TEST_CONFIG['test_directories']['integration']
        if not integration_dir.exists():
            self.log("Integration tests directory not found", 'WARNING')
            return {'status': 'skipped', 'reason': 'directory not found'}
        
        cmd = [
            'python', '-m', 'pytest',
            str(integration_dir),
            '--junit-xml=' + str(self.output_dir / 'integration_tests.xml'),
            '-v',
            '--tb=short',
            '--asyncio-mode=auto'
        ]
        
        if not self.verbose:
            cmd.append('-q')
        
        result = self.run_command(cmd)
        
        if result is None:
            return {'status': 'error', 'reason': 'execution failed'}
        
        return {
            'status': 'passed' if result.returncode == 0 else 'failed',
            'return_code': result.returncode,
            'output': result.stdout,
            'errors': result.stderr
        }
    
    def run_performance_tests(self):
        """Executar testes de performance"""
        self.log("Running performance tests...")
        
        performance_dir = self.project_root / TEST_CONFIG['test_directories']['performance']
        if not performance_dir.exists():
            self.log("Performance tests directory not found", 'WARNING')
            return {'status': 'skipped', 'reason': 'directory not found'}
        
        cmd = [
            'python', '-m', 'pytest',
            str(performance_dir),
            '--junit-xml=' + str(self.output_dir / 'performance_tests.xml'),
            '-v',
            '--tb=short',
            '-s'  # Não capturar output para ver métricas de performance
        ]
        
        result = self.run_command(cmd, capture_output=False)
        
        if result is None:
            return {'status': 'error', 'reason': 'execution failed'}
        
        return {
            'status': 'passed' if result.returncode == 0 else 'failed',
            'return_code': result.returncode
        }
    
    def run_security_tests(self):
        """Executar testes de segurança"""
        self.log("Running security tests...")
        
        security_dir = self.project_root / TEST_CONFIG['test_directories']['security']
        if not security_dir.exists():
            self.log("Security tests directory not found", 'WARNING')
            return {'status': 'skipped', 'reason': 'directory not found'}
        
        cmd = [
            'python', '-m', 'pytest',
            str(security_dir),
            '--junit-xml=' + str(self.output_dir / 'security_tests.xml'),
            '-v',
            '--tb=short',
            '-s'
        ]
        
        result = self.run_command(cmd, capture_output=False)
        
        if result is None:
            return {'status': 'error', 'reason': 'execution failed'}
        
        return {
            'status': 'passed' if result.returncode == 0 else 'failed',
            'return_code': result.returncode
        }
    
    def run_security_scan(self):
        """Executar scan de segurança com bandit"""
        self.log("Running security scan with bandit...")
        
        cmd = [
            'bandit',
            '-r', '.',
            '-f', 'json',
            '-o', str(self.output_dir / 'bandit_report.json'),
            '--exclude', 'tests,venv,.venv,node_modules'
        ]
        
        result = self.run_command(cmd)
        
        if result is None:
            return {'status': 'error', 'reason': 'execution failed'}
        
        # Bandit retorna código 1 se encontrar problemas, mas isso não é erro de execução
        return {
            'status': 'completed',
            'return_code': result.returncode,
            'output': result.stdout,
            'errors': result.stderr
        }
    
    def run_dependency_check(self):
        """Verificar vulnerabilidades nas dependências"""
        self.log("Checking dependencies for vulnerabilities...")
        
        cmd = [
            'safety', 'check',
            '--json',
            '--output', str(self.output_dir / 'safety_report.json')
        ]
        
        result = self.run_command(cmd)
        
        if result is None:
            return {'status': 'error', 'reason': 'execution failed'}
        
        return {
            'status': 'completed',
            'return_code': result.returncode,
            'output': result.stdout,
            'errors': result.stderr
        }
    
    def parse_coverage_xml(self, coverage_file):
        """Analisar arquivo XML de cobertura"""
        if not coverage_file.exists():
            return 0
        
        try:
            import xml.etree.ElementTree as ET
            tree = ET.parse(coverage_file)
            root = tree.getroot()
            
            # Procurar pelo atributo line-rate no elemento coverage
            coverage_elem = root.find('.')
            if coverage_elem is not None and 'line-rate' in coverage_elem.attrib:
                line_rate = float(coverage_elem.attrib['line-rate'])
                return round(line_rate * 100, 2)
            
        except Exception as e:
            self.log(f"Failed to parse coverage XML: {e}", 'WARNING')
        
        return 0
    
    def generate_summary_report(self):
        """Gerar relatório resumo"""
        self.log("Generating summary report...")
        
        summary = {
            'timestamp': datetime.now().isoformat(),
            'project': 'RoboTrader 2.0',
            'test_results': self.results,
            'overall_status': 'passed'
        }
        
        # Determinar status geral
        failed_tests = []
        for test_type, result in self.results.items():
            if result.get('status') == 'failed':
                failed_tests.append(test_type)
        
        if failed_tests:
            summary['overall_status'] = 'failed'
            summary['failed_tests'] = failed_tests
        
        # Verificar cobertura
        unit_result = self.results.get('unit_tests', {})
        coverage = unit_result.get('coverage', 0)
        
        if coverage < TEST_CONFIG['coverage_threshold']:
            summary['coverage_warning'] = f"Coverage {coverage}% is below threshold {TEST_CONFIG['coverage_threshold']}%"
        
        # Salvar relatório JSON
        summary_file = self.output_dir / 'test_summary.json'
        with open(summary_file, 'w') as f:
            json.dump(summary, f, indent=2)
        
        # Gerar relatório HTML
        self.generate_html_report(summary)
        
        return summary
    
    def generate_html_report(self, summary):
        """Gerar relatório HTML"""
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>RoboTrader 2.0 - Test Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        .header {{ background-color: #f0f0f0; padding: 20px; border-radius: 5px; }}
        .status-passed {{ color: green; font-weight: bold; }}
        .status-failed {{ color: red; font-weight: bold; }}
        .status-skipped {{ color: orange; font-weight: bold; }}
        .test-section {{ margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }}
        .coverage {{ background-color: #e8f5e8; padding: 10px; border-radius: 5px; }}
        table {{ width: 100%; border-collapse: collapse; }}
        th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
        th {{ background-color: #f2f2f2; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>RoboTrader 2.0 - Test Report</h1>
        <p><strong>Generated:</strong> {summary['timestamp']}</p>
        <p><strong>Overall Status:</strong> 
            <span class="status-{summary['overall_status']}">{summary['overall_status'].upper()}</span>
        </p>
    </div>
    
    <h2>Test Results Summary</h2>
    <table>
        <tr>
            <th>Test Type</th>
            <th>Status</th>
            <th>Details</th>
        </tr>
"""
        
        for test_type, result in summary['test_results'].items():
            status = result.get('status', 'unknown')
            status_class = f"status-{status}"
            
            details = []
            if 'coverage' in result:
                details.append(f"Coverage: {result['coverage']}%")
            if 'return_code' in result:
                details.append(f"Return Code: {result['return_code']}")
            
            details_str = ', '.join(details) if details else 'N/A'
            
            html_content += f"""
        <tr>
            <td>{test_type.replace('_', ' ').title()}</td>
            <td><span class="{status_class}">{status.upper()}</span></td>
            <td>{details_str}</td>
        </tr>
"""
        
        html_content += """
    </table>
    
    <h2>Coverage Information</h2>
    <div class="coverage">
"""
        
        unit_result = summary['test_results'].get('unit_tests', {})
        coverage = unit_result.get('coverage', 0)
        
        html_content += f"""
        <p><strong>Code Coverage:</strong> {coverage}%</p>
        <p><strong>Threshold:</strong> {TEST_CONFIG['coverage_threshold']}%</p>
"""
        
        if coverage < TEST_CONFIG['coverage_threshold']:
            html_content += f'<p style="color: red;"><strong>Warning:</strong> Coverage is below threshold!</p>'
        else:
            html_content += f'<p style="color: green;"><strong>Coverage target met!</strong></p>'
        
        html_content += """
    </div>
    
    <h2>Files Generated</h2>
    <ul>
        <li><a href="coverage_html/index.html">Coverage Report (HTML)</a></li>
        <li><a href="unit_tests.xml">Unit Tests (JUnit XML)</a></li>
        <li><a href="integration_tests.xml">Integration Tests (JUnit XML)</a></li>
        <li><a href="performance_tests.xml">Performance Tests (JUnit XML)</a></li>
        <li><a href="security_tests.xml">Security Tests (JUnit XML)</a></li>
        <li><a href="bandit_report.json">Security Scan (Bandit JSON)</a></li>
        <li><a href="safety_report.json">Dependency Check (Safety JSON)</a></li>
        <li><a href="test_summary.json">Test Summary (JSON)</a></li>
    </ul>
    
</body>
</html>
"""
        
        html_file = self.output_dir / 'test_report.html'
        with open(html_file, 'w') as f:
            f.write(html_content)
        
        self.log(f"HTML report generated: {html_file}")
    
    def run_all_tests(self, test_types=None):
        """Executar todos os testes"""
        if test_types is None:
            test_types = ['unit', 'integration', 'performance', 'security', 'security_scan', 'dependency_check']
        
        self.log("Starting comprehensive test suite...")
        start_time = time.time()
        
        # Verificar dependências
        if not self.check_dependencies():
            self.log("Dependency check failed", 'ERROR')
            return False
        
        # Executar testes
        test_methods = {
            'unit': self.run_unit_tests,
            'integration': self.run_integration_tests,
            'performance': self.run_performance_tests,
            'security': self.run_security_tests,
            'security_scan': self.run_security_scan,
            'dependency_check': self.run_dependency_check
        }
        
        for test_type in test_types:
            if test_type in test_methods:
                self.log(f"Running {test_type} tests...")
                self.results[f"{test_type}_tests"] = test_methods[test_type]()
            else:
                self.log(f"Unknown test type: {test_type}", 'WARNING')
        
        # Gerar relatórios
        summary = self.generate_summary_report()
        
        end_time = time.time()
        duration = end_time - start_time
        
        self.log(f"Test suite completed in {duration:.2f} seconds")
        self.log(f"Overall status: {summary['overall_status'].upper()}")
        
        # Mostrar resumo
        self.print_summary(summary)
        
        return summary['overall_status'] == 'passed'
    
    def print_summary(self, summary):
        """Imprimir resumo dos testes"""
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        for test_type, result in summary['test_results'].items():
            status = result.get('status', 'unknown').upper()
            print(f"{test_type.replace('_', ' ').title():.<30} {status}")
            
            if 'coverage' in result:
                print(f"  Coverage: {result['coverage']}%")
        
        print("\n" + "="*60)
        print(f"OVERALL STATUS: {summary['overall_status'].upper()}")
        print("="*60)
        
        # Mostrar arquivos gerados
        print(f"\nReports generated in: {self.output_dir}")
        print(f"Main report: {self.output_dir / 'test_report.html'}")

def main():
    """Função principal"""
    parser = argparse.ArgumentParser(description='Run RoboTrader 2.0 test suite')
    parser.add_argument('--types', nargs='+', 
                       choices=['unit', 'integration', 'performance', 'security', 'security_scan', 'dependency_check'],
                       help='Test types to run (default: all)')
    parser.add_argument('--verbose', '-v', action='store_true',
                       help='Verbose output')
    parser.add_argument('--output-dir', '-o', 
                       help='Output directory for reports')
    
    args = parser.parse_args()
    
    # Configurar output directory se especificado
    if args.output_dir:
        TEST_CONFIG['output_dir'] = args.output_dir
    
    # Criar runner
    runner = TestRunner(verbose=args.verbose)
    
    # Executar testes
    success = runner.run_all_tests(test_types=args.types)
    
    # Exit code baseado no resultado
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()

