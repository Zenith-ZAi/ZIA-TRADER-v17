"""Auditoria de segurança refinada para detecção de injeções e vulnerabilidades."""

from __future__ import annotations

import ast
import os
import sys
from pathlib import Path

def is_dangerous_eval(node: ast.Call) -> bool:
    """Verifica se a chamada é a função global eval() e não um método .eval()."""
    if isinstance(node.func, ast.Name) and node.func.id == 'eval':
        return True
    return False

def is_dangerous_exec(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Name) and node.func.id == 'exec':
        return True
    return False

def is_dangerous_system(node: ast.Call) -> bool:
    if isinstance(node.func, ast.Attribute) and node.func.attr == 'system':
        if isinstance(node.func.value, ast.Name) and node.func.value.id == 'os':
            return True
    return False

def audit_file(path: Path) -> list[str]:
    vulnerabilities = []
    try:
        content = path.read_text(encoding="utf-8")
        tree = ast.parse(content)
        
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if is_dangerous_eval(node):
                    vulnerabilities.append(f"Uso perigoso de eval() detectado na linha {node.lineno}")
                if is_dangerous_exec(node):
                    vulnerabilities.append(f"Uso perigoso de exec() detectado na linha {node.lineno}")
                if is_dangerous_system(node):
                    vulnerabilities.append(f"Uso perigoso de os.system() detectado na linha {node.lineno}")
                    
        # Check for potential SQL Injection in raw strings
        if "execute(" in content:
            if "f\"" in content or ".format(" in content or "%" in content:
                 # This is a heuristic, might still have false positives but better than nothing
                 if "SELECT" in content.upper() or "UPDATE" in content.upper() or "INSERT" in content.upper():
                    vulnerabilities.append(f"Possível SQL Injection detectado (heurística)")
                    
    except Exception as e:
        vulnerabilities.append(f"Erro ao auditar arquivo: {e}")
             
    return vulnerabilities

def main():
    project_root = Path(__file__).resolve().parents[1]
    all_vulnerabilities = []
    
    # Excluir o próprio script de auditoria da verificação
    this_file = Path(__file__).name
    
    for root, _, files in os.walk(project_root):
        for file in files:
            if file.endswith(".py") and file != this_file:
                path = Path(root) / file
                vulnerabilities = audit_file(path)
                for v in vulnerabilities:
                    all_vulnerabilities.append(f"{file}: {v}")
                
    if not all_vulnerabilities:
        print("✅ Core Refinado: Nenhuma vulnerabilidade de injeção detectada via AST.")
    else:
        print("⚠️ Vulnerabilidades detectadas:")
        for v in all_vulnerabilities:
            print(f" - {v}")
        sys.exit(1)

if __name__ == "__main__":
    main()
