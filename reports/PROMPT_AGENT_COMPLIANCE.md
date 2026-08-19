# Auditoria do Prompt de Comando e do Agente de Trading

**Repositório:** ZIA-TRADER-v17  
**Data:** 19 de agosto de 2026  
**Modo de execução:** shadow/backtest; nenhuma ordem foi enviada nesta etapa.

## 1. Conclusão executiva

O backend já possui um **modelo de negociação real**, formado por `EnsembleModel` com Random Forest e XGBoost, features OHLCV causais, sinais determinísticos e gates de risco. Transformer e LSTM também existem, mas permanecem desativados até que pesos aprovados estejam disponíveis. O agente autônomo está implementado no motor principal e no Sniper, porém sua execução continua desativada por padrão.

O prompt anexado descreve uma arquitetura mais ampla do que a anteriormente implementada. As lacunas principais eram a **memória histórica reutilizável de padrões**, um **ciclo explícito de saída/reversão no motor live**, o bloqueio de entrada duplicada e a distinção entre Spot e short. Essas lacunas foram corrigidas de forma condicional, com defaults seguros.

## 2. Mapeamento do prompt

| Requisito do prompt | Estado no backend | Correção/decisão |
|---|---|---|
| Feed de preço e candles | Implementado pela fachada da exchange e replay público | Mantido; a frequência depende de `TIMEFRAME` e do adapter |
| Três fontes de notícias | Implementado com RSS, Marketaux, Finnhub, NewsAPI e demais fallbacks | Mantido; falhas degradam para vazio e são registradas |
| Índice de sentimento | Implementado por agregação normalizada de artigos | Mantido como contexto, sem permitir que notícia isolada autorize trade |
| LTA/LTB e Pullback macro/meso/micro | Implementado em `core/pullback_strategy.py` | Mantido com EMA, pivôs, exaustão, volume, trigger e ATR |
| Comparação com padrões históricos | Ausente como memória reutilizável | Adicionados `MarketPattern`, `PatternMemory` e consulta causal por distância |
| Critério histórico de +2 ATR | Ausente | Adicionado como threshold configurável, com amostra mínima configurável |
| Saída por alvo/stop/breakeven | Existia no backtest, mas não havia política live explícita | Adicionada `evaluate_position_exit` e integração no motor principal |
| Reversão | Existia como sinal de contexto | Agora também pode fechar uma posição quando confirmada; não abre posição sozinha |
| Venda short automática | Incompatível com Binance Spot por padrão | `ALLOW_SHORT=false`; venda descoberta é bloqueada |
| Memória aprende automaticamente | Não deve ser presumida | Adicionado comando para rotular retorno futuro e materializar apenas padrões encerrados |
| Execução autônoma | Implementada, mas protegida | `AUTONOMOUS_TRADING_ENABLED=false` permanece default |

O trecho de exemplo do prompt contém nomes não definidos, como `media_volume`, `preco_ultimo_pivo_baixo`, `linha_tendencia_baixa` e `executar_ordem`. Eles não foram copiados literalmente; foram traduzidos para contratos existentes e testáveis.

## 3. Alterações implementadas

A tabela `market_patterns` armazena símbolo, estratégia, assinatura numérica causal, tipo de padrão, entrada, ATR, resultado em ATR, rótulo e origem da observação. A assinatura usa RSI, ATR percentual, momentum de cinco barras, razão de volume, sentimento, tendência, confiança do Pullback, exaustão, trigger e direção.

`PatternMemory` executa busca determinística por distância normalizada. Um padrão somente pode confirmar uma entrada quando possui resultado histórico igual ou superior ao limite configurado e quantidade mínima de amostras. Como não existe um banco vetorial externo no projeto, foi adotada a memória relacional auditável; isso evita adicionar uma dependência sem evidência de necessidade. Um backend vetorial pode ser acrescentado posteriormente, mantendo a mesma interface.

O comando `scripts/label_shadow_observations.py` usa candles futuros reais para preencher `forward_return` e `outcome_label`. Apenas observações com janela futura disponível são rotuladas. Padrões que atingem o retorno mínimo em ATR são então persistidos. O comando não gera dados, não chama endpoints de ordem e não trata a inserção como aprendizado instantâneo.

A política `evaluate_position_exit` prioriza stop quando stop e alvo aparecem na mesma barra OHLCV, pois a sequência intrabar não é observável. Depois considera alvo, reversão confirmada e sinal contrário com confiança mínima. No motor principal, uma posição existente é fechada antes de qualquer entrada, e uma entrada nova é bloqueada enquanto houver posição viva.

Também foi criado `RiskAI.validate_exit`, que valida o fechamento com a quantidade já mantida, em vez de recalcular sizing de uma nova entrada. O motor não permite short descoberto em Spot quando `ALLOW_SHORT=false`.

## 4. Backtest reproduzido

Foi executado o backtest no dataset OHLCV público BTCUSDT/1h de 2020–2024, com 43.816 candles, fricção habilitada, Pullback ativo, warm-up de 250 barras, sem Ensemble no caso comparativo e sem ordens.

| Caso | Trades | PnL | Retorno | Sharpe | Drawdown | Win rate |
|---|---:|---:|---:|---:|---:|---:|
| Memória desativada | 8 | 79,1390025685 | 0,7913900257% | 0,0762628585 | -0,3572455048% | 87,5% |
| Memória ativada, sem padrões armazenados | 8 | 79,1390025685 | 0,7913900257% | 0,0762628585 | -0,3572455048% | 87,5% |

O resultado igual é esperado: a memória foi habilitada, mas não havia padrões históricos elegíveis no banco. Isso confirma que o recurso não inventa confirmação para liberar sinais. Também confirma que **o Sharpe não foi elevado artificialmente**; o recorte continua muito pequeno para sustentar operação real.

## 5. O que ainda não é afirmado

O sistema não possui, nesta etapa, prova de que o índice de Sharpe seja superior a 1,0, nem prova de precisão estatística suficiente para capital real. O banco de padrões só deve ser ativado após acumular observações rotuladas em múltiplos regimes, com separação temporal entre treino, calibração e teste. A GPU não é ativada automaticamente pelo código e não transforma a latência de rede da exchange em 1–3 ms.

O modo Spot também não implementa short nativo. Para operar short seria necessário um adapter explícito de margem ou futuros, com regras, saldos, liquidação e risco diferentes; não foi habilitado implicitamente.

## 6. Validação

A suíte passou com **40 testes aprovados** e dois warnings não bloqueantes provenientes de dependências externas. A compilação Python e `git diff --check` também foram executados. Nenhum segredo ou ordem foi utilizado na validação.

A configuração segura permanece:

```text
AUTONOMOUS_TRADING_ENABLED=false
SHADOW_MODE_ENABLED=true
NEURAL_MODELS_ENABLED=false
SNIPER_ENABLED=false
PATTERN_MEMORY_ENABLED=false
ALLOW_SHORT=false
BINANCE_MODE=simulated
```

## 7. Operação recomendada

A sequência recomendada é: coletar OHLCV e observações shadow; rotular somente depois do horizonte futuro; revisar a distribuição de resultados; materializar padrões com resultado positivo em ATR; executar backtest walk-forward com a memória ativada; avaliar estabilidade por regime; e somente depois considerar promoção para uma Sandbox com ordens, ainda supervisionada.

Ativar `PATTERN_MEMORY_ENABLED=true` antes de haver padrões elegíveis não melhora a assertividade: ele apenas rejeita entradas que não possuem memória histórica aprovada. Ativar `ALLOW_SHORT=true` em Binance Spot não corrige essa limitação e não deve ser feito.
