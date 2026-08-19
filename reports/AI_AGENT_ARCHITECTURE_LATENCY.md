# Arquitetura do agente ZIA-TRADER-v17 e latência

**Data:** 19 de agosto de 2026 UTC  
**Modo avaliado:** shadow/research, sem ordens  
**Autor:** Manus AI

> Este documento descreve o software. Ele não garante precisão, lucro ou execução em uma exchange real.

## 1. Como o banco da IA é usado

O banco não é um cérebro que aprende automaticamente a cada inserção. Ele é uma camada de memória, auditoria e rotulagem futura. A tabela `ai_observations` registra, por ciclo e símbolo, a ação final, a ação candidata, a confiança do modelo, a confiança do sinal determinístico, o preço, o sentimento de notícias, a tendência externa, o bloqueio econômico, a validação de risco, as features causais e as latências. Os campos `forward_return` e `outcome_label` existem para receber o resultado futuro somente quando a janela posterior estiver disponível.

O ciclo correto é: observar uma barra fechada; calcular features sem dados futuros; combinar modelos e estratégias; registrar a decisão no banco; aguardar a janela de avaliação; rotular o retorno futuro; medir precisão, calibração, PnL, drawdown e Sharpe por regime; e só então aceitar uma nova versão do modelo. Inserir observações, sozinho, não treina o Ensemble nem transforma uma previsão em conhecimento confiável.

## 2. Função das estratégias

| Camada | Papel | Pode autorizar sozinha? |
|---|---|---|
| Ensemble RF/XGBoost | Prediz `buy`, `sell` ou `hold` a partir de OHLCV causal e fornece confiança | Não |
| Transformer/LSTM | Só participam quando existem pesos aprovados e `NEURAL_MODELS_ENABLED=true` | Não |
| MarketSignal | Calcula EMA, MACD, RSI, ATR, volume, volatilidade, notícias e tendência externa | Não |
| Pullback/Softskill | Confirma macro, pivôs, toque, exaustão, rompimento, stop, alvo e breakeven | Não |
| Reversão | Contextualiza divergência/mudança causal e fica registrada para auditoria | Não |
| WhaleDetector | Mede concentração, notional e imbalance do livro; não prova que uma ordem pertence a uma baleia | Não |
| Sniper | Observa volatilidade rápida, exige Whale alinhada, sinal determinístico, Pullback, evento livre e RiskAI | Não |
| RiskAI | Confere saldo privado, exposição, perda, preço, confiança e sizing | Não |
| EventGuard | Bloqueia entradas na janela econômica configurada | Não; pode bloquear |

No motor principal, a decisão precisa passar pelo consenso entre modelo, `MarketSignal`, Pullback quando habilitado, calendário e RiskAI. No Sniper, volatilidade isolada não basta. A autonomia continua desativada por padrão.

## 3. Precisão não é latência

Precisão é uma propriedade estatística medida fora da amostra; latência é o tempo de processamento e comunicação. Um sistema pode decidir em poucos milissegundos e estar errado. Da mesma forma, uma decisão com boa precisão histórica pode ser inviável se a informação chegar atrasada ou se o preço mudar antes do preenchimento.

O benchmark local foi executado em 100 repetições sobre 600 candles OHLCV públicos reais. Ele mede somente o processo Python local e não mede TLS, roteamento, WebSocket/REST, fila da exchange, matching engine, confirmação ou preenchimento.

| Componente | p50 local | p95 local | Observação |
|---|---:|---:|---|
| Features causais | 6,84 ms | 9,47 ms | CPU/Pandas |
| Ensemble | 6,19 ms | 9,34 ms | Artefatos treinados |
| MarketSignal com Pullback recalculado | 54,98 ms | 63,21 ms | Gargalo antigo |
| MarketSignal com Pullback pré-calculado | 4,36 ms | 4,90 ms | Caminho otimizado |
| PullbackSignalCache construído | 80,64 ms | 124,56 ms | Deve ser reutilizado, não criado a cada tick |
| Decisão local completa sem cache | 70,15 ms | 82,24 ms | Baseline |
| Decisão local completa com Pullback cacheado | 17,93 ms | 21,25 ms | Resultado atual do caminho rápido |

O cache melhora a decisão depois de construído, mas construir um cache completo em cada tick ainda é caro. Em operação real, o cache deve ser mantido por símbolo e invalidado apenas quando a barra fechada ou o fingerprint OHLCV mudar. Para buscar p50 de 1–3 ms, será necessário um caminho incremental/vectorizado, modelo exportado para runtime de baixa latência e benchmark no mesmo hardware de produção. Uma GPU disponível não reduz a latência de rede da exchange e pode aumentar o tempo de transferência se o lote for pequeno.

## 4. O que acontece na entrada e saída

A entrada não deve ser disparada pela palavra “precisão”. O agente só deve produzir uma ordem candidata quando direção, confiança, volatilidade, confluência, Whale/Softskill quando exigidas, eventos, saldo, filtros da exchange e RiskAI estiverem aprovados. O `ExecutionEngine` então valida símbolo, ação e quantidade, chama a fachada da exchange e grava a posição no cache. A execução real ainda depende da exchange e deve ser reconciliada por status, fills parciais, comissão, posição e saldo.

A saída precisa ser uma política explícita de posição, não somente o sinal contrário do modelo. O código já possui níveis ATR no Pullback e validação de risco, mas a produção ainda requer reconciliação robusta, stop/OCO ou equivalente suportado pela exchange, idempotência e kill switch. Sem esses elementos, alta velocidade pode aumentar o risco em vez de melhorar o agente.

## 5. Estado atual e próximos critérios

A última calibração temporal real apresentou Sharpe de 0,2952 no teste posterior, com 19 operações. O Ensemble apresentou balanced accuracy de 37,22% e F1 macro de 35,17%. Esses resultados não sustentam a afirmação de precisão suficiente para capital real. O banco shadow e a observabilidade agora permitem medir cada estratégia por separado, mas o período de aprendizagem ainda precisa acumular rótulos futuros e múltiplos regimes.

A promoção deve exigir uma janela de treino, uma janela de calibração e uma janela final intocada; mínimo de operações definido antes do teste; slippage, comissão e latência incluídos; métricas por `principal`, `sniper`, `whale-aligned`, `pullback` e `hold`; e aprovação independente do drawdown, da estabilidade do Sharpe e da calibração de confiança. Até cumprir esses critérios, a configuração recomendada é shadow mode com ordens desativadas.

## 6. Segurança operacional

Os defaults permanecem `AUTONOMOUS_TRADING_ENABLED=false`, `NEURAL_MODELS_ENABLED=false`, `SNIPER_ENABLED=false` e `SHADOW_MODE_ENABLED=true`. O replay de validação bloqueia `place_order` explicitamente. O próximo passo seguro é um replay histórico com timestamps intermediários para rotular `forward_return` e `outcome_label`, seguido de shadow em tempo real sem ordens.
