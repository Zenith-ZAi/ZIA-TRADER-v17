# Auditoria de dependências e runtime

**Data de verificação:** 2026-10-21. **Ambiente:** Sandbox Linux, Python 3.12.3, virtualenv `/home/ubuntu/.venvs/zia-v17`. Esta é uma auditoria do ambiente ativo e dos manifests; não equivale a um build limpo de container.

## Evidências executadas

| Verificação | Resultado | Escopo/limite |
|---|---|---|
| `/home/ubuntu/.venvs/zia-v17/bin/python --version` | Python 3.12.3 | Runtime local do Sandbox. |
| `python -m compileall -q .` | Exit 0 | Sintaxe/compilação; não valida runtime de cada integração. |
| `python -m pytest -q` | 189 passed, 3 skipped, 1 warning | Suíte local; sem broker real, VPS ou serviços externos de produção. |
| `uv pip check --python /home/ubuntu/.venvs/zia-v17/bin/python` | **Exit 1**; 194 pacotes verificados, uma incompatibilidade: `nvidia-cusparselt-cu13` foi construído para plataforma diferente | Falha do ambiente ativo; não foi atribuída sem prova ao Docker. Deve ser resolvida/explicada antes de aprovar build reprodutível. |
| Build limpo de dependências/Docker | Não executado | O Sandbox não possui Docker CLI/Compose. |
| Scanner de vulnerabilidades (por exemplo, pip-audit) | Não executado | Não instalado/validado nesta tarefa; nenhuma alegação de ausência de CVEs. |

## Manifestos e consistência

- `requirements.txt` fixa várias dependências principais (FastAPI, SQLAlchemy, Alembic, Pandas, NumPy, Redis, XGBoost e driver PostgreSQL), mas deixa outras sem versão exata ou em faixa aberta, incluindo `torch`, pacotes OpenTelemetry, `requests` e alguns conectores opcionais.
- `requirements.lock` registra versões transitivas e contém `nvidia-cusparselt-cu13==0.8.1`; o `uv pip check` reporta que a build instalada não corresponde à plataforma corrente.
- `Dockerfile` usa `FROM python:3.12-slim` e instala **somente** `requirements.txt`; não consome `requirements.lock`. A tag base não fixa digest nem patch de Python. Portanto o lock não garante o conteúdo reproduzível da imagem atual.
- CI configura Python 3.12 e serviço PostgreSQL 16, instala `requirements.txt`, compila, executa testes e possui job de build de imagem. A última execução remota observada antes desta branch foi sucesso no `master` após PR #17 (run `39361245138`, 2026-10-20); não é resultado de CI desta branch.
- A suíte de migration em CI prevê `TEST_DATABASE_URL` e PostgreSQL, mas o ambiente local desta rodada não tinha PostgreSQL; o teste local correspondente foi ignorado quando a variável não estava configurada.

## Classificação dos achados

| Severidade | Achado | Ação/recomendação |
|---|---|---|
| Alta para release | `uv pip check` falha por wheel CUDA/NVIDIA incompatível com a plataforma do Sandbox. | Identificar proveniência e necessidade do pacote; resolver em ambiente limpo/CPU compatível sem ignorar o erro; repetir verificação e build. Não remover dependência do lock às cegas. |
| Alta para reprodutibilidade | Dockerfile não instala lock e inclui dependências sem pin estrito. | Escolher mecanismo oficial do projeto para gerar/consumir um lock compatível com Python 3.12/Linux de produção; construir/testar imagem antes de fixar a configuração. |
| Média | Imagem base, Postgres/Redis usam tags, sem digest imutável. | Definir política de atualização e pin de digest após confirmar arquitetura e scanner; programar rebuilds de segurança. |
| Não medido | CVEs/licenças/SBOM e comportamento de conectores opcionais. | Executar scanner em CI e revisar os resultados antes da implantação externa. |

## Conclusão

O conjunto local é suficiente para executar a suíte atual, mas a checagem de compatibilidade retorna erro e a instalação de container não foi reproduzida. **Dependências não estão aprovadas para deployment até que o erro de plataforma seja resolvido e o Docker build consuma dependências controladas.** Nenhum pacote foi atualizado ou removido nesta rodada para evitar mascarar a origem do conflito.
