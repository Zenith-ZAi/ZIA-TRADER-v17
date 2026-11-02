# Fontes e proveniência — auditoria de 2026-11-02

## Fontes externas consultadas

- **pip-audit, PyPI:** https://pypi.org/project/pip-audit/ — descreve o scanner de vulnerabilidades conhecidas de pacotes Python e suas fontes de advisory (Python Packaging Advisory Database via PyPI JSON API; opções PyPI/OSV). Consultado em 2026-11-02. O alcance não cobre vulnerabilidades desconhecidas, segurança de configuração, licenças ou imagem/OS.
- **Astral uv, “Using uv with PyTorch”:** https://docs.astral.sh/uv/guides/integration/pytorch/ — consultado em 2026-11-02; a página informa revisão em 2026-10-14. Explica variantes CPU/CUDA, índices separados de wheels e seleção explícita `uv pip --torch-backend`. O projeto usa perfil CPU explícito no Docker/lock.
- **PyTorch, “Start Locally”:** https://pytorch.org/get-started/locally/ — página oficial de seleção de instalação e comando apropriado por plataforma/backend; usada como referência do índice CPU.
- **Astral uv, compatibilidade do pip interface:** https://docs.astral.sh/uv/pip/compatibility/ — documentação de resolução/índices usada na auditoria anterior da Fase 8A.

## Evidência local reproduzível

Em Python 3.12.3 ARM64, `/tmp/zia-trader-test-venv` foi sincronizado do `requirements.lock` com backend CPU. `uv pip check` verificou 117 pacotes compatíveis. A execução `uvx --from pip-audit pip-audit --path /tmp/zia-trader-test-venv` não reportou vulnerabilidades conhecidas para os pacotes instalados consultados. Isso é um scan do ambiente instalado, não da imagem Docker nem de dependências do sistema operacional.

`uv pip list --outdated --python /tmp/zia-trader-test-venv/bin/python` encontrou 77 pacotes para os quais o índice consultado listava versão mais nova. Diferenças representativas: FastAPI 0.111.0→0.162.0; SQLAlchemy 2.0.51→2.1.6; Redis 5.0.7→8.1.0; NumPy 1.26.4→2.5.4; pandas 2.2.2→3.1.0; XGBoost 2.0.3→3.4.1; Torch 2.13.0+cpu→2.15.0. Este comando apenas leu metadados; não mudou o lock nem instalou atualizações. Por incluir migrações major de API, não foi feito upgrade global. A recomendação é um PR separado, com re-lock hashado, revisão de compatibilidade e suíte integral após atualizações agrupadas.

## Limites de interpretação

“Sem vulnerabilidades reportadas” significa que o serviço de advisory consultado não retornou issue conhecida para aquele conjunto instalado no momento do scan. Não equivale a certificação, SBOM, auditoria de licenças, revisão humana ou teste de segurança em runtime. “Versão mais nova disponível” é comparação com o índice configurado; não é uma recomendação automática para atualização nem prova de compatibilidade.
