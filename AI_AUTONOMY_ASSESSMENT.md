# Avaliação da IA e do modo autônomo — ZIA-TRADER-v17

**Data da avaliação:** 18 de agosto de 2026  
**Base:** código do branch `master`, homologação Binance Demo registrada no repositório e testes automatizados locais.  
**Escopo:** assertividade de sinais, aprendizado supervisionado, execução autônoma, risco e prontidão para ambiente real.

> **Conclusão executiva:** o Sandbox comprovou conectividade, leitura privada, normalização de filtros e o ciclo de execução Demo. Ele ainda não comprovou assertividade da IA em ambiente real. A principal limitação não é um limiar de configuração: é a ausência de um dataset OHLCV rotulado, artefatos treinados, validação fora da amostra e reconciliação operacional completa.

## 1. Métricas mais recentes disponíveis

A homologação registrada utilizou **500 candles de BTC/USDT em 1 minuto**. O backtest walk-forward reportado foi tecnicamente consistente, porém a amostra teve apenas duas operações; portanto, não é estatisticamente suficiente para estimar rentabilidade futura.

| Métrica | Resultado registrado | Interpretação |
|---|---:|---|
| PnL do recorte | `+2,8625` | Positivo no recorte, sem significância estatística |
| Retorno | `+0,02862%` | Muito pequeno para concluir vantagem |
| Sharpe | `0,3008` | Baixo e instável com duas operações |
| Drawdown máximo | `-0,06037%` | Baixo no recorte, não representa regime de estresse |
| Operações | `2` | Amostra insuficiente |
| Vitórias / perdas | `1 / 1` | Win rate de `50%` |
| Profit factor | `5,9601` | Inflado pela amostra pequena |
| Sinais bons | `7` | `1,505%` das 465 barras avaliadas |
| Sinais rejeitados | `458` | Gate conservadora, não necessariamente baixa assertividade |
| Dados inválidos | `0` | Pipeline de dados válido no recorte |
| Tempo de análise/backtest | `196,87 ms` | Boa latência local para o recorte |
| Ensemble treinado | **Não** | Fallback neutro `HOLD/0,5`; não é previsão aprendida |

A matriz de limiares também foi conclusiva para não reduzir o limiar operacional de `0,70` para `0,65` sem evidência adicional: com o recorte Demo avaliado, `0,70` produziu PnL `+2,7242`, 2 operações, win rate `50%` e profit factor `4,8081`; `0,65` produziu PnL `-4,2317`, 5 operações, win rate `20%` e profit factor `0,5008`. A alteração de `BACKTEST_MAX_VOLATILITY` de `0,08` para `0,12` não mudou o resultado naquele recorte.

A ordem Demo posteriormente autorizada validou apenas a execução técnica: `BUY MARKET` de `0,00015 BTC`, `order_id 57614421337`, status `FILLED`, preço médio `64.788,64 USDT/BTC` e valor executado `9,718296 USDT`. Isso não constitui validação da estratégia, pois o sinal da IA estava em `HOLD` com confiança `0,5757`.

## 2. O que foi refinado no código

| Área | Situação após esta alteração | Estado |
|---|---|---|
| Features de modelo | Criado `ai/feature_pipeline.py` com dez features normalizadas e cálculo causal | Implementado |
| Rótulos | Criado rótulo futuro `sell=0`, `hold=1`, `buy=2`, com horizonte configurável | Implementado |
| Treino Ensemble | Criado `ai/train_ensemble.py` para CSV/Parquet OHLCV real, divisão cronológica e gap de purga | Implementado |
| Artefatos | Ensemble valida schema, classes, metadados e rejeita modelos incompatíveis | Implementado |
| Inferência | Motor usa o mesmo schema de features do treinamento | Implementado |
| Redes neurais | Transformer/LSTM só entram no consenso quando pesos existem e carregam sem erro | Implementado |
| Autonomia | `AUTONOMOUS_TRADING_ENABLED=false` por padrão | Implementado |
| Sniper | Removeu confiança fixa `0,95`; exige volatilidade, baleia alinhada, sinal determinístico e autonomia habilitada | Implementado |
| Saldo | RiskAI consulta saldo privado da exchange no contexto e bloqueia ativo insuficiente | Implementado |
| Concorrência | Sniper desativado por padrão no worker; evita dois motores abrindo posições simultaneamente | Implementado |
| Menu de IA | Treinamento/exportação deixaram de simular sucesso e passaram a refletir artefatos reais | Implementado |
| Testes | `26 passed`; compilação e `git diff --check` aprovados | Validado |

Essas alterações elevam a **qualidade estrutural do software**, não a assertividade estatística automaticamente. Nenhum artefato treinado foi gerado porque não há dataset OHLCV real no diretório `data/`; o sistema não inventa dados para preencher essa lacuna.

## 3. Percentuais de prontidão

Os percentuais abaixo são um **scorecard de engenharia**, não uma probabilidade de lucro nem uma taxa de acerto. Eles distinguem a infraestrutura já construída da prontidão para operar dinheiro real.

| Dimensão | Estimativa | Por que não é 100% |
|---|---:|---|
| Conectividade e adapter Binance Demo | `90%` | O ciclo privado e uma ordem Demo foram confirmados; produção ainda não foi homologada |
| Dados, notícias, tendências e livro | `75%` | Há pipeline híbrido e fallback, mas faltam qualidade histórica versionada e testes por regime |
| Sinais determinísticos | `70%` | EMA/MACD/RSI/ATR/volume/reversão existem; falta calibração estatística e validação multiativo |
| RiskAI e sizing | `75%` | Há limites, saldo privado e exposição; faltam reconciliação e proteção pós-execução completas |
| Aprendizado supervisionado | `25%` | Pipeline foi implementado, mas ainda não há dataset, treino aprovado ou artefato em produção |
| Transformer/LSTM | `20%` | Arquitetura existe, mas pesos treinados e validação fora da amostra não existem |
| Backtest de estratégia IA | `45%` | Walk-forward determinístico existe; ainda não inclui o Ensemble treinado, slippage e impacto de mercado |
| Autonomia operacional | `40%` | Há kill switch e gates; faltam idempotência, reconciliação, OCO/bracket e monitoramento de produção |
| **Prontidão para produção real** | **`35%`** | Sandbox não é produção; não ativar trading real neste estágio |

A estrutura técnica pode ser considerada aproximadamente **65% concluída** para um sistema de pesquisa e homologação. Para um agente autônomo que opere capital real, a referência correta é aproximadamente **35% concluída**, porque aprendizado validado e controles operacionais pesam mais do que a quantidade de módulos existentes.

## 4. O que ainda exige código, e não apenas configuração

### 4.1 Dataset e treinamento real

É necessário fornecer candles reais, com timestamp, open, high, low, close e volume, para vários ativos e regimes: alta, baixa, lateralização, volatilidade e eventos de liquidez. O treinamento deve ser cronológico, com separação temporal, gap de purga e validação fora da amostra. O arquivo de treinamento não deve ser criado a partir de dados aleatórios.

Depois do treino, é necessário registrar accuracy, balanced accuracy, precision, recall, F1, matriz de confusão e calibração de probabilidade. A confiança retornada pelo Ensemble não deve ser tratada como “assertividade” até que sua calibração seja verificada em uma janela nunca usada no ajuste.

### 4.2 Backtest da IA treinada

O backtest atual avalia principalmente o sinal determinístico. A próxima etapa precisa executar o mesmo pipeline que será usado em produção: features causais, Ensemble treinado, gate de confluência, spread, comissão, slippage, latência, filtros de quantidade e regras de saída. A métrica principal não deve ser apenas win rate; deve incluir retorno líquido, profit factor, expectancy por operação, turnover, drawdown, exposição, estabilidade por ativo e desempenho por regime.

### 4.3 Proteção e reconciliação de execução

O executor atual envia ordem de mercado e registra o resultado, mas ainda precisa de um ciclo completo de proteção: stop-loss/take-profit ou OCO/bracket quando suportado, reconciliação periódica entre exchange e banco, idempotência por `clientOrderId`, recuperação após reinício, tratamento de fills parciais e kill switch acionado por erro, perda diária ou divergência de saldo.

### 4.4 Agente autônomo

O modo autônomo deve ser uma política determinística com estados explícitos: `observe → qualify → risk_check → submit → reconcile → protect → exit`. Um LLM pode auxiliar na classificação de notícias ou na explicação, mas não deve decidir e enviar ordens diretamente. Toda ordem deve passar por sinal, confiança calibrada, saldo privado, exposição, filtro da exchange e autorização operacional.

## 5. O que é apenas configuração final

Depois que o código e a validação forem concluídos, estas variáveis podem ser ajustadas sem reestruturar a aplicação:

| Configuração | Default seguro | Condição para ativar |
|---|---:|---|
| `BINANCE_MODE` | `simulated` | `demo` somente para homologação; produção exige adapter e credenciais de produção separados |
| `AUTO_START_ENGINES` | `false` | Somente após health check, banco, Redis e observabilidade |
| `AUTONOMOUS_TRADING_ENABLED` | `false` | Somente após backtest fora da amostra e shadow mode |
| `NEURAL_MODELS_ENABLED` | `false` | Somente após pesos Transformer/LSTM validados |
| `SNIPER_ENABLED` | `false` | Somente após teste independente e política de não concorrência |
| `MIN_CONFIDENCE_THRESHOLD` | `0,70` | Calibrar por validação; não reduzir por conveniência |
| `BACKTEST_MAX_VOLATILITY` | `0,08` | Ajustar por ativo/regime após amostra maior |
| `MAX_RISK_PER_TRADE` | `0,02` | Definir conforme mandato de risco; não é substituto de stop/OCO |
| `MAX_EXPOSURE_PER_SYMBOL` | `0,10` | Confirmar contra saldo e correlação entre ativos |

**Configuração sozinha não resolve** a ausência de aprendizado. As flags apenas controlam quando uma implementação já validada pode ser ativada.

## 6. Opções de implementação

| Abordagem | Resultado esperado | Trade-offs | Custo relativo | Complexidade |
|---|---|---|---|---|
| **A. Pesquisa e shadow mode no repositório atual** | Treinar Ensemble com OHLCV real, simular sinais em tempo real sem enviar ordens e comparar previsão versus resultado | Mais seguro e barato; exige dataset e período de observação | Baixo | Média |
| **B. Autonomia gradual em Sandbox** | Ativar `AUTONOMOUS_TRADING_ENABLED` somente em Demo, com capital virtual, reconciliação e relatório diário | Aproxima execução real, mas não prova rentabilidade em produção | Médio | Alta |
| **C. Produção com agente sempre ativo** | Worker persistente, PostgreSQL/Redis, observabilidade, kill switch, reconciliação, alertas e rollout limitado | Maior disponibilidade e risco operacional; requer infraestrutura e processo de incidentes | Alto e recorrente | Muito alta |

A sequência tecnicamente recomendada é **A → B → C**. A opção C não deve ser ativada enquanto o Ensemble não tiver dataset real, validação fora da amostra e relatório por regime.

## 7. Decisão técnica atual

O repositório está mais preparado para **pesquisa, backtest e homologação Demo** do que para trading autônomo com capital real. As flags de autonomia e modelos neurais permanecem desativadas por padrão. O próximo bloqueador objetivo é obter um dataset OHLCV real e executar `ai/train_ensemble.py`; sem esse arquivo, qualquer número de assertividade seria inventado.

### Referências

[1]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/BINANCE_SANDBOX_HOMOLOGATION_REPORT.md "Relatório de homologação Binance Demo do ZIA-TRADER-v17"
[2]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/core/backtest_engine.py "Backtest walk-forward do projeto"
[3]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17/blob/master/ai/feature_pipeline.py "Pipeline causal de features e rótulos"
[4]: https://developers.binance.com/en/docs/products/spot/demo-mode/general-info "Binance Spot Demo Mode — General Info"
[5]: https://developers.binance.com/en/docs/binance-spot-api-docs/faqs/order_count_decrement "Binance Spot API — Order and execution behavior"

> **Basis:** métricas de backtest são líquidas conforme taxas configuradas no projeto; não incluem ainda impacto de mercado completo. **Time:** métricas principais referem-se ao recorte Demo de 500 candles de 1 minuto registrado em 18 de agosto de 2026. **Assumptions:** scorecard de prontidão é uma avaliação de engenharia, não previsão de retorno; a execução Demo foi manualmente autorizada. **Sources & Confidence:** dados de mercado e execução vêm da Binance Demo e do relatório versionado; a confiança estatística é baixa por haver apenas duas operações. **Compliance:** This is research and analysis only, not personalized financial advice.
