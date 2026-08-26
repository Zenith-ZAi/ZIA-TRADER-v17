# Lacunas de produção estruturalmente endereçadas

**Status da implementação:** código e lógica ampliados no Sandbox; trading mainnet continua desabilitado por padrão.  
**Escopo:** reconciliação, idempotência, proteção pós-fill, adapter mainnet fail-closed, rate limiting, paridade de features, treinamento OOS e hardening de container.

> **Importante:** este documento descreve prontidão estrutural. Ele não comprova rentabilidade, assertividade financeira nem substitui homologação independente, revisão de segurança ou operação em infraestrutura persistente.

## P0 — execução e estado

| Lacuna | Implementação | Limite mantido |
|---|---|---|
| Reconciliação | `core/reconciliation.py` (`OrderReconciler`) persiste `client_order_id`, compara ordens/posições e grava snapshots. | O adapter precisa fornecer dados remotos; diferenças ficam em `attention` e não são silenciosamente corrigidas. |
| Idempotência | `DatabaseManager.reserve_order_intent()` usa identificador único; retries reutilizam o mesmo ID. | Retry seguro depende de o adapter/exchange respeitar `clientOrderId`; falha ambígua não deve ser tratada como ausência de execução. |
| Backoff | `submit_with_retry()` usa tentativas limitadas e backoff exponencial. | Não há retry infinito nem repetição com novo identificador. |
| OCO/bracket | `execution/oco_manager.py` anexa stop e take-profit após fill e persiste proteções. | Adapter nativo OCO é preferível; fallback separado exige reconciliação e cancelamento da proteção oposta após fill. |
| Mainnet | `execution/mainnet_adapter.py` aceita somente `api.binance.com`, `BINANCE_MODE=live`, `LIVE_TRADING_ENABLED=true`, `LIVE_MODE=true` e `SHADOW_MODE_ENABLED=false`. | O padrão continua bloqueado; não há ativação automática nem credenciais no repositório. |
| Kill switch | Mainnet possui ativação, cancelamento de ordens abertas e bloqueio de novas ordens; API administrativa registra o evento. | O kill switch deve ser testado em infraestrutura real e integrado a alertas externos antes de produção. |

## P1 — API, features e imagem

O `RequestRateLimitMiddleware` aplica limites independentes por IP e por token/usuário, retorna `429` com `Retry-After` e mantém a classe `RateLimiter` reutilizável. A rota autenticada `/test_rate_limit` permite teste controlado no Sandbox.

`core/feature_pipeline.py` fornece uma fachada única usada pelo motor live, pelo backtest e pelo treinamento. A transformação causal permanece no módulo de features existente, reduzindo o risco de diferenças entre pesquisa e execução.

O `Dockerfile` agora declara `PYTHONBUFFERED=1` e `PYTHONOPTIMIZE=1`, cria usuário não-root `nonroot:nonroot`, restringe a propriedade de `/app` e mantém a execução da API sem privilégios. `requirements.lock` registra o ambiente instalado no Sandbox; ele deve ser revisado e reconstruído em CI para evitar incorporar dependências transitivas não aprovadas.

## Aprendizado supervisionado

`learning/training_pipeline.py` implementa split cronológico, gap de purga, métricas OOS de precisão, recall, F1, balanced accuracy, cobertura, Sharpe proxy e calibração por faixas de confiança. O candidato só é publicado quando supera o piso de validação e o melhor modelo anterior; os artefatos anteriores são copiados para um diretório de rollback.

O pipeline não fabrica dados, não treina Transformer/LSTM automaticamente e não chama treinamento no loop live. O treino continua sendo uma operação manual com dataset OHLCV real, versionado e aprovado.

## Comandos e validação

```bash
python3 -m compileall -q core execution api learning config scripts
python3 -m pytest -q
python3 -m pytest -q tests/test_production_gaps.py
python3 -m learning.training_pipeline data/ohlcv.csv --model-dir models
```

Os testes P0/P1 cobrem retry com o mesmo `clientOrderId`, reuso idempotente, diferenças de posição, proteção parcial, fail-closed da mainnet, rate limiter e paridade de schema do pipeline. O comando de treinamento falha explicitamente quando não há dataset suficiente ou quando as classes `sell`, `hold` e `buy` não estão representadas.

## Próximos 10% de infraestrutura

Os itens que permanecem fora do Sandbox são TLS e proxy reverso, firewall/WAF, secret manager e rotação de credenciais, PostgreSQL/Redis gerenciados com backup e restauração testados, alta disponibilidade, filas/eventos distribuídos, alertas 24/7, SLOs, incident response e treinamento em escala. O deploy deve começar em paper/Demo/Testnet, com permissões mínimas e capital real desabilitado.

## Resultado da execução desta sessão

O comando `python3 scripts/update_core.py` foi executado após a integração final. A compilação dos pacotes `core`, `execution`, `api`, `learning`, `config` e `scripts` passou; a suíte completa terminou com **74 testes aprovados**; e os dois diagramas foram regenerados com sucesso. O resumo foi salvo em `logs/test_report.log`.

O pipeline OOS também foi executado manualmente com o dataset público `data/replay_btcusdt_1h.csv`, em `/tmp/zia-ensemble-candidate`, sem substituir modelos do repositório. O recorte gerou 93 linhas de validação e 93 de teste. O F1 macro foi `0,3476` na validação e `0,2806` no teste; o Sharpe proxy do teste foi `-0,6795`. O candidato não foi promovido para `models/` nem habilitado no worker, porque o teste fora da amostra não sustenta uma decisão de produção. Esse resultado confirma que o pipeline funciona e, ao mesmo tempo, evita transformar treinamento estrutural em afirmação de vantagem financeira.
