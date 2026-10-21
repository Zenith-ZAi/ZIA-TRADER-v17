# Evidências de testes — Fase 7

**Data:** 2026-10-21. **Ambiente:** Sandbox Linux, Python 3.12.3, virtualenv `/home/ubuntu/.venvs/zia-v17`. Nenhuma ordem real, exchange, VPS ou serviço de produção foi acessado.

## Baseline e resultado atual

| Momento | Comando | Resultado | Observação |
|---|---|---|---|
| Baseline documentado antes das alterações desta branch | `python -m pytest -q` | 178 passed, 3 skipped, 1 warning | Registro em `docs/BASELINE_REPORT.md`, commit base `861d5f9`. |
| Baseline herdado após integrações de segurança PR #17 | suíte local anterior reportada | 186 passed, 3 skipped, 1 warning | Evidência herdada do estado de trabalho; não substitui o comando final desta branch. |
| Final desta branch | `/home/ubuntu/.venvs/zia-v17/bin/python -m pytest -q` | **189 passed, 3 skipped, 1 warning**, 21.28 s | Três testes novos cobrem preço de execução causal e preflight Alembic com/sem head. |

O warning atual é `PendingDeprecationWarning` de `starlette/formparsers.py:12`, recomendando `import python_multipart`. Os três skips são mantidos pela configuração da suíte; o teste PostgreSQL de migrations exige `TEST_DATABASE_URL`, que não estava definida no Sandbox.

## Checks focados adicionais

| Comando | Resultado | Escopo |
|---|---|---|
| `pytest -q tests/test_api.py tests/test_final_safety_gates.py tests/test_e2e_resilience.py tests/test_phase5_broker_resilience.py` | 22 passed, 1 warning | API, gates, resiliência e broker fake. |
| `pytest -q tests/test_stress.py tests/test_feed_quality.py tests/test_feed_persistence.py` | 23 passed | Look-ahead/fallback causal, OHLCV incompleto, feeds e persistência. |
| `pytest -q tests/test_vps_preparation.py tests/test_database_migrations.py` | 8 passed, 1 skipped | Preflight, Alembic local, banco temporário; PostgreSQL não disponível localmente. |
| `python -m compileall -q .` | exit 0 | Compilação geral. |
| `git diff --check` | exit 0 | Sem whitespace/error de patch no diff verificado. |
| Parser PyYAML 6.0.3 + asserts estáticos dos dois Compose | passou | Estrutura YAML, comando db-init, flags, bind local e hardening; não é `docker compose config`. |
| `uv pip check --python /home/ubuntu/.venvs/zia-v17/bin/python` | **exit 1** | 194 pacotes; uma incompatibilidade de plataforma em `nvidia-cusparselt-cu13`. Não escondido nem ignorado. |

## CI remoto

A última execução de baseline antes da branch foi `ZIA Trader CI`, run `39361245138`, conclusão `success`, branch `master`, criada em 2026-10-20. Após o push da implementação, o CI do PR #18 (workflow run `39635864347`) concluiu com os jobs `test` e `container` em **SUCCESS**; o status CodeRabbit foi “Review skipped”, portanto não é uma revisão de código aprovada. O PR #18 foi integrado em 2026-10-21 no merge commit `847e09a7beeac643b2837e6e00d5b42a249a468c`. O CI valida a branch submetida ao PR; não substitui build/execução em uma VPS real.

## Limites das evidências

- Testes sintéticos/fakes verificam invariantes de engenharia, não retorno, calibração, desempenho, vantagem econômica ou comportamento de um venue real.
- Nenhum dataset de procedência verificada ou modelo aprovado foi localizado; nenhum treino, promoção ou medição de performance de mercado foi executado.
- Nenhuma conexão, consulta transacional ou ordem foi enviada a broker/exchange.
- Docker/Compose, PostgreSQL, Redis, TLS, VPS e backup/restore externos não foram testados no Sandbox desta rodada.
