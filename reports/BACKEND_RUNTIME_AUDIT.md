# Auditoria do Backend e Prontidão Operacional

**Projeto:** ZIA-TRADER-v17  
**Data da auditoria:** 19 de agosto de 2026  
**Escopo:** menu administrativo, bots e estratégias, mercados, múltiplos timeframes, notícias/tendências, ciclo de saída e riscos de operação live.

## Conclusão

O projeto contém um **backend FastAPI funcional**, um **console administrativo Rich** e dois caminhos de execução: o motor principal de trading e o Sniper. Entretanto, não há um dashboard web com menu de bots e estratégias. A interface de menu existente é somente o programa local `admin_console.py`; a API expõe autenticação, healthcheck, métricas e três comandos de controle (`/trading/start`, `/sniper/start`, `/trading/stop`). O endpoint `/admin/dashboard` retorna apenas uma mensagem JSON, não uma tela.

O menu lista mais opções do que o runtime realmente executa. `StrategyConfig`, `AlgorithmConfig` e `ExchangeConfig` são tabelas usadas pelo console e não são consultadas pelo `TradingManager`, `RoboTraderUnified`, `SniperEngine` ou `ExecutionEngine`. Portanto, ativar `Scalping`, `Swing`, `IA Adaptativa`, `Bybit`, `OKX`, Forex ou outro preset no menu **não altera automaticamente a estratégia ou a corretora do motor live**.

## Capacidades reais

| Área | Implementado hoje | Limitação operacional |
|---|---|---|
| API | FastAPI, OAuth2/JWT, `/healthz`, `/metrics`, start/stop | Sem dashboard web e sem endpoint de estado detalhado dos motores |
| Menu | Console Rich local com Exchange APIs, Estratégias, IA, Algoritmos, Configurações e Testes | Não é uma interface web; alterações do menu não são aplicadas ao runtime já iniciado |
| Bots | Motor principal e Sniper | Sniper é um segundo loop, não um catálogo de bots configuráveis pelo menu |
| Corretoras | Simulação local ou Binance Spot Demo/Testnet | Não há adapter live para Forex, MT5, OANDA, Bybit, OKX ou outras corretoras |
| Cripto | Binance Spot com símbolos configuráveis, como BTC/USDT, ETH/USDT e SOL/USDT | O adapter é Spot; short não é permitido por default |
| Timeframe principal | Um `TIMEFRAME`, default `1h` | Não analisa 1m, 5m, 10m e 1h simultaneamente no mesmo ciclo |
| Timeframe Sniper | Um `SNIPER_TIMEFRAME`, default `1m` | É independente do timeframe principal e não cria uma matriz multi-timeframe |
| Binance intervals | `1m`, `3m`, `5m`, `15m`, `30m`, `1h` e superiores | `10m` não está na lista aceita pelo adapter; será rejeitado |
| Notícias | Provedores paralelos, cache de 300 segundos, agregação de sentimento | Falha de provedor degrada para sentimento neutro e não impede entrada por si só |
| Tendências | CoinGecko e Benzinga opcional, persistência de snapshots | Não existe um classificador de choque de tendência com saída de emergência |
| Eventos econômicos | Bloqueio por janela em `data/economic_events.json` | Bloqueia novas entradas; não fecha posição viva automaticamente |
| Saídas | Stop, alvo, breakeven, reversão e sinal contrário confirmado | Notícia adversa e incerteza não são, por padrão, motivos de saída forçada |

## Gargalos identificados

### 1. Gargalo de latência local

O benchmark foi executado com 50 repetições sobre 600 candles reais do dataset BTCUSDT/1h. A decisão local com Pullback recalculado apresentou p50 de **54,652108 ms** e p95 de **59,547563 ms**. Com o Pullback em cache, a decisão combinada caiu para p50 de **17,312632 ms** e p95 de **19,417055 ms**. O gargalo dominante é recalcular `PullbackSignalCache` e sinais derivados a cada chamada, não o detector de baleias.

| Componente | p50 | p95 |
|---|---:|---:|
| Construção de features causais | 6,690762 ms | 7,422969 ms |
| Ensemble | 5,814108 ms | 6,574110 ms |
| Construção do cache Pullback | 75,352216 ms | 82,648223 ms |
| Sinal com Pullback recalculado | 54,652108 ms | 59,547563 ms |
| Sinal com Pullback em cache | 4,602008 ms | 5,228999 ms |
| Decisão local sem cache | 68,109654 ms | 75,486160 ms |
| Decisão local com cache | 17,312632 ms | 19,417055 ms |

Esses números são somente do processo local. Eles **não representam** latência de REST/WebSocket, TLS, roteamento, fila, matching engine, confirmação de saldo ou execução da corretora. A afirmação de 1–3 ms em produção não pode ser deduzida desse benchmark.

### 2. Notícias são fail-open para entradas

Os provedores são chamados em paralelo e cada requisição usa o timeout configurado. Quando todos ou alguns provedores falham, o motor zera `processed_news`, `avg_sentiment` e `trend_score` e continua analisando. Isso evita travar o loop, mas significa que a decisão pode continuar sem informação externa. O sentimento lexical atual também não é equivalente a um modelo BERT validado.

### 3. O bloqueio de eventos não é um stop de posição

`EconomicEventGuard` retorna bloqueio quando o timestamp está dentro da janela configurada. No motor principal esse resultado participa do gate de confluência e impede a entrada. A política de posição recebe stop, alvo, reversão e sinal contrário; ela não recebe `event_status`, choque de sentimento ou tendência incerta para forçar encerramento. Portanto, atualmente o comportamento é **não entrar**, e não “sair para não ficar no prejuízo”.

### 4. O Sniper não usa notícias e não tem saída própria completa

O Sniper usa variação de preço, whale detector, Pullback, confiança, Spot guard e EconomicEventGuard para confirmar uma entrada. Ele grava `news_sentiment=0.0` e `trend_score=0.0` nas observações shadow. Também não possui um fluxo próprio de saída de posição; a proteção principal de saída fica no motor principal.

### 5. Estado de posição e reconciliação

Durante esta auditoria foi identificado e corrigido um gargalo funcional: após uma entrada preenchida, o executor gravava no cache apenas preço de ordem, ação, quantidade e identificador. Não gravava stops, alvo e breakeven calculados pelo RiskAI, nem criava a entidade `Position` no banco. Isso poderia impedir que o ciclo live encontrasse níveis de saída completos.

A correção publicada passou a gravar o **preço efetivamente preenchido**, níveis de stop/alvo/breakeven e a posição auditável no banco; na saída, o cache é removido e a posição é fechada. Essa correção não substitui a reconciliação inicial com a corretora: se o Redis não estiver disponível, o fallback atual é memória do processo, que se perde em reinício.

## Resposta direta sobre o cenário 1m, 5m, 10m e 1h

**Não está implementado como análise simultânea multi-timeframe.** O motor principal lê apenas `TIMEFRAME`; o Sniper lê apenas `SNIPER_TIMEFRAME`. O menu permite digitar uma string como `1m,5m,1h`, mas o motor não a interpreta como quatro séries paralelas. Além disso, 10m não é um intervalo aceito no adapter Binance atual. Para suportar esse cenário corretamente seria necessário implementar uma matriz por símbolo/timeframe, sincronização de candle fechado, agregação de confirmação entre timeframes e regras de risco específicas por timeframe.

## Resposta direta sobre parada por notícias e tendências

**Parcialmente implementado.** O código pode rejeitar novas entradas quando há volatilidade acima do limite, indicadores contraditórios, confiança insuficiente, Pullback não confirmado, padrão histórico não aprovado ou janela econômica cadastrada. Porém, não há ainda um módulo de “emergency exit” baseado em notícia adversa, sentimento anormal, tendência informal ou falha dos provedores. Para essa política ser segura, ela deve distinguir claramente:

| Situação | Política atual | Política necessária para live |
|---|---|---|
| Evento econômico previamente cadastrado | Bloqueia entrada | Opcionalmente fechar ou reduzir posição conforme configuração explícita |
| Sentimento negativo em notícia | Reduz score do sinal | Classificador de choque com timestamp, ativo, deduplicação e limiar validado |
| Tendência contraditória | Pode gerar HOLD | Circuit breaker e congelamento temporário de entradas |
| Provedores indisponíveis | Continua com contexto neutro | Modo fail-closed para entrada autônoma, com alerta operacional |
| Volatilidade acima do limite | Rejeita entrada | Stop/trailing e emergency exit independentes do sinal de entrada |

## Riscos que ainda impedem operação live irrestrita

A operação não deve ser promovida diretamente para capital real enquanto persistirem os seguintes pontos: ausência de dashboard e controle de estado; menu não conectado ao runtime; ausência de análise multi-timeframe; falta de adapter Forex; falha de notícias tratada como neutra; ausência de emergency exit por choque de notícia; ausência de reconciliação de posições após reinício; fallback Redis em memória; falta de circuit breaker distribuído e lock de instância; e ausência de teste prolongado em Sandbox com falhas de rede, ordens parcialmente preenchidas, timeout, reconexão e restart.

O default seguro continua correto: `BINANCE_MODE=simulated`, `AUTONOMOUS_TRADING_ENABLED=false`, `SHADOW_MODE_ENABLED=true`, `SNIPER_ENABLED=false`, `ALLOW_SHORT=false`.

## Validação executada

Após a correção de persistência, foram aprovados **42 testes**, a compilação Python e `git diff --check`. A auditoria de superfície encontrou 14 rotas FastAPI, incluindo documentação automática, healthcheck, métricas, autenticação e start/stop. Não foi enviada ordem durante esta auditoria.

## Sequência recomendada antes de ativar Sandbox supervisionada

Primeiro, separar o painel web da execução e implementar um endpoint de estado que mostre processo, símbolo, timeframe, posição, último sinal, última falha e idade dos dados. Em seguida, tornar o menu de estratégias uma configuração versionada e consumida pelo runtime, com validação e reinício controlado. Depois, implementar reconciliação da posição na inicialização, Redis obrigatório fora do desenvolvimento e lock de instância. Só então deve ser criado o gate de notícia/tendência com política fail-closed para entradas e emergency exit opcional, validado em walk-forward com timestamps reais de publicação.

O suporte a 1m/5m/10m/1h deve ser implementado como etapa independente e testado sem misturar candles futuros ou barras ainda abertas. Forex deve receber um adapter e um modelo de execução próprios; não deve ser habilitado apenas pela etiqueta no menu.

> **Conclusão:** a estrutura atual é adequada para continuar em shadow mode e Sandbox controlada, mas ainda não é um painel operacional multi-mercado nem um agente autônomo pronto para capital live irrestrito.

## Referências

[1]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17 "Repositório ZIA-TRADER-v17"
[2]: https://github.com/binance/binance-spot-api-docs/blob/master/README.md "Documentação pública da Binance Spot API"

Este documento é uma auditoria técnica do software, não uma recomendação personalizada de investimento.
