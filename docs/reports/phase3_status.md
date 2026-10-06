# Fase 3 — status de refinamento e histórico técnico

- **Data:** 2026-10-06
- **Branch de trabalho:** `refine/phase3-ai-validation`
- **Estado:** implementação local concluída; validação real de performance pendente de dataset OHLCV verificado.

## Limite importante desta entrega

Não encontrei CSV/Parquet OHLCV verificado no checkout. O diretório `data/` contém arquivos de protocolo/notícias e um banco SQLite local, mas não usei nenhum deles como histórico de mercado: a procedência e a semântica dos dados não foram confirmadas. Portanto:

- **nenhum treinamento real foi executado**;
- **nenhuma métrica de mercado foi calculada nesta sessão**;
- **nenhum modelo foi aprovado, promovido ou comitado**;
- fixtures de teste são apenas casos determinísticos para testar contratos e não aparecem como resultados de investimento.

O gerador automático cria `docs/reports/model-validation-latest.md` quando o pipeline recebe um dataset válido e completa o walk-forward. O relatório abaixo registra o estado do trabalho, não uma avaliação de performance.

## Ajustes técnicos implementados na Fase 3

- Walk-forward expanding, temporal e past-only; purge pelo horizonte, embargo configurável e blocos OOS não sobrepostos.
- Baselines buy-and-hold e momentum passado de 20 barras; custos/slippage explicitados e cobrados por turnover.
- Métricas classificatórias por fold/regime, Brier multiclasses, ECE top-label e reliability curve.
- Gates de promoção existentes preservados e reforçados: exigem calibração em validation/test/walk-forward e superação líquida dos dois baselines.
- Seed configurável e determinismo dos estimadores (`n_jobs=1`); versão vinculada à hash do dataset e hash dos artefatos.
- Integração com as tabelas `model_registry`/`model_metrics` já presentes; registro antes de ativar, bloqueio de promoção direta, serialização de ativações concorrentes em PostgreSQL e verificação do hash dos arquivos copiados.
- Monitor invocável de data/performance drift, alerta estruturado, hold persistente e tentativa de rollback somente após verificar o hash do backup; `Ensemble.predict` retorna `hold` até revisão manual.
- A entrada antiga `ai/train_ensemble.py` agora delega ao pipeline controlado e não pode mais gravar artefatos sem os gates.
- Transformer com `batch_first=True` interno e contrato de entrada/saída sequence-first preservado; equivalência numérica validada.
- Teste causal: alterar um candle futuro não muda features passadas, mas pode alterar o label que depende daquele retorno futuro.

## Histórico de PRs recentes já integrados

| PR | Data de merge | Ajustes confirmados |
| --- | --- | --- |
| [#9](https://github.com/Zenith-ZAi/ZIA-TRADER-v17/pull/9) | 2026-10-04 | Corrigiu consumo do contrato JWT `sub` no endpoint de usuário e no WebSocket autenticado; adicionou cobertura para dashboard/WebSocket. |
| [#10](https://github.com/Zenith-ZAi/ZIA-TRADER-v17/pull/10) | 2026-10-04 | Adicionou Alembic/PostgreSQL versionado, pool configurável, adoção de schema legado, backup/restore e job PostgreSQL no CI. |
| [#11](https://github.com/Zenith-ZAi/ZIA-TRADER-v17/pull/11) | 2026-10-05 | Adicionou validação de feed, persistência idempotente de gaps, observabilidade de cobertura/cadência/staleness e snapshots de order book com retenção. |

Esses ajustes foram conferidos pelos metadados e descrições das PRs do repositório; não representam meses de dados ou resultados operacionais.

## Validação local

Antes das mudanças da Fase 3, a master executou `101 passed, 2 skipped` em `pytest`; `compileall` e `git diff --check` passaram. O único aviso era o aviso de performance do Transformer (`batch_first=False`). Após todas as alterações, a suíte completa executou **120 passed, 3 skipped**, sem warnings; `compileall` e `git diff --check` também passaram. Um dos skips é o round-trip do registry PostgreSQL, que é executado quando `TEST_DATABASE_URL` está disponível no CI. A CI remota desta nova branch ainda precisa concluir antes de integrar/fechar a PR.

## Pressupostos e limitações

- Custos padrão do comando (10 bps de custo + 5 bps de slippage) são exemplos explícitos, não estimativas para um ativo ou venue. Ajuste-os antes de usar dados reais.
- O retorno agregado é soma aritmética de blocos com notional fixo; não é simulação de carteira ou execução.
- O baseline short é simétrico e não modela borrow/funding/margem.
- O Sharpe proxy legado mantém a anualização fixa `sqrt(252)` por compatibilidade; não conhece o timeframe.
- O monitor de drift depende de uma entrada recente rotulada e é invocável, mas não foi agendado; o repositório ainda não tem um fluxo online de labels validado para monitoramento contínuo.
- O estado de drift exige revisão manual para liberação; não há limpeza automática do hold.

## Arquivos principais

Implementações em `learning/model_validation.py`, `learning/model_registry.py`, `learning/model_drift.py`, `learning/training_pipeline.py`, `ai/ensemble_model.py`, `ai/train_ensemble.py` e `ai/price_transformer_model.py`; testes dedicados em `tests/`. Nenhum arquivo de `core/engine.py`, `risk/` ou `execution/` foi alterado.
