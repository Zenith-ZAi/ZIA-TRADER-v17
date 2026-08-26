# Avaliação técnica pós-validação — ZIA-TRADER-v17

**Data da avaliação:** 26 de agosto de 2026  
**Base principal:** branch `master`, commit `994c9bb`, com a correção de runtime do `asyncio` validada posteriormente.  
**Escopo:** arquitetura, infraestrutura, segurança, análise de mercado, estratégias, aprendizado, comportamento ao vivo, impacto operacional e lacunas de produção.

> **Conclusão executiva:** o projeto está bem estruturado para pesquisa, backtest, shadow mode e homologação em Binance Demo/Testnet. Ele ainda não deve operar capital real. A maior limitação não é a quantidade de módulos, mas a ausência de modelo treinado validado fora da amostra, reconciliação de execução, proteção de posição por OCO/bracket, infraestrutura persistente endurecida e evidência estatística suficiente.

## 1. Resultado geral em números

Os números abaixo são **scores de engenharia**, não probabilidade de lucro nem taxa de acerto. A avaliação separa qualidade estrutural, robustez de IA e prontidão para dinheiro real, porque uma base de código modular pode existir antes de a estratégia possuir evidência estatística.

| Dimensão | Score | Leitura técnica |
|---|---:|---|
| Qualidade estrutural do código | **78/100** | Boa separação de módulos, contratos claros, documentação e 67 testes aprovados; ainda faltam lint/type checking sistemático e maior cobertura de falhas distribuídas. |
| Análise determinística de mercado | **72/100** | EMA, RSI, MACD, ATR, volume, fluxo, pullback, notícias, tendências e regimes estão integrados; calibração por ativo/regime ainda é limitada. |
| Backtest e pesquisa causal | **64/100** | Há walk-forward, fricção, taxas, stops, PnL, Sharpe e drawdown; a paridade completa com o caminho live ainda não é total. |
| Risco e gates de decisão | **74/100** | Existem limites de exposição, risco, saldo, microestrutura, circuito, eventos, notícias e estado diário 5x2; faltam reconciliação e proteção de ordens mais completa. |
| Segurança de aplicação | **68/100** | Segredos por ambiente, JWT, RBAC, confirmação e fail-closed; rate limiter não está conectado a rotas HTTP e TLS/secret manager ficam fora do Compose. |
| Infraestrutura de execução | **61/100** | API/worker, PostgreSQL, Redis, healthcheck, métricas e telemetria estão previstos; faltam hardening de imagem, HA, backups operacionais, proxy TLS e alertas. |
| Aprendizado e modelos de IA | **32/100** | Pipeline causal, rótulos, Ensemble, Transformer/LSTM e memória existem; faltam artefatos treinados, calibração, validação OOS, drift e retreinamento controlado. |
| Prontidão para Demo/Testnet | **70/100** | O adapter possui filtros, assinatura, status, saldo e hosts sandbox restritos; uma execução Demo não prova qualidade da estratégia. |
| Prontidão para produção com capital real | **35/100** | O adapter Binance real aceita somente `simulated`, `testnet` e `demo`; não há adapter mainnet aprovado nem controles operacionais completos. |

### Síntese de estado

Para **pesquisa e homologação**, o código está aproximadamente em **78/100**. Para **um agente autônomo de produção**, o estado é aproximadamente **35/100**. A diferença é intencional: os bloqueios atuais impedem que uma arquitetura ainda sem evidência estatística seja confundida com um sistema pronto para risco financeiro.

## 2. Estrutura lógica e infraestrutura

A entrada pode ocorrer pelo operador, pela API HTTP ou pelo worker dedicado. `TradingManager` compõe o ciclo de vida, o `MarketConnector`, o processador de notícias, o RiskAI, o executor, o `OrderManager`, o motor principal, o Sniper, o backtest e a camada de comandos [1] [2]. A API inicializa banco, telemetria e conexão, mas não liga os motores automaticamente quando `AUTO_START_ENGINES=false`. O worker separado é o caminho destinado a manter o loop de trading fora do processo HTTP.

A camada de dados agrega históricos em múltiplos timeframes, cotação, livro, notícias e tendências em paralelo. O `MultiTimeframeFeed` conserva erros por provedor e permite que o chamador mantenha o gate fechado quando dados obrigatórios ou contexto suficiente não estão disponíveis [3]. Os adapters atuais cobrem simulação local, Binance Demo/Testnet, Yahoo B3 read-only, Forex paper/read-only e CCXT opcional com restrições.

A persistência usa SQLAlchemy com SQLite para desenvolvimento e PostgreSQL no Compose. Redis é usado para estado/cache, com fallback em memória. Isso é adequado para desenvolvimento e homologação, mas o fallback em memória não pode ser aceito como fonte de verdade em produção, pois perde estado em reinício e não coordena múltiplas réplicas.

| Camada | Componentes | Função | Estado |
|---|---|---|---|
| Entrada | API FastAPI, CLI, worker | Operação, análise e ciclo de vida | Implementada |
| Configuração | Pydantic Settings, Runtime Registry | Variáveis e perfis controlados | Implementada, escopo de aplicação limitado |
| Dados | MarketConnector, MultiTimeframeFeed, NewsProcessor | OHLCV, livro, notícias e tendências | Implementada |
| Análise | MarketSignal, FlowAnalysis, Pullback, MultiTimeframe | Score e gates explicáveis | Implementada |
| Risco | RiskAI, RiskGuard, PreMarketGate, DailyState | Sizing, exposição e bloqueios | Implementada |
| Execução | CostAwareExecutor, OrderManager, adapters | Normalização, confirmação e envio | Homologável em sandbox; incompleta para produção |
| Aprendizado | AIObservation, LearningLayer, PatternMemory, Ensemble | Contexto before/after e modelos | Estruturalmente implementado; sem evidência OOS suficiente |
| Operação | PostgreSQL, Redis, Prometheus, OpenTelemetry | Persistência, estado e observabilidade | Prevista no Compose; exige hardening |

## 3. Estratégias e indicadores

O sinal determinístico calcula tendência por EMA rápida/lenta, momentum dos retornos recentes, RSI, diferença MACD, razão de volume, ATR normalizado, sentimento de notícias, tendência externa e desequilíbrio do livro. Os componentes são limitados e combinados em um score explicável; a confiança é derivada do módulo do score. A política retorna `hold` quando há histórico insuficiente, contraditório, volatilidade acima do limite, falta de confirmação de volume, fluxo incompleto ou ausência de dominância 2x1 [4].

O fluxo do livro exige uma razão configurável, atualmente `ORDER_FLOW_RATIO_THRESHOLD=2.0`, e classifica compradores, vendedores ou neutro. O pullback tenta representar tendência macro, toque na média, exaustão e gatilho de continuação, com ATR para stop/target. A confirmação multi-timeframe pode exigir que mais de um período concorde com o timeframe primário. A camada de notícias pode bloquear entradas quando não há provedor saudável, artigos suficientes ou dados frescos.

| Estratégia/ferramenta | O que faz | Limitação atual |
|---|---|---|
| EMA/MACD/RSI/ATR/volume | Mede direção, momentum, extensão, volatilidade e confirmação | Pesos fixos e não calibrados por ativo/regime |
| Fluxo 2x1 | Requer dominância nocional compradora ou vendedora | Livro histórico completo não está disponível no replay; o replay usa proxy de taker volume por candle |
| Pullback LTA/LTB | Procura correção, exaustão e retomada | Não equivale a uma prova de causalidade ou vantagem estatística |
| Multi-timeframe | Reduz entradas isoladas em um período | Pode reduzir muito a frequência e aumentar latência |
| Notícias e tendências | Adiciona sentimento e direção externa; popularidade não vira direção automaticamente | GDELT apresentou timeout no Sandbox; fontes opcionais exigem licença/chave |
| Microestrutura/custo | Controla spread, slippage, impacto e quantidade | Precisa de testes com fills parciais e condições de mercado extremas |
| RiskAI/Kelly adaptativo | Limita risco, exposição, saldo e pode reduzir sizing | Kelly só é confiável após amostra de trades suficiente e resultados bem definidos |
| PatternMemory | Reutiliza padrões encerrados e filtrados | Sem base rotulada não confirma entradas |
| Transformer/LSTM/Ensemble | Arquitetura para previsão e consenso | Sem pesos aprovados, a inferência permanece neutra |

## 4. Por que o algoritmo produz tanto `hold`

O `hold` não é causado por um único threshold. Há uma cadeia de bloqueios independentes. O score precisa superar o limiar direcional; a confiança precisa superar `MIN_CONFIDENCE_THRESHOLD`, atualmente `0,70`; não pode haver contradição; a volatilidade deve ficar abaixo de `BACKTEST_MAX_VOLATILITY`; o fluxo precisa coincidir com a ação quando a confirmação está habilitada; pullback, notícias, eventos, multi-timeframe, microestrutura, saldo, exposição e autonomia também precisam passar.

Existe ainda uma barreira especialmente importante: quando nenhum modelo treinado está disponível, o motor mantém a previsão do modelo em `hold`. O caminho live exige que a ação do modelo coincida com a leitura determinística antes de aceitar uma entrada [5]. Portanto, reduzir apenas `MIN_CONFIDENCE_THRESHOLD` não desbloqueia o sistema se o Ensemble/Transformer/LSTM continuar sem artefatos válidos.

A simulação pública mais recente utilizou 499 candles BTCUSDT de 1h. Foram criadas 456 observações causais: 455 `hold`, 1 `buy`, nenhum `sell`; o fluxo foi 429 neutro, 12 bearish e 15 bullish. Houve zero ordens e somente uma observação direcional, que não teve resultado positivo no horizonte de oito candles. Isso é evidência de **seletividade do gate em uma amostra curta**, não prova de baixa ou alta assertividade [6].

## 5. O que o código consegue fazer hoje

### Em pesquisa, paper e shadow

O sistema consegue coletar OHLCV público da Binance, dados Yahoo global/B3 e Forex público, normalizar séries, calcular indicadores, ler o livro quando disponível, buscar notícias e tendências, produzir score explicável, simular cenários de fluxo, executar backtest walk-forward e gravar contexto before/after. A validação mais recente confirmou Binance público, Yahoo global, Yahoo B3, Forex público e 67 testes aprovados.

Ele também consegue operar o adapter local simulado, executar comandos de sincronização e análise sem ordem, persistir observações, rotular candles futuros sem look-ahead e renderizar o diagrama. Esse é o ambiente recomendado atualmente.

### Em Binance Demo/Testnet

Com credenciais próprias do sandbox, `BINANCE_MODE=testnet` ou `BINANCE_MODE=demo`, conexão HTTPS permitida e filtros carregados, o código pode consultar tempo, exchange info, candles, ticker, livro, saldo, normalizar quantidade/preço, enviar, consultar e cancelar ordens de sandbox. O adapter rejeita hosts desconhecidos e não aceita `live` [7]. O Demo/Testnet continua sendo um ambiente virtual sujeito a diferenças de preço, livro, execução, elegibilidade e funcionalidades em relação ao live [8].

### Em ambiente real de produção

A resposta atual é: **não existe prontidão para produção real**. O caminho Binance implementado limita-se a simulação, Testnet e Demo; o modo `live` é rejeitado. B3 Yahoo e Forex público são read-only. O Forex live permanece fail-closed até existir broker configurado. O CCXT opcional não deve ser tratado como adapter de produção homologado apenas porque a biblioteca está instalada.

## 6. O que o código não está fazendo

O sistema não está provando rentabilidade, não está aprendendo online de forma autônoma a partir de qualquer candle sem supervisão, não está recalibrando probabilidades automaticamente, não está treinando pesos neurais no loop de produção, não está executando mainnet Binance, não está garantindo stop/OCO/bracket após cada fill, não está reconciliando completamente ordens e posições depois de reinício, não está tratando de forma completa fills parciais e não possui uma política distribuída de `clientOrderId` idempotente.

Também não há garantia de que backtest e live tenham exatamente a mesma informação: o backtest walk-forward usa cache de indicadores e regras de fricção, enquanto o live agrega notícias, livro, saldo, eventos, microestrutura e adapters em tempo real. Essa diferença precisa ser reduzida antes de qualquer decisão de produção.

O rate limiter existe como classe, mas o audit encontrou que ele não está aplicado como dependência nas rotas HTTP. A proteção efetiva hoje depende mais do gateway externo, da configuração de infraestrutura e das limitações dos provedores do que dessa classe interna. Esse ponto reduz o score de segurança e deve ser corrigido antes de expor a API publicamente.

## 7. Segurança e impacto na infraestrutura

Os controles positivos são relevantes: `SECRET_KEY`, credenciais e senhas devem vir do ambiente; autenticação usa JWT; RBAC separa administrador e trader; usuários públicos não retornam senha; o `OrderManager` exige modo compatível, risco válido e confirmação; o modo shadow não envia ordem; a Binance real está limitada a hosts sandbox; e o worker é separado da API. Essas barreiras reduzem o risco de uma ativação acidental [9].

Os riscos residuais são igualmente importantes. O Compose publica a porta HTTP diretamente e não incorpora TLS, proxy reverso, WAF, rotação de segredo, limites de CPU/memória ou política de usuário não-root [10]. A imagem não fixa todas as dependências, e `torch`, `requests`, `psycopg2-binary` e algumas bibliotecas de observabilidade não possuem uma política completa de lock/reproducibilidade. Redis e PostgreSQL possuem volumes, mas backup, restauração testada, retenção, migração reversível e alertas ainda precisam ser operacionalizados.

O impacto de uma decisão do bot é, portanto, assimétrico. O sistema tende a **não operar** quando não há evidência, contexto, saldo ou autorização suficientes; isso reduz entradas, latência de decisão pode aumentar com múltiplos providers e o comportamento pode parecer excessivamente conservador. Quando todos os gates passam, ainda existe risco de execução, slippage, falha de rede, divergência de saldo e diferença entre sandbox e live. Nenhum score de confiança atual equivale a probabilidade calibrada de lucro.

## 8. Lacunas prioritárias para refinar o código

| Prioridade | Ausência | Impacto | Critério de conclusão |
|---|---|---|---|
| P0 | Adapter mainnet separado e homologação de produção | Impede tratar o sistema como live-ready | Implementação explicitamente separada, permissões mínimas, revisão e kill switch validado |
| P0 | Reconciliação de ordens/posições e idempotência | Pode duplicar, perder ou desalinhar posições após falha | Reconciliação periódica, `clientOrderId`, fills parciais, retry seguro e recovery testado |
| P0 | OCO/bracket/stop real após fill | Uma ordem de entrada sem proteção deixa risco aberto | Proteção aceita pela exchange e confirmada por status independente |
| P0 | Dataset real rotulado multiativo e multi-regime | Sem ele, a IA não tem evidência de generalização | Split cronológico, gap de purga, OOS, F1/balanced accuracy, calibração e relatório por regime |
| P1 | Aplicar rate limiter nas rotas | Reduz superfície de abuso HTTP | Dependência por IP/usuário, resposta 429, testes concorrentes e armazenamento distribuído quando necessário |
| P1 | Paridade backtest/live | Evita validar uma lógica diferente da que opera | Mesmo feature builder, fluxo, notícias, custos, filtros e regras de saída |
| P1 | Observabilidade operacional | Falhas podem ficar silenciosas | Alertas para desconexão, latência, erro, saldo divergente, perda diária e ordem sem reconciliação |
| P1 | Hardening de imagem e runtime | Reduz risco de supply chain e privilégio | Imagem não-root, lockfile, SBOM, scan, TLS, secrets manager e limites de recurso |
| P2 | Calibração adaptativa por regime | Aumenta seletividade sem simplesmente baixar threshold | Curva precision/coverage, custo de falso positivo/negativo e validação walk-forward |
| P2 | Histórico de order book | Melhora avaliação da regra 2x1 | Captura versionada, timestamp, profundidade e replay com custo de impacto |
| P2 | Retreinamento controlado | Evita drift ou autoaprendizado contaminado | Dataset imutável, aprovação humana, modelo versionado, rollback e monitor de drift |

## 9. Sequência recomendada

A sequência de menor risco é **pesquisa → shadow → Demo/Testnet → paper com reconciliação → exposição mínima controlada**, sem saltar diretamente para capital real. Primeiro deve ser produzido um dataset real suficiente e treinado o Ensemble com validação temporal. Depois, o backtest deve executar o mesmo caminho de features e gates usado pelo worker. Em seguida, o Demo/Testnet deve ser submetido a testes de desconexão, fills parciais, rejeições, filtros, clock drift, rate limit, reinício e divergência de saldo.

Somente depois de uma janela de shadow suficientemente longa, com métricas por ativo e regime, deve-se considerar ativação progressiva. A redução do threshold deve ser resultado de uma matriz de **coverage versus precision versus expectancy líquida**, e não de uma meta arbitrária de gerar mais sinais. A configuração mais permissiva deve continuar preservando o bloqueio quando a tendência é neutra, o fluxo é incompleto ou a infraestrutura não pode confirmar o estado da conta.

## 10. Diagrama lógico resumido

O diagrama complementar `docs/live_trading_architecture.mmd` representa a separação entre entrada, dados, análise, risco, execução, aprendizado e infraestrutura. A seta pontilhada de aprendizado não autoriza ordens: ela apenas leva resultados rotulados para um processo de treinamento aprovado.

## Referências

[1]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/core/manager.py "TradingManager e composição do core"

[2]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/core/engine.py "Motor principal e gates de decisão"

[3]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/core/data_feeds.py "Feed paralelo e MarketSnapshot"

[4]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/core/market_signals.py "Indicadores, score, confiança e rejeição"

[5]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/core/engine.py "Confluência entre modelo e sinal determinístico"

[6]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/MARKET_SIMULATION_REPORT.md "Resultados do replay público e notícias"

[7]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/execution/binance_adapter.py "Adapter Binance Demo/Testnet"

[8]: https://www.binance.com/en/support/faq/detail/9be58f73e5e14338809e3b705b9687dd "Binance Demo Trading — diferenças e limitações"

[9]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/execution/order_manager.py "Confirmação, modo e gates do OrderManager"

[10]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/docker-compose.yml "Infraestrutura declarada no Compose"

**Basis:** os scores são avaliações de engenharia baseadas no código, nos testes e nos relatórios versionados; não são métricas de retorno. **Time:** a avaliação usa o estado do branch em 26 de agosto de 2026 e o dataset público BTCUSDT de 4 a 25 de agosto de 2026. **Assumptions:** defaults seguros permanecem ativos, `AUTONOMOUS_TRADING_ENABLED=false`, `SHADOW_MODE_ENABLED=true` e modelos sem artefatos são tratados como neutros. **Sources & Confidence:** evidência alta para estrutura e testes locais; confiança baixa para assertividade, pois a amostra direcional foi de uma operação. **Compliance:** This is research and analysis only, not personalized financial advice.
