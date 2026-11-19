# Auditoria de análise observacional — `analysis-observation`

**Data do checkout auditado:** 2026-11-19
**Base:** `/home/ubuntu/ZIA-TRADER-v17-phase9-resume`
**Head verificado:** `09ea8c8` (`fix/backend-provider-security-nov19`)
**Modo:** somente leitura; nenhum código, menu, flag ou serviço foi alterado. O P2 de health de providers desabilitados ficou fora desta auditoria e não foi reimplementado.

## Veredito

A análise on-demand existe: `GET /core/analyze` (`api/routers/market.py:87-99`) chama `CoreCommandManager.analyze_symbol` (`core/command_manager.py:114-141`), busca um `MarketSnapshot`, executa `calculate_market_signal` e retorna `orders_sent: 0`. Esse caminho não chama `OrderManager` nem cria intenção de ordem.

A análise contínua **não existe como loop observacional independente**. As observações shadow são gravadas somente dentro do `RoboTraderUnified.start()` (`core/engine.py:212-224` e `591-638`), que é o loop de trading: ele também restaura posições, adquire lock de decisão, consulta saldo privado/estado de posição, calcula risco, e possui `OrderManager`/`ExecutionEngine` injetados. O loop só roda quando o motor de trading é iniciado pelo worker/app ou pelo endpoint de controle; `AUTO_START_ENGINES` é `false` por padrão (`config/settings.py:36`, `worker.py:35-47`, `api/application.py:59-85`). Portanto, `SHADOW_MODE_ENABLED=true` não significa “análise contínua ativa”.

Não foi demonstrado lookahead no caminho causal inspecionado: `calculate_market_signal`, `MarketSignalCache` e o cache de pullback foram comparados em replay por prefixos; o teste local encontrou zero divergências de `action`, `candidate_action` e `score` entre o cálculo do prefixo e o cache causal em 225 posições. Os pivôs de pullback são confirmados com duas barras à direita antes de serem usados. `detect_reversal_signal` compara explicitamente `data.iloc[:-1]` com o frame atual. Contudo, não há implementação identificável de `zigzag`: existem pivôs de pullback, não um componente ZigZag nomeado e com contrato de confirmação/estado.

Os testes focados já existentes passaram: **24 passed**, com um warning de depreciação de dependência.

## Achados materiais

### AO-01 — P1: shadow contínuo está acoplado ao motor de trading

**Evidência.** `TradingManager` constrói `ExecutionEngine`, `OrderManager`, `CoreCommandManager` e `RoboTraderUnified` no mesmo runtime (`core/manager.py:60-84`). O único caminho contínuo que cria `AIObservation` está dentro do loop de `RoboTraderUnified.start()` (`core/engine.py:212-224`, `591-638`). Antes de chegar à observação, esse loop consulta posição Redis, saldo da exchange, PnL, circuit breaker, microestrutura, eventos e gates de execução (`core/engine.py:480-590`). A rota on-demand não grava uma observação nem mantém estado: `analyze_symbol` termina no retorno do sinal (`core/command_manager.py:114-141`).

**Consequência verificável.** Com os defaults atuais, o processo pode estar saudável, conectado e com `SHADOW_MODE_ENABLED=true`, mas sem task de análise: `AUTO_START_ENGINES=false` impede o start automático e não existe task `analysis-observer`. Iniciar a análise contínua exige iniciar o motor de trading, embora a finalidade seja apenas observar.

**Incremento recomendado, sem adapter de ordens.** Criar um `AnalysisObserver`/`ObservationService` nativo do app que receba somente um feed de mercado read-only, o analisador determinístico e um sink de snapshots. Não deve receber `OrderManager`, `ExecutionEngine`, saldo privado, posição Redis ou `ExchangeConnector` de execução. A coleta pode usar o conector de dados de mercado existente, mas o contrato do observer deve impedir chamadas de ordem. Manter `/core/analyze` como execução única e adicionar uma flag nova, por exemplo `ANALYSIS_OBSERVER_ENABLED=false`, sem mudar as flags de trading existentes.

### AO-02 — P1: `/core/analyze` pode declarar entrada permitida apesar de histórico secundário ausente

**Evidência.** `MultiTimeframeFeed.fetch_snapshot` mantém falhas de históricos secundários em `snapshot.errors` e continua quando o histórico primário existe (`core/data_feeds.py:269-286`). `CoreCommandManager.analyze_symbol` não inspeciona esses erros e calcula `entry_allowed` somente como `signal.action in {buy,sell}` e `signal.status == good` (`core/command_manager.py:124-140`). Os defaults solicitam `1m,5m,1h` (`config/settings.py:88`), mesmo com `MULTI_TIMEFRAME_ENABLED=false`.

**Prova determinística sem rede/credenciais.** Com um frame primário fechado sintético que produz `buy/good` e um conector que falha somente em `1m` e `5m`, o retorno foi:

```text
{'action': 'buy', 'status': 'good', 'entry_allowed': True,
 'errors': {'history:1m': '1m indisponivel', 'history:5m': '5m indisponivel'},
 'orders_sent': 0}
```

Isto não envia ordem nesta rota, mas é uma saída semanticamente verde para uma análise com dados configurados como ausentes. Um consumidor pode confundir `entry_allowed` com suficiência operacional.

**Incremento recomendado.** Definir explicitamente `required_timeframes` versus `optional_timeframes`. Se multi-timeframe estiver desligado, buscar apenas o primário; se um timeframe configurado for requisito, retornar `data_sufficient=false`, `status=attention` e `entry_allowed=false` quando ele falhar. Em qualquer caso, o retorno deve expor `execution_authorized=false`, sem transformar a análise em autorização.

### AO-03 — P1: observações e snapshots não são idempotentes por candle fechado

**Evidência.** O feed remove o candle ainda aberto (`core/data_feeds.py:143-167`), mas o motor repete o mesmo último candle a cada `TRADING_LOOP_INTERVAL` de 5 segundos (`core/engine.py:769-788`, `config/settings.py:86`). Cada passagem chama `create_ai_observation` (`core/engine.py:591-638`). O modelo `AIObservation` identifica símbolo e `observed_at`, mas não possui timestamp do candle-fonte, timeframe, hash de entrada ou chave única (`database.py:249-272`); `DatabaseManager.create_ai_observation` sempre insere outra linha (`database_manager.py:614-642`). O `DecisionSnapshot` também usa `utc_now()` quando não recebe `observed_at` (`database_manager.py:674-704`), portanto não é uma deduplicação por candle.

**Prova determinística.** Duas chamadas com o mesmo payload de observação produziram `duplicate_rows_for_same_payload=2` no SQLite temporário. No loop real, as chamadas repetidas no mesmo candle carregam ainda latência, timestamp e contexto possivelmente diferentes, mas não carregam uma identidade temporal que permita distinguir “novo dado” de “reprocessamento”.

**Incremento recomendado.** Persistir `source_candle_at`, `timeframe`, `source_data_hash` e `analysis_version`; usar uma chave idempotente por `(symbol, timeframe, source_candle_at, mode, analysis_version)` e um snapshot derivado dessa mesma identidade. Manter `observed_at` como hora de processamento, separada do timestamp do dado. Uma nova barra deve gerar uma nova identidade; repetir a mesma barra deve fazer upsert/ignore, não outra observação.

### AO-04 — P2: regime/reversão são leituras instantâneas; não há estado ativo nem ZigZag causal com contrato próprio

**Evidência.** `MarketRegimeDetector.detect` apenas calcula o `tail(lookback)` e retorna uma classificação; não guarda regime anterior, confirmação, transição, validade ou debounce (`core/regime_detector.py:11-49`). `detect_reversal_signal` compara somente o sinal do frame sem a última barra com o sinal do frame atual e retorna um dicionário efêmero (`core/market_signals.py:375-403`). Não existe símbolo/função `zigzag` no código auditado; a única lógica semelhante é `_last_confirmed_pivots` do pullback (`core/pullback_strategy.py:55-65`), que é um conjunto de pivôs confirmados e não uma máquina de estado ZigZag.

**Consequência.** Repetir a análise do mesmo candle pode produzir o mesmo evento de reversão, sem `event_id`, `confirmed_at`, expiração ou indicação de que o evento já foi emitido. O observador futuro não poderá afirmar “transição nova” versus “mesmo estado reavaliado”; e não deve chamar os pivôs existentes de ZigZag.

**Incremento recomendado.** Introduzir um estado observacional por símbolo/timeframe contendo `last_source_candle_at`, regime anterior, regime atual, último evento de reversão emitido e expiração. Modelar estados `unknown`, `pending` e `confirmed`; emitir uma transição uma vez por candle-fonte. Se ZigZag for requisito, criar um componente explícito que confirme pivôs somente após as barras à direita, exponha `pending/confirmed` e seja validado por replay causal; não reutilizar uma série de pivôs retrospectiva como se fosse o ZigZag ativo.

### AO-05 — P2: `MarketRegimeDetector` falha aberto quando chamado fora do feed validado

**Evidência e reprodução.** O detector só verifica `len(df) < lookback` e acessa `high`, `low` e `close` sem validar colunas, finitude ou positividade (`core/regime_detector.py:17-32`). Com 20 linhas contendo `NaN`, retornou:

```text
{'regime': 'normal', 'volatility_index': 1.0,
 'trend_index': nan, 'action_multiplier': 1.0}
```

Com `close` sem `high/low`, lançou `KeyError`. O caminho atual do `MultiTimeframeFeed` normalmente bloqueia OHLCV inválido antes do detector, portanto este não é um bypass comprovado do runtime presente; é uma falha demonstrável da função de análise que será relevante para um observer, replay ou consumidor direto.

**Incremento recomendado.** Validar `high/low/close`, converter numericamente, rejeitar NaN/inf/preços não positivos e retornar `regime=unknown`, `status=bad_data` e motivo seguro. O `TrendAlignmentFilter` já bloqueia `unknown`; o detector não deve transformar dados inválidos em `normal`.

## Causalidade, lookahead e aprendizagem posterior

- `calculate_market_signal` exige pelo menos 35 barras e retorna `bad_data` abaixo desse limite (`core/market_signals.py:66-106`). A validação de feed exige OHLCV completo antes do runtime (`core/dataset_integrity.py:29-66`).
- O replay local de `MarketSignalCache.at(position)` contra `calculate_market_signal(frame.iloc[:position+1])` teve **0 divergências** nas posições 35–259 de um frame determinístico de 260 barras.
- O pullback usa confirmação de pivô com duas barras à direita; no cache, `_confirmed_pairs` só disponibiliza o pivô após `pivot_index + 2 <= current_index` (`core/pullback_strategy.py:355-366`). Isso é causal, mas não é ZigZag.
- `detect_reversal_signal` não leu barras futuras além do último frame entregue no teste; o problema é a ausência de estado/identidade, não lookahead demonstrado.
- `SignalLearningLayer.label_observation` usa candles futuros para rotular uma observação (`core/learning_layer.py:52-90`). Isso é correto somente como etapa posterior de avaliação; o futuro não pode ser colocado no snapshot “before” nem no cálculo ao vivo do observer.

## Desenho do incremento nativo, default OFF (não implantado)

1. **Flag e contrato:** adicionar `ANALYSIS_OBSERVER_ENABLED=false`, intervalo positivo, timeout por ciclo e limite de concorrência. O default deve manter zero tasks observacionais.
2. **Lifecycle:** no lifespan da aplicação, após runtime de dados estar pronto, criar no máximo uma task nomeada `analysis-observer` somente quando a flag estiver explicitamente ativa. No shutdown, sinalizar parada, cancelar, aguardar a task e fechar somente recursos que pertençam ao observer. Não iniciar `trading_engine` como efeito colateral. O worker deve seguir a mesma decisão explícita, sem agendamento externo.
3. **Timeout/concurrency:** usar timeout por símbolo/ciclo; uma fonte travada não pode prender o ciclo seguinte. Usar semáforo global limitado e uma chave por `(symbol,timeframe)` para impedir sobreposição. Em processo com múltiplos workers, a chave idempotente no banco é obrigatória; um lock em memória sozinho não basta.
4. **Dados e snapshot:** consumir somente candles fechados, quote/order-book público quando necessário e contexto de notícias explicitamente disponível. Salvar `mode=observation`/`shadow`, identidade do candle-fonte, qualidade/erros, regime, reversão, pivôs confirmados, features e hashes. O snapshot deve declarar sempre `execution_authorized=false` e `orders_sent=0`; não deve possuir caminho para `OrderManager`.
5. **Separação de decisão:** manter o analisador puro e reutilizável por `/core/analyze`, observer e replay. A análise deve produzir diagnóstico; qualquer autorização de ordem continua em outro caminho e permanece bloqueada pelos defaults existentes.
6. **Retenção de estado:** persistir a última identidade processada e os eventos de regime/reversão com upsert/idempotência. A rotulagem futura deve ocorrer em job/ação posterior e nunca alterar retroativamente o contexto causal “before”.

## Critérios binários de aceite

- Com `Settings()` padrão, não existe task `analysis-observer`, nenhum `AIObservation` é criado e nenhum motor de trading é iniciado automaticamente.
- Com `ANALYSIS_OBSERVER_ENABLED=true` em teste, o observer inicia e encerra pelo lifespan sem construir nem receber `OrderManager`/`ExecutionEngine`; um stub de adapter de ordens que lança exceção não impede a análise read-only.
- Um provider que não responde faz o ciclo daquele símbolo terminar dentro do timeout configurado; a task permanece cancelável e o próximo ciclo consegue rodar.
- Com N símbolos, a concorrência observada nunca excede o limite configurado e duas execuções do mesmo símbolo/timeframe nunca ficam simultâneas.
- Três ciclos sobre o mesmo candle fechado produzem exatamente uma identidade de observação e um snapshot; ao acrescentar um candle fechado, produzem exatamente uma nova identidade.
- Histórico primário válido com timeframe obrigatório ausente retorna `data_sufficient=false`/`status=attention` e `entry_allowed=false`; nenhuma resposta de análise retorna `execution_authorized=true`.
- Um frame de regime com NaN ou sem OHLC obrigatório retorna `unknown`/`bad_data` e nunca `normal`.
- Replay prefixado confirma que cada snapshot do candle `t` é igual ao cálculo usando dados até `t`, sem uso de linha posterior; o teste também comprova que labels futuros só aparecem depois da janela de horizonte.
- Repetir o mesmo candle não emite uma nova transição de reversão; uma nova transição tem identidade, candle-fonte e estado `confirmed` explícitos.

## Conclusão

O core já oferece uma leitura on-demand segura e componentes determinísticos úteis, mas não oferece ainda uma análise periódica nativa separada do motor de trading. O próximo incremento deve ser observacional, default OFF, limitado por lifecycle/timeout/concurrency, idempotente por candle e incapaz de autorizar ordens. A correção prioritária é separar esse loop do `RoboTraderUnified` e tornar suficiência temporal e identidade de snapshot contratos verificáveis; a correção do P2 de health de providers desabilitados permanece com o pai.
