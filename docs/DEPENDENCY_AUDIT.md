# Auditoria de dependências e runtime

**Atualizado:** 2026-10-21, branch `phase8/cpu-lock-and-final-readiness`. O diagnóstico da virtualenv anterior é preservado; esta atualização registra a solução proposta e os testes isolados. Não equivale a build/deploy em VPS.

## Evidências executadas

| Verificação | Resultado | Escopo/limite |
|---|---|---|
| Ambiente da virtualenv anterior | Python 3.12.3, Linux `aarch64` | A virtualenv compartilhada original não foi alterada. |
| `uv pip check --python /home/ubuntu/.venvs/zia-v17/bin/python` | **Exit 1** na virtualenv antiga: um pacote (`nvidia-cusparselt-cu13==0.8.1`) tem wheel `manylinux2014_sbsa` que o ambiente ativo não aceita | Diagnóstico real de compatibilidade de ambiente; não foi atribuído ao build de produção sem evidência. |
| Lock novo CPU | 117 requisitos resolvidos, pins + hashes SHA-256; `torch==2.13.0+cpu` para plataformas não macOS; sem pacotes `nvidia-*`, `cuda-*` ou `triton` | Universal lock para runtime CPU; versões preservadas por `requirements.constraints.txt`, arquivo de constraints que não deve ser instalado. |
| Sync limpo do lock | `uv pip sync --python /tmp/zia-v17-phase8-lock-test/bin/python --torch-backend cpu --no-progress requirements.lock` | Ambiente descartável Python 3.12.3, Sandbox ARM64; 117 pacotes instalados, download Torch CPU de 147,8 MiB. |
| `uv pip sync ... --check requirements.lock` | Sem alterações necessárias; 117 pacotes verificados | O ambiente temporário instalado corresponde ao lock versionado. |
| `uv pip check --python /tmp/zia-v17-phase8-lock-test/bin/python` | Exit 0; todos compatíveis | No mesmo ARM64 limpo; não corrige a virtualenv antiga, prova que uma reinstalação via lock é compatível. |
| Torch no ambiente limpo | `2.13.0+cpu`, `torch.version.cuda=None`, CUDA indisponível, pacote `nvidia-cusparselt-cu13` ausente | Perfil deliberado para VPS CPU; desempenho/capacidade de inferência ainda precisam ser medidos no hardware-alvo. |
| `pytest -q` no ambiente limpo, branch Phase 8A | 192 passed, 3 skipped, 1 warning; 20,47 s | Sem serviços externos; skip de banco depende de `TEST_DATABASE_URL`; warning Starlette/PendingDeprecation. |
| Resolução cruzada `x86_64-unknown-linux-gnu` | Torch CPU selecionado; sem dependências CUDA/NVIDIA | Verifica resolução para o alvo padrão do GitHub/Docker, não executa imagem x86 no Sandbox ARM. |
| Testes novos `tests/test_dependency_lock.py` | 3 passed | Verificam perfil CPU, hashes, ausência dos wheels incompatíveis e que constraints não são manifest de instalação. |
| CI GitHub do PR #20 | `test` e `container` concluídos com sucesso no run `39651671722` (SHA `e375072658cad0e581ac75cbfbd4cf27aa5f78f0`) | O job container construiu a imagem no runner GitHub x86_64. CodeRabbit reportou revisão ignorada; isso não é revisão manual. Build não significa deploy, Compose up ou soak em VPS. |
| Scanner CVE/licenças/SBOM | Não executado | Não alegar ausência de vulnerabilidades. |

## Alterações nesta branch

- `requirements.lock` passou a ser gerado por UV com resolução universal, backend `cpu`, pins e hashes; o perfil de produção não solicita aceleração CUDA.
- `requirements.constraints.txt` preserva pins de referência não acelerados do snapshot anterior e é usado **somente como `-c` na regeneração**; não instalar esse arquivo diretamente.
- Dockerfile e CI passam a sincronizar o mesmo lock com UV `0.12.19` e `--torch-backend cpu`, seguidos por `uv pip check`.
- Regeneração controlada: `uv pip compile requirements.txt -c requirements.constraints.txt --python-version 3.12 --torch-backend cpu --universal --emit-index-url --generate-hashes -o requirements.lock`.
- Instalação/sincronização: `uv pip sync --system --torch-backend cpu requirements.lock`; verificação: `uv pip check --system`.

## O que ainda não prova

A resolução x86_64 e a instalação ARM64 em venv descartável, somadas ao build do job `container`, não executam Compose up, PostgreSQL/Redis persistentes, proxy TLS ou aplicação com feeds/broker reais. A tag `python:3.12-slim`, Postgres e Redis ainda não estão fixados por digest; scanner, SBOM, licenças, atualização de CVEs e medição de latência CPU permanecem gates do release.


## Adendo de 2026-11-02 — auditoria do lock atual

No venv descartável Python 3.12.3 sincronizado por `requirements.lock`, `uv pip check` verificou 117 pacotes compatíveis. `pip-audit` executado contra esse ambiente não reportou vulnerabilidades conhecidas; isso não cobre CVEs ainda não catalogadas, licenças, imagem Docker ou componentes do sistema operacional. A ferramenta documenta a consulta a bases de advisory conhecidas em https://pypi.org/project/pip-audit/.

A enumeração `uv pip list --outdated` encontrou 77 pacotes com versões mais recentes disponíveis no índice consultado. Entre as diferenças de maior risco estão FastAPI 0.111→0.162, SQLAlchemy 2.0→2.1, Redis 5→8, NumPy 1→2, pandas 2→3, XGBoost 2→3 e Torch 2.13 CPU→2.15. Nenhum upgrade foi aplicado em massa: o resultado de compatibilidade e a ausência de CVEs conhecidos não justificam misturar mudanças de API em runtime e modelos com a correção de execução. Criar um ciclo separado de atualização por grupos, com lock/hash regenerado e CI integral após cada conjunto. O método CPU continua explícito com `uv pip --torch-backend cpu`, conforme o guia de integração PyTorch do uv: https://docs.astral.sh/uv/guides/integration/pytorch/.
