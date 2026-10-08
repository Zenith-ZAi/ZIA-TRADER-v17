# Fase 4 — performance e paridade live/backtest

**Data:** 2026-10-07

**Branch de trabalho:** `refine/phase4-parity-performance`

**Estado:** Fase 4 integrada na PR #13; follow-up de warm-up aprovado, validado localmente e com CI verde na PR #14, aguardando merge. Limitações de paridade end-to-end permanecem explícitas.

## Escopo implementado

### Transporte e I/O assíncrono

- `infra/async_http.py` agora retenta somente `GET`/`HEAD` em falhas de transporte e respostas transitórias (`408`, `425`, `429`, `500`, `502`, `503`, `504`). O backoff é exponencial, recebe jitter, respeita `Retry-After` numérico em `429` e tem limites superiores de segurança.
- O circuito por provedor, a concorrência limitada, métricas, timeout HTTP e cache local existente foram preservados.
- `run_sync` executa operações bloqueantes read-only em thread com timeout, retry/circuit breaker. A chamada antiga `forex-python` do adapter público Forex foi encaminhada por essa rota; o fallback Yahoo permanece inalterado.
- Adapters read-only que criam seu próprio cliente fecham-no no lifecycle e o recriam ao reconectar; clientes compartilhados não são fechados pelo adapter.
- Novas variáveis de configuração têm defaults conservadores: 2 retries, backoff base de 0,25 s, teto de 2 s e jitter de 25%. Nenhum modo live foi habilitado.
- **Limite:** cancelar a espera por `asyncio.to_thread` não termina à força a operação já iniciada na thread. O provider precisa terminar por conta própria; o circuito limita novas tentativas, mas não equivale a cancelamento do I/O subjacente.

### Caches

- `FeatureFrameCache` atualiza features em append-only somente se o histórico anterior continuar idêntico como prefixo e as novas barras forem finitas. Índice alterado, candle revisado, janela móvel ou dado inválido faz fallback para `build_feature_frame` canônico.
- `PullbackSignalCache` e `PullbackCacheRegistry` atualizam EMA, RSI, ATR, volume e pivôs apenas para barras anexadas e preservam o cálculo canônico como referência. Correções, reordenação ou janela móvel invalidam o incremental e reconstroem o cache.
- As fórmulas canônicas e os gates de ordem/risco não foram alterados. Os testes verificam equivalência numérica com tolerância `1e-12` em fixtures determinísticas locais.
- **Limite:** se a fonte entrega uma janela de tamanho fixo que desliza ou revisa o candle em formação, o cache deliberadamente refaz o cálculo canônico para preservar a semântica. A otimização evita trabalho em snapshots idênticos e em crescimento append-only; não elimina o recálculo nesses casos.

### Paridade

- O teste compara `calculate_market_signal` com `MarketSignalCache` sobre as mesmas sequências determinísticas de OHLCV e verifica `action`, `candidate_action`, `status`, `regime`, `confidence`, `score` e `volatility`.
- O teste de pullback compara estados de decisão e valores numéricos contra o cálculo direto em cada prefixo, exceto texto de explicação (`reasons`), que já tem redação diferente entre os caminhos.
- **Não é uma certificação end-to-end:** não foram incluídos ordem-flow, notícias, modelo IA, calendário externo, gates de risco, estado do broker nem a etapa final de execução. Não havia dataset de mercado com procedência verificada no checkout; fixtures sintéticas servem apenas para testar invariantes.

## Divergência corrigida e limitações remanescentes

1. **Aquecimento do cache de pullback em um candle — corrigido no follow-up aprovado em 2026-10-08:** o guard incremental agora aceita o primeiro prefixo válido do cálculo canônico (`index >= max(ema_period, 40) + 1`). Com `ema_period=50` e prefixo de 52 barras (posição 51), ambos os caminhos retornam `candidate_action="buy"` e `action="hold"`. `test_pullback_cache_matches_canonical_at_warmup_boundary` e a comparação prefixo a prefixo verificam a fronteira. Nenhuma fórmula canônica foi modificada.
2. **Timeout de operação síncrona:** `asyncio.wait_for` limita a espera da coroutine, mas não pode encerrar a thread subjacente. Se a biblioteca do provider ignorar seu timeout próprio, a thread pode continuar. Considerar uma API realmente assíncrona com timeout explícito ou isolamento/bounded worker dedicado antes de depender desse fallback em produção.
3. **Paridade de produção não verificada:** é necessário validar com as mesmas barras fechadas, parâmetros e dados externos que alimentam live e backtest, em Demo/shadow. As diferenças de input externo e de gates finais não são resolvidas por este teste.

As referências detalhadas e correções sugeridas também estão em [`FINDINGS.md`](../FINDINGS.md).

## Validação local

| Verificação | Baseline antes da Fase 4 | Após as mudanças | Resultado |
|---|---:|---:|---|
| `python3 -m compileall -q .` | executado sem saída de erro | executado sem saída de erro | passou |
| `git diff --check` | executado sem saída de erro | executado sem saída de erro | passou |
| `python3 -m pytest -q` | 120 passed, 3 skipped (25,13 s) antes da Fase 4 | 132 passed, 3 skipped (29,51 s) após o follow-up | passou; contagem mantida |
| Testes focalizados atuais (`test_phase4_parity.py`) | — | 8 passed (4,29 s) | passou |
| CI GitHub Actions da PR #13 | — | PostgreSQL 16: 135 passed, 2 warnings; build do container aprovado | passou |
| CI GitHub Actions da PR #14 (run `37778660559`, SHA `8e65daa`) | — | PostgreSQL 16: 135 passed, 2 warnings; build do container aprovado | passou |

Os 3 skips ocorreram somente na execução local; a CI da PR #14 testou com PostgreSQL 16. Os warnings reportados pelo pytest não impediram os checks. VPS e broker não foram verificados.

## Arquivos alterados

- `infra/async_http.py`, `config/settings.py`, `core/manager.py`, `data/news_processor.py`, `execution/market_connector.py`, `.env.example`, `.env.vps.example`
- `core/feature_pipeline.py`, `core/pullback_strategy.py` (somente estado/cache incremental), `core/pullback_registry.py`
- `tests/test_p0_async_and_locks.py`, `tests/test_phase4_parity.py`
- `docs/FINDINGS.md`, este relatório

`execution/market_connector.py` contém métodos de ordens para adapters; **nenhum método de colocar/cancelar ordem foi alterado**. `core/pullback_strategy.py` contém o cálculo canônico; a função `calculate_pullback_signal` e seu gate foram mantidos sem edição. Os testes reportam explicitamente a diferença preexistente do cache em vez de suprimi-la.
