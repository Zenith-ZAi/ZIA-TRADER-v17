# Relatório final — Upgrade 2 do ecossistema ZIA-TRADER-v17

**Autor:** Manus AI
**Data da validação:** 22 de agosto de 2026
**Repositório:** [Zenith-ZAi/ZIA-TRADER-v17](https://github.com/Zenith-ZAi/ZIA-TRADER-v17)

## Escopo

O Upgrade 2 implementa as lacunas operacionais descritas em `Promptdeupgrade2.txt`, preservando a arquitetura FastAPI, SQLAlchemy, Redis com fallback, adapters existentes e os defaults de segurança do projeto. O objetivo foi criar uma superfície unificada para mercados, ordenar o fluxo de confirmação, expor os endpoints de operação e testar o motor em replay sem enviar ordens.

> **Regra operacional mantida:** `BINANCE_MODE=simulated`, `AUTONOMOUS_TRADING_ENABLED=false`, `MANUAL_TRADING_ENABLED=false`, `SHADOW_MODE_ENABLED=true`, `ORDER_CONFIRMATION_REQUIRED=true` e `ALLOW_SHORT=false` permanecem como defaults seguros.

## Implementações

| Componente | Implementação entregue | Limite consciente |
|---|---|---|
| `MarketConnector` | Fachada unificada para cripto, Forex e B3, com normalização de símbolos | B3 Yahoo é somente leitura; Forex live continua fail-closed |
| Cripto | Mantém Binance simulada, Demo/Testnet e suporte opcional CCXT para Spot/Futures | Binance Futures via CCXT exige credenciais e configuração explícitas |
| Forex | Forex paper existente; cotações públicas com `forex-python` e fallback Yahoo | Não há OANDA/FXCM live sem adapter, contrato, autenticação e testes do broker |
| B3 | OHLCV/cotação pública Yahoo, identificadores `.SA` | Não há envio de ordens para B3 |
| `OrderManager` | Aceita comandos manuais ou decisões IA, usa confirmação visual, deduplicação e modo `manual/auto` | Live externo permanece bloqueado sem `MANUAL_TRADING_ENABLED` ou autonomia explícita |
| API | `/status`, `/order`, `/order/confirm`, `/market`, `/logs`, além das rotas pré-existentes | `/logs` retorna JSON auditável das últimas 24h |
| Launcher | `scripts/run_backend.py` executa FastAPI em thread de background | O processo deve permanecer ativo para manter a API disponível |
| Pré-mercado | `PreMarketGate` bloqueia histórico insuficiente, volatilidade acima do limite e contexto de notícias indisponível | No replay de segurança, notícias foram deliberadamente neutralizadas |
| Kelly | `AdaptiveKellySizer` estima Kelly fracionário, ajusta risco pela volatilidade e limita risco máximo | Histórico insuficiente não promove uma estratégia automaticamente |
| Persistência | Ordens/execuções/posições continuam usando SQLAlchemy e Redis/estado runtime existente | Redis não disponível no sandbox foi tratado como fallback de memória |
| Menu | Novo menu `Trading Híbrido` no `admin_console.py`, com conexão, modo, pré-mercado, relatório e ordem manual confirmada | A confirmação manual não foi acionada durante a validação |

## Validação automatizada

A compilação Python, a suíte completa e a auditoria de whitespace foram executadas com:

```bash
python3 -m compileall -q .
python3 -m pytest -q
git diff --check
```

O resultado final foi **62 testes aprovados**, com dois avisos não bloqueantes: uma depreciação do parser multipart do Starlette e um aviso de otimização do Transformer do PyTorch. Nenhuma falha de teste, erro de compilação ou credencial foi introduzido.

Os testes novos cobrem normalização de símbolos, modo manual, confirmação visual, bloqueio de adapter live sem habilitação explícita, Kelly adaptativo, PreMarketGate, Forex paper/live fail-closed e superfície REST.

## Replay de uma hora

O script `scripts/run_upgrade2_replay.py` executou 60 ciclos por mercado, equivalentes a uma hora simulada, com `place_order` substituído por uma exceção explícita. A série cripto foi obtida publicamente de Yahoo Finance (`BTC-USD`, intervalo de 1h, 1.434 barras entre 24/06/2026 e 22/08/2026). A série Forex tentou o caminho público e caiu para o adapter Forex paper determinístico quando a fonte pública não entregou histórico utilizável.

| Mercado | Barras/ciclos | Observações | p50 do ciclo | p95 do ciclo | Máximo | < 200 ms | Ordens |
|---|---:|---:|---:|---:|---:|---|---:|
| BTC/USDT replay | 60 / 60 | 60 | 127,643764 ms | 136,643276 ms | 145,363461 ms | **Sim** | 0 |
| EUR/USD replay | 60 / 60 | 60 | 32,970960 ms | 35,213793 ms | 40,451484 ms | **Sim** | 0 |

A métrica é tempo de ciclo do motor no sandbox, não latência de matching, rede, TLS, saldo privado ou corretora. O Redis estava indisponível (`localhost:6379`), e o motor registrou o fallback de memória; por isso o resultado comprova o comportamento funcional do replay, mas não certifica uma implantação live persistente.

## Comandos principais

Para executar o console administrativo em modo manual ou automático:

```bash
python3 admin_console.py --mode manual
python3 admin_console.py --mode auto
```

Para iniciar a API em background:

```bash
python3 scripts/run_backend.py --host 127.0.0.1 --port 8000
```

Para executar o replay com um dataset público local:

```bash
python3 scripts/run_upgrade2_replay.py \
  --crypto-dataset /caminho/para/btcusd_replay_1h.csv \
  --output /tmp/upgrade2_replay_result.json
```

## Riscos e limitações remanescentes

O suporte a Binance Spot existente permanece separado do caminho opcional CCXT Futures. A presença de uma chave em um arquivo de ambiente não prova que a permissão, o endpoint, o relógio, o `recvWindow`, o lote mínimo ou a margem estão corretos. O arquivo de APIs anexado foi utilizado somente como referência local e **não foi copiado, exibido, versionado ou incluído no pacote**. As chaves devem ser rotacionadas se tiverem sido compartilhadas fora de um canal seguro.

O replay comprovou latência inferior a 200 ms no ambiente atual, mas não valida a meta de 1–3 ms em produção. Para isso ainda são necessários host próximo da corretora, Redis persistente, sincronização de relógio, monitoramento de filas, limites de taxa, reconciliação de ordens após restart e teste de conectividade do broker escolhido.

O modo automático continua subordinado ao kill-switch. A combinação `ORDER_CONFIRMATION_REQUIRED=true`, `AUTONOMOUS_TRADING_ENABLED=false` e `MANUAL_TRADING_ENABLED=false` impede ordens externas por padrão. O código não promove estratégias com amostra estatística insuficiente nem interpreta o fallback paper como dado de mercado real.

## Conclusão

O backend agora contém a estrutura operacional solicitada para conexão unificada, modo híbrido, API, pré-mercado, sizing adaptativo, persistência e menu. A validação de 62 testes e o replay de 60 ciclos por mercado foram aprovados sem ordens. O sistema está apto para continuar em shadow, paper e Sandbox supervisionada; não deve ser promovido a capital live irrestrito sem broker Forex/B3 homologado, Redis persistente e validação fora do sandbox.

## Referências

[1]: https://github.com/Zenith-ZAi/ZIA-TRADER-v17 "Repositório ZIA-TRADER-v17"

[2]: https://github.com/ccxt/ccxt "CCXT — biblioteca de conectores de exchanges"

[3]: https://pypi.org/project/forex-python/ "forex-python no Python Package Index"

[4]: https://pypi.org/project/yfinance/ "yfinance no Python Package Index"

[5]: https://developers.binance.com/docs/binance-spot-api-docs "Binance Spot API Documentation"
