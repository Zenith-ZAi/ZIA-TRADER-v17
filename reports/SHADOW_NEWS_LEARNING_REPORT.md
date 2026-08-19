# Relatório de notícias, aprendizado e shadow mode

**Projeto:** ZIA-TRADER-v17  
**Data da execução:** 19 de agosto de 2026 UTC  
**Modo:** shadow/research, sem ordens  
**Autor:** Manus AI

> Este relatório é uma avaliação técnica de software e não constitui recomendação de investimento nem garantia de desempenho financeiro.

## 1. Escopo e método

Foram implementados adaptadores por variável de ambiente para Marketaux, Finnhub Crypto News e Twelve Data News, preservando os provedores gratuitos e pagos já existentes. O processador usa timeout, cache, fallback, normalização e persistência idempotente. A seleção de artigos passou a usar round-robin por provedor para não deixar RSS ocupar todo o limite global.

O Ensemble foi treinado localmente com o dataset OHLCV público BTCUSDT/1h de 2020–2024, contendo 43.816 candles fechados. A calibração utilizou separação cronológica: 70% para treino, 15% para calibração e 15% para teste. O modelo nunca recebeu dados futuros para construir features. Notícias atuais não foram retroativamente associadas ao OHLCV histórico; portanto, notícias permanecem contexto determinístico no live/shadow e não foram declaradas como feature histórica do Ensemble.

## 2. Integrações de notícias observadas

A execução real de ingestão para BTC/USDT, ETH/USDT e SOL/USDT persistiu 20 artigos no último ciclo e duas tendências atualizadas. O banco SQLite auditado contém 36 artigos e dois snapshots de tendência, incluindo dados acumulados da execução anterior.

| Provedor | Status observado | Persistência observada |
|---|---|---:|
| RSS/Google News | OK | 22 artigos |
| Marketaux | OK | 3 artigos |
| Finnhub | OK | 6 artigos |
| NewsAPI | OK | 5 artigos |
| Alpha Vantage | HTTP OK; resposta não priorizada no lote final | sem artigo identificável no recorte |
| CoinGecko | OK | 2 snapshots |
| GDELT | timeout de 8 s no sandbox | fallback |
| Twelve Data | HTTP 404 no caminho `/news` | fallback seguro |

As chaves foram consumidas somente em memória, normalizadas para remover CR/LF e não foram versionadas. O arquivo de ambiente enviado pelo usuário deve ser tratado como material sensível; recomenda-se a rotação das chaves se elas tiverem sido expostas fora do canal seguro.

## 3. Treinamento e qualidade do modelo

O treinamento cronológico do Ensemble RF + XGBoost gerou artefatos locais em `models/`, fora do Git. Na validação do período posterior ao treino, as métricas de classificação foram:

| Métrica | Valor |
|---|---:|
| Accuracy | 43,12% |
| Balanced accuracy | 37,22% |
| Precision macro | 41,45% |
| Recall macro | 37,22% |
| F1 macro | 35,17% |
| Amostras de validação | 6.127 |

Esses números são fracos para autorizar autonomia real. O modelo está treinável e auditável, mas não demonstrou vantagem estatística suficiente sobre o ruído do mercado.

## 4. Calibração shadow e Sharpe

A grade testou pullback ligado/desligado, limiares de confiança `0,60/0,65/0,70`, volatilidade máxima `0,08/0,12` e quatro níveis de tolerância/exaustão/volume do pullback. A seleção foi feita apenas na janela de calibração, exigindo pelo menos 10 trades e drawdown superior a `-15%`; o teste final ficou separado.

| Métrica | Calibração | Teste posterior |
|---|---:|---:|
| Configuração selecionada | sem pullback, confiança 0,60, vol. 0,08 | mesma |
| Trades | 19 | 19 |
| PnL | 161,1197 | 232,2920 |
| Retorno | 1,6112% | 2,3229% |
| Sharpe | 0,2249 | **0,2952** |
| Drawdown máximo | -0,8517% | -0,7408% |
| Win rate | 42,11% | 47,37% |
| Profit factor | 1,6918 | 2,0921 |
| Rejeições do Ensemble | 2.834 | 3.321 |

O alvo de Sharpe acima de 1,0 **não foi atingido**. A causa observável não é resolvida por reduzir limiares indiscriminadamente: as variantes com pullback ligado produziram zero trades neste recorte, enquanto a melhor variante estatística desligou o pullback. Isso indica que o pullback está excessivamente restritivo ou desalinhado com o timeframe de 1 hora; ativá-lo em produção agora seria uma mudança não suportada pela evidência.

## 5. Alimentação do banco e shadow replay

Foi criada a tabela `ai_observations`, contendo ação final, ação candidata, confiança do modelo, confiança do sinal determinístico, preço, sentimento, tendência, bloqueio econômico, validade de risco, features causais e metadados de auditoria. Um replay com 600 candles reais produziu seis observações shadow e confirmou `orders_sent=0`. O adapter de replay lança erro explícito se qualquer caminho tentar chamar `place_order`.

O registro permite rotular posteriormente o retorno futuro e a classe de resultado quando houver uma janela temporal posterior. Não foi fabricado rótulo para observações sem futuro disponível.

## 6. Alterações de código

Foram adicionados os adaptadores em `data/news_processor.py`, aliases e validação de ambiente em `config/settings.py`, idempotência de tendências em `database_manager.py`, a entidade `AIObservation` em `database.py`, o registro shadow em `core/engine.py`, o warm-up e filtro Ensemble opcional em `core/backtest_engine.py`, a tolerância configurável do pullback nos três motores, e os scripts operacionais em `scripts/`.

A autonomia permanece bloqueada por padrão: `AUTONOMOUS_TRADING_ENABLED=false`, `NEURAL_MODELS_ENABLED=false`, `SNIPER_ENABLED=false` e `SHADOW_MODE_ENABLED=true`. O shadow mode registra e avalia; ele não envia ordens.

## 7. Verificação e decisão

A suíte completa terminou com **33 testes aprovados e dois warnings não bloqueantes**. Compilação, `git diff --check` e varredura de padrões de credenciais foram executadas. O código pode seguir em shadow/research mode, mas não deve ser promovido a capital real enquanto o teste posterior não demonstrar desempenho robusto, com amostra maior, custos, slippage e regime adverso.

A próxima melhoria de alto valor é construir um dataset histórico de notícias com timestamp anterior à barra, sentimento por ativo e deduplicação temporal. Sem esse alinhamento, adicionar notícias atuais ao treino histórico criaria vazamento ou distribuição incompatível. Em paralelo, o pullback precisa ser recalibrado por timeframe e validado em múltiplas janelas walk-forward, não apenas em uma amostra.

## Referências

[1]: https://www.marketaux.com/documentation — Marketaux API Documentation.  
[2]: https://finnhub.io/docs/api — Finnhub API Documentation.  
[3]: https://twelvedata.com/docs — Twelve Data API Documentation.  
[4]: https://api.twelvedata.com/doc/swagger/openapi.json — Twelve Data OpenAPI specification.  
[5]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17 — ZIA-TRADER-v17 repository.
