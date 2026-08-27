# Auditoria técnica final — ZIA-TRADER-v17

**Data da auditoria:** 27 de agosto de 2026
**Objeto:** estado atual do código no ambiente virtual, incluindo core de análise, backend, execução, aprendizado, segurança, infraestrutura VPS e validação funcional.
**Base de evidência:** código local, testes automatizados, auditorias de importação/superfície, benchmark de latência e execução com dataset OHLCV público.
**Política de segurança:** nenhum trade real foi executado, nenhuma chave privada foi reutilizada e nenhum resultado de IA foi fabricado.

## 1. Conclusão executiva

O ZIA-TRADER-v17 é uma plataforma de pesquisa, análise de mercado, backtesting, shadow mode e homologação Demo/Testnet com arquitetura modular considerável. O código atual contém uma cadeia defensiva de dados, indicadores, gates de confluência, risco, execução simulada, persistência e aprendizado supervisionado controlado. Também contém uma base de deploy em VPS com Docker Compose, PostgreSQL, Redis persistente, preflight, backup e observabilidade opcional.

A conclusão realista é que **a quantidade de módulos não equivale a prontidão para capital real**. O sistema já é funcional para experimentação e pré-produção controlada, mas ainda há diferenças entre o caminho histórico e o live, dependências HTTP síncronas dentro de fluxos assíncronos, ausência de modelo de IA validado e ausência de homologação operacional em Docker, broker e infraestrutura persistente. O sistema deve permanecer em simulação, shadow, paper, Demo ou Testnet até que os critérios de passagem sejam cumpridos.

> **Estado para pesquisa/backtest/shadow e pré-produção VPS: 78/100.**
>
> **Prontidão para operação autônoma com capital real: 38/100.**
>
> Esses números são **scores de engenharia**, não porcentagem de lucro, probabilidade de acerto ou autorização de investimento. A pontuação mais baixa para capital real é intencional: faltam evidências e controles operacionais que não podem ser substituídos por mais indicadores ou mais código.

## 2. Pontuação por dimensão

| Dimensão | Score | Avaliação objetiva |
|---|---:|---|
| Arquitetura do core | **84/100** | Boa separação entre dados, análise, risco, execução, aprendizado e operação; ainda há duplicação de dependências e paridade live/backtest incompleta. |
| Análise determinística | **75/100** | EMA, RSI, MACD, ATR, volume, fluxo, pullback, tendência, reversão, multi-timeframe e microestrutura existem; pesos e thresholds ainda são majoritariamente fixos e pouco calibrados por regime. |
| Dados e integridade temporal | **74/100** | Coletor OHLCV pagina, remove candle aberto, ordena, elimina duplicatas e calcula hash; order book histórico, cobertura global homogênea e controle de gaps ainda são insuficientes. |
| Risco e gates | **79/100** | Há sizing, exposição, saldo, circuito de perda, eventos, notícias, confirmação, Spot guard, OCO estrutural e kill switch; faltam testes distribuídos e homologação de incidentes. |
| Execução em simulação/Demo/Testnet | **75/100** | Adapters, normalização, retries, idempotência, reconciliação e proteção pós-fill foram implementados; fills parciais, reconexão e OCO precisam ser comprovados contra o broker alvo. |
| Aprendizado e IA | **45/100** | Existe pipeline causal, rótulos, Ensemble, Transformer/LSTM, memória de padrões, calibração e rollback; não existe evidência suficiente de modelo treinado e generalização. |
| Backend/API | **80/100** | FastAPI, JWT/RBAC, health, métricas, middleware rate limit, worker separado e controles administrativos; não há proxy TLS/WAF/secret manager incorporados. |
| Persistência | **76/100** | SQLAlchemy suporta SQLite local e PostgreSQL no VPS; Redis com AOF e healthcheck; `create_all` ainda não substitui migrações versionadas e a restauração não foi ensaiada. |
| Segurança da aplicação | **77/100** | Defaults fail-closed, autenticação, RBAC, secrets por ambiente, rate limit e bloqueios live; ainda faltam hardening de supply chain, gestão de segredos e defesa de perímetro. |
| Infraestrutura VPS pré-produção | **73/100** | Compose separado, volumes, non-root, preflight, backup, CI e Prometheus foram preparados; Docker não está instalado no Sandbox e o deploy real não foi executado. |
| Prontidão para capital real | **38/100** | Mainnet permanece bloqueada; não há homologação independente, operação 24/7, HA, caos, restore, latência externa ou aprovação de risco. |

## 3. O que foi criado, implementado, ajustado e corrigido

### 3.1 Reconciliação, execução e risco

Foram criadas entidades persistentes para `OrderIntent`, `ReconciliationSnapshot`, `ProtectionOrder`, `KillSwitchEvent` e `BacktestRun`. O `OrderReconciler` compara intents/ordens abertas/posições observadas e grava snapshots. O `ExecutionEngine` gera e preserva `clientOrderId`, reutiliza o mesmo identificador nos retries e grava o estado da entrada e saída.

O `OCOManager` tenta proteção nativa quando o adapter declara suporte e utiliza fallback de stop-loss e take-profit quando necessário. O adapter mainnet foi isolado e permanece **fail-closed**, exigindo flags explícitas e credenciais próprias. O kill switch bloqueia novas ordens e tenta cancelar ordens abertas, além de registrar o evento no banco.

Foi corrigida uma falha no `TradingManager`: o `db_manager` não estava atribuído no construtor, embora fosse usado para registrar o kill switch. Também foi corrigido o risco de usar saldo local potencialmente obsoleto: quando a autonomia está ativa e o saldo privado da exchange não está disponível, a entrada agora é bloqueada em vez de dimensionada com um saldo antigo.

### 3.2 Core de análise e decisão

O `RoboTraderUnified` coordena o ciclo por símbolo. Ele busca histórico, cotação, livro, notícias e tendências; constrói features; avalia Transformer/LSTM/Ensemble quando há artefatos válidos; calcula sinal determinístico; aplica pullback, fluxo, notícias, eventos, multi-timeframe, memória de padrões, pré-mercado, risco, custo, circuito de perda e saída emergencial; grava observação shadow; e somente então considera execução.

O comportamento padrão de ausência de modelo é conservador: sem pesos ou metadados válidos, a camada de modelo permanece em `hold`. O sinal determinístico pode produzir um candidato direcional, mas a confluência final exige confirmação de modelo, gates e risco. Isso reduz operações indevidas, embora também gere baixa cobertura e sensação de lentidão.

O `SniperEngine` é um segundo caminho de decisão para variações rápidas. Ele usa preço, livro, whale detector, pullback, eventos, notícias quando injetadas, custo e risco. Por ser um loop separado, exige cuidado especial com lock de instância, duplicidade de ordens e compartilhamento de estado.

### 3.3 Dados, indicadores e contexto

O repertório atual inclui coleta OHLCV pública, Yahoo read-only para ações/B3 e fallback de Forex público, Binance Demo/Testnet/simulação, CCXT opcional com restrições, feeds multi-timeframe, livro de ofertas, fluxo nocional, notícias RSS/GDELT/CoinGecko/Benzinga/Marketaux/Finnhub/TwelveData/Alpha Vantage/NewsAPI/CryptoPanic, snapshots de tendência e persistência de artigos.

O cálculo determinístico combina EMA rápida/lenta, momentum, RSI, MACD, ATR/volatilidade, volume, sentimento, tendência externa e desequilíbrio do livro. A regra 2x1 exige dominância mínima configurável quando a confirmação de fluxo está habilitada. O pullback usa tendência macro, toque, exaustão, gatilho, ATR, stop, alvo e breakeven. O detector de baleias usa concentração do book quando o dado está disponível, não uma magnitude simulada arbitrária.

### 3.4 Aprendizado e treinamento

O `SignalLearningLayer` grava contexto anterior e rotula somente depois que há candles futuros suficientes. O pipeline Ensemble implementa split cronológico, gap de purga, métricas OOS, calibração por faixas de confiança, critério de aceitação e backup/rollback. O treinamento não é chamado automaticamente pelo loop live, e Transformer/LSTM não são treinados sem procedimento explícito.

O pipeline foi executado anteriormente com um candidato temporário. O F1 macro de validação foi `0,3476`, o F1 macro de teste foi `0,2806` e o Sharpe proxy de teste foi `-0,6795`; o artefato não foi promovido. Isso é um resultado útil de governança: o fluxo funciona e o candidato não foi tratado como vantagem financeira.

### 3.5 Backend, infraestrutura e deploy

A API FastAPI possui autenticação OAuth2/JWT, RBAC, healthcheck, métricas Prometheus, endpoints de análise, sincronização, controle e kill switch. O rate limiting passou a ser aplicado por middleware HTTP, com `429` e `Retry-After`; as chamadas manuais duplicadas foram removidas dos handlers. O worker foi separado da API e executa reconciliação inicial antes do loop.

A preparação para VPS inclui `docker-compose.vps.yml`, PostgreSQL, Redis com AOF e senha, job `db-init`, volumes de dados/modelos/logs, API ligada inicialmente a localhost, worker separado, jobs mensais de backtest e notícias, Prometheus opcional, `.env.vps.example`, preflight estrito, backup e runbook. A imagem usa usuário non-root e o contexto Docker foi limpo para não incluir datasets, logs ou backups locais.

## 4. Camadas do backend

| Camada | Componentes principais | Responsabilidade real | Estado |
|---|---|---|---|
| Transporte | FastAPI, OAuth2 password flow, WebSocket dashboard | Receber comandos, autenticar, retornar estado, health e métricas | Funcional; precisa de TLS/proxy para exposição externa |
| Proteção HTTP | Middleware de rate limit, CORS, RBAC | Reduzir abuso e separar permissões administrativas/trader | Funcional localmente; Redis distribuído e WAF ainda faltam |
| Orquestração | `TradingManager`, `worker.py`, ciclo de vida da API | Iniciar/parar motores, reconciliação, kill switch, shutdown | Funcional; lock de instância e supervisão externa faltam |
| Feeds | `MultiTimeframeFeed`, adapters, news processor | Consolidar histórico, ticker, book, notícias e tendências | Funcional; chamadas externas ainda podem bloquear o event loop |
| Features | `FeaturePipeline`, indicadores, caches causais | Produzir vetor comum para live/backtest/treino | OHLCV centralizado; notícias/fluxo não estão totalmente no vetor comum |
| Decisão | sinais, pullback, reversão, multi-timeframe, gates | Produzir `buy`, `sell` ou `hold` explicável | Funcional e conservadora |
| Risco | RiskAI, Kelly adaptativo, exposição, circuit breaker, microestrutura | Validar saldo, tamanho, custo, perdas e limites | Funcional estruturalmente; precisa de testes de incidente reais |
| Execução | OrderManager, ExecutionEngine, adapters, friction | Confirmar, enviar, persistir, proteger e reconciliar ordens | Adequado para simulação/Demo/Testnet; não homologado para mainnet |
| Aprendizado | observations, labels, PatternMemory, Ensemble, treinamento OOS | Registrar resultados e criar candidatos versionados | Estrutural; pouca evidência estatística de generalização |
| Persistência | SQLAlchemy, SQLite local, PostgreSQL VPS, Redis | Estado, histórico, intents, snapshots, cache e backtests | PostgreSQL/Redis preparados; migrações/restore ainda faltam |
| Operação | CLI Rich, scripts, Docker Compose, CI, Prometheus, OpenTelemetry | Execução manual, jobs, deploy e observabilidade | Pré-produção; perímetro e operação 24/7 faltam |

## 5. Impacto atual do código

O impacto positivo mais importante é **reduzir a probabilidade de uma decisão sem contexto**. O algoritmo tende a permanecer em `hold` quando o histórico é curto, o score é fraco, indicadores divergem, o fluxo não confirma, o livro está ausente, o evento está bloqueado, o modelo não existe, a notícia falha sob política fail-closed, o saldo não é confirmável ou o circuito de perda está acionado. A idempotência, a reconciliação e a proteção pós-fill reduzem risco de inconsistência de estado, mas ainda dependem do contrato real do broker.

O impacto negativo é a baixa cobertura e a latência acumulada. Um sistema que exige simultaneamente modelo, pullback, fluxo, notícias, multi-timeframe, custo e risco terá menos sinais do que um sistema que usa apenas cruzamento de médias. Isso é esperado e não deve ser “corrigido” simplesmente baixando thresholds: a redução de filtros pode aumentar falsos positivos e risco operacional.

O sistema não “aprende o mercado” como uma entidade autônoma com entendimento geral. Ele calcula variáveis, registra observações, recebe rótulos definidos por horizonte e pode treinar um Ensemble sob procedimento controlado. Aprendizado online, drift, causalidade de notícias, impacto de liquidez e adaptação a regimes ainda precisam de desenho e validação adicionais.

## 6. Testes e validação executados

### 6.1 Suíte automatizada

A validação completa terminou com **78 testes aprovados** e dois warnings não bloqueantes: a depreciação de `python_multipart` e o aviso de `batch_first` do Transformer. A compilação dos pacotes críticos passou. A auditoria de importação carregou `main`, `worker`, `security.rate_limiter` e `execution.order_manager` com sucesso. A auditoria de superfície encontrou 27 rotas FastAPI.

### 6.2 Teste final de lógica

Foi criado `scripts/final_logic_audit.py` e executado sobre `data/replay_btcusdt_1h.csv`, com 499 candles públicos. Os dez checks passaram:

| Check | Resultado |
|---|---|
| Schema de features não vazio | Passou |
| Sinal causal inalterado por mutação de dados futuros | Passou |
| Fluxo comprador 2x1 produz buy | Passou |
| Book vazio permanece neutro | Passou |
| Sinal é não executável por si só | Passou |
| Microestrutura retorna decisão booleana | Passou |
| Notícias ausentes bloqueiam entrada sob fail-closed | Passou |
| Circuit breaker bloqueia após perda excessiva | Passou |
| Backtest retorna resultado válido | Passou |
| Flags live permanecem false e ordens enviadas são zero | Passou |

Nesse teste, o sinal observado foi `hold` com candidato `buy`, score `0,2943485`. O backtest técnico do recorte produziu 12 trades, PnL `184,4034`, retorno `1,8440%`, Sharpe `1,2319` e drawdown máximo `-0,6061%`. Esses números são uma saída de um dataset curto e de uma configuração de teste; **não são prova de rentabilidade, não são taxa de acerto de IA e não devem ser extrapolados**.

### 6.3 Latência local

O benchmark final foi executado cinco vezes sobre o mesmo dataset, em processo local, sem rede, REST, WebSocket, TLS, roteamento, fila ou matching engine. Os resultados centrais foram:

| Componente | p50 (ms) | p95 (ms) |
|---|---:|---:|
| Features causais | 7,404609 | 7,917907 |
| Construção do cache Pullback | 68,670003 | 69,857334 |
| Sinal com Pullback | 55,921439 | 57,871663 |
| Sinal com Pullback já em cache | 5,575754 | 5,946296 |
| Decisão local combinada sem cache | 60,586418 | 62,571148 |
| Decisão local combinada com cache | 12,133760 | 12,229392 |

O ponto fraco de desempenho é claro: **reconstruir o Pullback e indicadores derivados em todo ciclo é muito mais caro do que a inferência Ensemble quando o modelo está ausente**. O cache reduz substancialmente o custo local, mas não elimina o custo de rede nem a espera de provedores.

### 6.4 Backtest mensal técnico

O runner mensal foi executado com 31 dias de BTCUSDT em 1h, 743 barras públicas fechadas, hash SHA-256 `6c8ad295a07962ea5b99b59dc0fe1bbaa080243d16b7662cb7ddbd31927a6c79`, banco temporário e `orders_sent: 0`. O fluxo terminou com status `ok`, `model_promoted: false` e zero trades no recorte. A diferença entre esse resultado e o teste final de lógica decorre das configurações e do caminho de dados usados; nenhum dos dois resultados certifica desempenho futuro.

## 7. Pontos fracos, bugs potenciais e lentidão da IA

### 7.1 I/O síncrono dentro de funções assíncronas

`YahooB3Adapter`, `ForexPublicReadOnlyAdapter`, partes de `MarketConnector` e `NewsProcessor` usam `requests.get` dentro de caminhos `async`. O `asyncio.gather` organiza as tarefas, mas uma chamada síncrona pode bloquear o event loop enquanto aguarda rede. Em um VPS com vários símbolos, isso aumenta latência, impede resposta rápida da API e pode atrasar o worker inteiro.

**Correção recomendada:** adotar `httpx.AsyncClient`/cliente assíncrono com pool de conexões, timeout separado para conexão/leitura, circuit breaker por provedor, limite de concorrência e cache TTL. Como transição, `asyncio.to_thread` é preferível a bloquear o loop, mas não substitui um cliente assíncrono bem configurado.

### 7.2 Reconstrução repetida do Pullback

O motor principal cria `PullbackSignalCache` dentro de cada ciclo e calcula uma série histórica inteira para obter o último sinal. O benchmark mediu p50 de aproximadamente 68,67 ms para construir esse cache e decisão combinada sem cache de aproximadamente 60,59 ms. O resultado é uma possível sensação de “IA lenta”, embora o gargalo seja feature engineering repetido, não necessariamente a rede neural.

**Correção recomendada:** manter cache por `(símbolo, timeframe, último_timestamp_fechado)`, recalcular apenas quando chegar candle fechado novo, compartilhar o objeto entre análise e backtest, e evitar criar novamente o cache no Sniper para a mesma janela.

### 7.3 Muitas fontes por símbolo e por ciclo

Para cada símbolo, o feed busca históricos dos timeframes configurados, cotação, livro, notícias e tendências. Se houver três símbolos e três timeframes, o número de chamadas pode crescer rapidamente. Rate limits externos, timeouts e retries passam a dominar o tempo total, mesmo quando o cálculo local é rápido.

**Correção recomendada:** separar coleta de dados do ciclo de decisão; usar um agregador periódico que atualiza snapshots e um consumidor que decide sobre o snapshot mais recente; limitar concorrência por provedor; registrar idade do dado e rejeitar snapshot atrasado.

### 7.4 Estado Redis duplicado entre componentes

`TradingManager` cria um `RedisCache`, enquanto `RoboTraderUnified` cria outro internamente. Com Redis real, ambos apontam para o mesmo backend, mas com fallback em memória eles são stores diferentes. Isso pode fazer Engine, Sniper e ExecutionEngine observarem estados diferentes quando Redis está indisponível.

**Correção recomendada:** injetar a mesma instância de `RedisCache` em todos os motores, bloquear autonomia quando a persistência não estiver disponível e manter um lock distribuído por conta/símbolo.

### 7.5 Ausência de modelo validado

O modelo ausente não é um bug de segurança; é uma trava correta. Porém, funcionalmente, significa que o ensemble não gera decisão real no runtime. O Transformer/LSTM existe como arquitetura e o Ensemble possui código de inferência, mas sem pesos e metadados aprovados não há aprendizado operacional demonstrado.

**Correção recomendada:** criar dataset imutável multiativo e multirregime, treinar candidatos fora do worker, avaliar por período/ativo/regime, medir calibração e drift, e promover somente após revisão humana. Não reduzir o threshold para mascarar a ausência de modelo.

### 7.6 Paridade incompleta entre backtest e live

O backtest utiliza OHLCV walk-forward e fricção; o live utiliza notícias, livro, saldo, eventos, multi-timeframe, providers e adapters. A transformação OHLCV foi centralizada pelo `FeaturePipeline`, mas notícias, fluxo e microestrutura não formam ainda um vetor idêntico nos dois caminhos. Uma estratégia pode parecer boa no histórico porque não enfrenta exatamente os mesmos filtros e custos do runtime.

**Correção recomendada:** definir um `DecisionSnapshot` versionado, congelar o schema, registrar todos os inputs usados em cada decisão e permitir replay do mesmo snapshot no backtest.

### 7.7 Proteção e reconciliação ainda não homologadas no broker

O OCO nativo/fallback, `clientOrderId`, retries e reconciliação são implementações estruturais. Ainda é preciso testar no Demo/Testnet: timeout depois do envio, resposta perdida, fill parcial, proteção parcial, cancelamento da ordem oposta, reinício entre entrada e proteção, clock drift, rejeição de quantidade/preço e divergência de saldo. Sem esses testes, não se deve tratar a proteção como garantia real.

### 7.8 Eventos e notícias não são saída forçada por default

A janela de evento e o gate de notícias podem bloquear novas entradas. A saída emergencial por evento ou choque de notícia existe como capacidade configurável, mas permanece desligada por default e não deve ser ativada sem uma política de risco clara. Uma entrada bloqueada não significa que uma posição existente será fechada automaticamente.

### 7.9 Sniper e concorrência

O Sniper é um segundo loop rápido, não apenas uma configuração do motor principal. Ele precisa compartilhar lock, estado, idempotência e limites de risco com o motor principal. Sem coordenação distribuída, dois loops podem analisar o mesmo símbolo e disputar a mesma posição em caso de reinício ou atraso.

### 7.10 Persistência e migrações

`Base.metadata.create_all` é conveniente para inicialização, mas não substitui migrações versionadas, rollback de schema e revisão de alterações em PostgreSQL. O job `db-init` reduz corrida de inicialização, mas o VPS ainda precisa de migração formal, backup externo, restauração ensaiada e menor privilégio para a conta da aplicação.

## 8. Segurança atual e riscos residuais

| Controle | Situação atual | Risco residual |
|---|---|---|
| Flags live | `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, shadow ativo por padrão; Compose VPS fixa live false | Qualquer futura alteração deve passar por revisão e aprovação dupla |
| Credenciais | Templates sem valores reais; ambiente separado | Secret manager, rotação e auditoria ainda não implantados |
| Autenticação | JWT/OAuth2 e RBAC admin/trader | Usuários de demonstração não são solução de produção |
| Rate limit | Middleware por IP/token com 429 | Para múltiplas réplicas, precisa de estado Redis/edge confiável |
| Rede | Compose VPS publica API em localhost inicialmente | Firewall, TLS, proxy reverso, WAF e allowlist ainda dependem do operador |
| Banco | PostgreSQL preparado, schema aditivo e healthcheck | Sem restore real, HA, RPO/RTO e migração versionada comprovados |
| Redis | AOF, senha e preflight de persistência | Não há HA/failover; fallback em memória é aceitável só fora da autonomia |
| Container | Non-root, cap drop, no-new-privileges, read-only em API/worker | Falta build real no Sandbox, SBOM, scan CVE e digest imutável da imagem |
| Observabilidade | Logs, métricas, telemetria e Prometheus opcional | Falta alerta 24/7, retenção, SLO e resposta a incidentes |
| Kill switch | Bloqueia novas ordens, cancela quando suportado e persiste evento | Precisa de teste independente, alertas e procedimento humano |

Credenciais que tenham aparecido em arquivos antigos não devem ser reutilizadas. Se ainda estiverem ativas, devem ser revogadas e rotacionadas. Nenhuma delas foi incluída neste relatório ou no repositório.

## 9. O que falta para considerar 100% no ambiente virtual

“100%” precisa ser definido como **100% dos critérios de pré-produção verificáveis**, não como promessa de lucro ou impossibilidade de falha. Para chegar a esse nível no ambiente virtual, faltam:

| Prioridade | Entrega | Evidência exigida |
|---|---|---|
| P0 | Build Docker real | Build no CI/VPS, scan CVE, SBOM, imagem fixada por digest e teste de healthcheck |
| P0 | PostgreSQL operacional | Migrações versionadas, usuário least-privilege, backup externo e restauração automatizada em ambiente isolado |
| P0 | Redis operacional | Persistência confirmada, senha fora de logs, política de falha e teste de reinício/failover |
| P0 | Lock de instância | Apenas um worker/conta/símbolo pode executar decisão e ordem por vez |
| P0 | Demo/Testnet E2E | Fills parciais, timeouts, retry idempotente, OCO/fallback, cancelamentos e reconciliação após restart |
| P0 | Dados reproduzíveis | Datasets multiativo, multi-regime, hash, cobertura, gaps e timestamps UTC auditados |
| P1 | Paridade live/backtest | `DecisionSnapshot` comum, replay de snapshots e mesmos custos/gates |
| P1 | Desempenho | Cliente HTTP assíncrono, cache incremental e teste com número real de símbolos/timeframes |
| P1 | Observabilidade | Dashboards, alertas de reconciliação, latência, saldo, erro, restart e kill switch |
| P1 | Segurança de perímetro | TLS, proxy reverso, firewall, WAF/allowlist, headers e autenticação operacional |
| P1 | Modelo aprovado | Ensemble treinado com OOS, calibração, drift, relatório por ativo/regime e rollback ensaiado |
| P2 | Dados de order book | Histórico de profundidade e replay de impacto/slippage, sem usar proxy como se fosse book real |
| P2 | Treinamento em escala | Dataset versionado, pipeline reproduzível, aprovação humana e monitor de degradação |
| P2 | Exercício de incidente | Caos de rede, relógio, banco, Redis, provider, exchange, kill switch e recuperação documentada |

Mesmo depois disso, 100% estrutural não significa 100% de acerto. Mercado muda, liquidez desaparece, APIs falham e o custo real pode diferir do backtest.

## 10. Sequência recomendada para os próximos 30 dias

Na primeira etapa, o VPS deve executar somente PostgreSQL, Redis, API, worker em shadow e jobs de coleta/backtest. O operador deve acompanhar idade dos dados, saúde dos providers, reconciliação, latência, PnL simulado, drawdown, custos, número de sinais e motivo de cada `hold`.

Na segunda etapa, execute o backtest mensal multiativo com datas UTC fixas, armazene hashes e resultados no PostgreSQL e produza relatório por ativo e regime. Rode o replay causal e o treino OOS somente em diretório de candidato. O modelo candidato deve ser comparado com baseline e permanecer desligado se o teste ou a calibração forem fracos.

Na terceira etapa, use Demo/Testnet com chaves dedicadas, sem saque, limites mínimos e autonomia inicialmente desligada. Faça testes de restart, rede, fill parcial, OCO, reconciliação e kill switch. Só depois de uma janela prolongada e aprovação humana pode ser discutida uma exposição controlada; esta auditoria não autoriza isso.

## 11. Referências internas

[1]: core/engine.py "Motor central de decisão, gates, risco e execução"
[2]: core/data_feeds.py "Agregação de históricos, cotação, book, notícias e tendências"
[3]: core/market_signals.py "Indicadores, score, confiança e sinal causal"
[4]: core/pullback_strategy.py "Pullback, ATR, stop, alvo e breakeven"
[5]: risk/risk_ai.py "Sizing, exposição, saldo e validação de ordens"
[6]: execution/execution_engine.py "Idempotência, intents e persistência de execução"
[7]: execution/oco_manager.py "Proteção OCO/bracket e fallback"
[8]: core/reconciliation.py "Reconciliação de ordens e posições"
[9]: learning/training_pipeline.py "Treinamento OOS, calibração e rollback"
[10]: scripts/final_logic_audit.py "Teste funcional final de lógica"
[11]: reports/final_logic_audit.json "Resultado do teste final"
[12]: reports/final_latency_benchmark.json "Benchmark local de latência"
[13]: docker-compose.vps.yml "Arquitetura de serviços para VPS"
[14]: scripts/vps_preflight.py "Preflight de persistência e segurança"
[15]: docs/VPS_DEPLOYMENT_RUNBOOK.md "Runbook de migração e operação VPS"

**Basis:** os scores medem qualidade estrutural e evidência de validação do software; métricas de retorno do backtest não foram tratadas como previsão. **Time:** auditoria em 27 de agosto de 2026; dataset do teste final entre 4 e 25 de agosto de 2026 UTC. **Assumptions:** flags live desligadas, shadow ativo, modelos ausentes tratados como neutros e nenhum endpoint de ordem real chamado. **Sources & Confidence:** confiança alta para inventário, testes locais e latência local; confiança baixa para generalização, slippage real e estabilidade em mercado ao vivo. **Compliance:** This is research and analysis only, not personalized financial advice.
