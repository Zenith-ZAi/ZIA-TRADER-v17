# Fase 9 — auditoria arquitetural e primeira refatoração

**Data:** 2026-10-22. **Base:** `master` no merge do PR #20 (`f39ae9711f68ba59882a196c72e7fd4f123aa205`). **Estado desta entrega:** implementação local + testes; ainda não integrada. **Objetivo:** preparar backend para execução supervisionada e verificável, não ativar negociação autônoma, não afirmar rentabilidade e não dispensar validação externa.

## 1. DIAGNÓSTICO DO CÓDIGO ATUAL

### Bibliotecas e responsabilidade observada

| Bloco | Bibliotecas já declaradas/utilizadas | Papel no código e limite |
|---|---|---|
| API e servidor | FastAPI, Starlette, Uvicorn, Pydantic Settings | Rotas HTTP assíncronas, lifespan ASGI, auth, rate limit e WebSocket do dashboard. A rota `/ws/dashboard` envia estado a cada 2 s; não é stream de mercado. |
| Persistência | SQLAlchemy 2, Alembic, psycopg2-binary | ORM e migrações PostgreSQL versionadas. A interface do `DatabaseManager` é síncrona; operações SQL chamadas de corrotinas podem ocupar o event loop. SQLite está restrito a desenvolvimento/testes. |
| Cache/coordenação | redis-py síncrono | Locks/estado Redis são chamados através de `asyncio.to_thread` em `RedisCache`; há fallback em memória somente para cenários não autônomos. Redis não substitui a fonte persistente de ordens/ledger. |
| HTTP e provedores | HTTPX AsyncClient, requests transitivo/de provedores síncronos | `AsyncProviderHTTP` agrega timeout, semáforos, retries idempotentes, circuito e `to_thread` para provedores síncronos read-only. Não é um SDK de execução de corretora. |
| Mercado/corretoras | CCXT (`ccxt.async_support` importado sob demanda), adapters REST próprios | `MarketConnector` tem caminho async de dados; há adapters Binance/Forex/MT5/FIX e simulado. Existirem no repositório não prova que cada venue, autenticação, stream ou execução esteja homologado. Mainnet segue gated e as limitações de `client_order_id` já registradas permanecem. |
| Análise/ML | Pandas, NumPy, scikit-learn, XGBoost, PyTorch CPU | Features e indicadores tabulares, classificação/ensemble e Transformer/LSTM opcionais. Inferência de Pandas/NumPy/Torch ocorre sincronamente dentro do ciclo async do motor; não há runtime de treinamento OOS com dataset verificado nesta sessão. |
| Telemetria/segurança | Prometheus client, OpenTelemetry, python-jose, python-multipart | Métricas, tracing/exportação, JWT e formulários OAuth. O cadastro da API ainda usa usuários demo/em ambiente, não um serviço de identidade persistente multiusuário. |

### Arquitetura e fluxo de execução

Há dois entrypoints de processo. `main.py` expõe a API ASGI; `worker.py` usa `asyncio.run()` e mantém o loop de engine. Ambos podem criar `TradingManager`, cujo grafo compõe conectores, feeds, notícias, cache, risco, `OrderManager`, estratégia principal e Sniper. O motor percorre símbolos sequencialmente: busca snapshot async → constrói features/model votes e sinais localmente → avalia frescor, confluência, posição e risco → registra observações/snapshots → somente então pode submeter via `OrderManager`, se flags e gates permitirem. O worker e a API revalidam reconciliação antes do start; em estado de reconciliação inconclusivo, start deve falhar fechado.

Antes desta entrega, a importação de `main.py` executava `DatabaseManager.create_tables()` e construía `TradingManager`; o construtor atualizava runtime/configuração e consultava estado de conta, enquanto inicializava outros recursos. O mesmo processo também repetia `create_tables()` dentro do lifespan. Isso tornava importação de rotas dependente de banco/schema e podia executar migrações em momento anterior ao ciclo de vida ASGI. A API tinha ainda um contrato operacional inconsistente: o endpoint de stop chamava `stop_all()`, que fechava HTTP/exchange providers enquanto o processo permanecia disponível para requests e possível novo start.

Há operações síncronas no caminho de corrotinas além da inicialização: `DatabaseManager` abre sessões/consultas/commits síncronos; health/status/rotas chamam leituras sync e o motor registra observações, intents/histórico e estado sync no mesmo loop. O cálculo Pandas/NumPy/Torch também é CPU síncrono. Assim, o sistema é **misto** — I/O de feed frequentemente async, mas persistência e parte de cálculo bloqueantes — e não deve ser descrito como backend integralmente não bloqueante.

> **Limite de simulação:** `SimulatedExchangeAdapter` gera preços/volume com aleatoriedade e retorna saldos/respostas sintéticos. Serve para harness de desenvolvimento; não é feed histórico válido, paper broker auditável, fonte de labels, teste de fills realistas ou evidência de estratégia.

## 2. ANÁLISE DE LACUNAS (O QUE ESTÁ AUSENTE)

### Conexão ao vivo, streams e corretoras

- **Já existe:** API WebSocket de dashboard; CCXT async para determinados caminhos de dados; REST/adapters de leitura e execução encapsulados; camada central `OrderManager`; reconciliação por intent/client ID nos fluxos já documentados.
- **Ausente/não homologado:** stream WebSocket de mercado da exchange com sequência/recuperação de gaps, resubscribe, heartbeat, backpressure, deduplicação, ressincronização via snapshot REST e gate de staleness conectado ao ciclo decisório. Reconexão do dashboard não supre isso.
- **Biblioteca adicional:** não instalar `websocket-client` ou `websockets` por reflexo. `websockets` aparece no lock transitivamente, mas não há adapter próprio de stream. A biblioteca/serviço deve ser escolhido após venue, limites de conexão, licença e política de dados; o uso de API websocket do CCXT pode depender da edição/contrato escolhido e precisa de validação própria.
- **Execução de corretora:** existem adapters, porém nenhum teste Demo/Testnet ou chamada real foi feita nesta Fase 9. Ainda faltam ambiente alvo definido, contrato de idempotência por venue, limites/filtros reais, reconciliação de fills parciais e ensaio supervisionado; a mainnet permanece fora de autorização.

### Integração LLM

Não há import direto de OpenAI, Anthropic, LangChain ou outro SDK LLM nos módulos Python atuais. **Não é uma biblioteca faltante para o core de decisão/executação.** Inserir texto probabilístico de LLM no caminho de sinal, sizing, risco ou ordem seria uma ampliação de risco sem necessidade técnica demonstrada. Se houver caso de uso aprovado (por exemplo, sumarização read-only de notícias), deve ser provider opcional isolado, entrada/saída schema-validada e rastreável, com timeout/circuit/fonte, filtragem de prompt injection e resultado incapaz de autorizar ou alterar sinal/ordem. Só então escolher o SDK oficial e adicioná-lo como extra opcional, sem credenciais de live.

### Blocos fundamentais ainda pendentes

1. **Lifespan/ownership:** corrigido nesta entrega para FastAPI; manter lifecycle simétrico por processo, startup abortado com cleanup e teardown idempotente.
2. **Persistência não bloqueante:** não há SQLAlchemy AsyncSession/repository async no `DatabaseManager`; a solução deve preservar as APIs de backtest/teste enquanto migra caminho de runtime, com limites de pool, cancelamento e sem compartilhar `Session` entre threads/tasks.
3. **Reprodutibilidade de dados e decisões:** feed websocket completo e auditável; ledger de equity e execuções fechadas; dataset licenciado/hashado e modelo aprovado. Ausência continua HOLD.
4. **Identidade e secrets:** usuário demo/ENV não é gestão de identidades de produção; política de secret store/rotacionamento e papéis operacionais precisa de staging e revisão.
5. **Operação:** DB/Redis persistentes, migrations, health/readiness real, alertas, backup/restore, kill switch durável, restart/soak e observabilidade ainda precisam de prova em VPS/staging.

## 3. PLANO DE IMPLEMENTAÇÃO PASSO A PASSO

| Ordem | Subfase | Trabalho e gate objetivo | Dependência/decisão |
|---|---|---|---|
| 9.1 | Ciclo de vida ASGI — **implementado localmente nesta entrega** | Remover DB/TradingManager e DDL do import; criar recursos somente no lifespan; migrations off-loop; requests sem runtime retornam 503; shutdown fecha tasks, providers e DB uma vez. Testes unitários/API e suíte completa. | Nenhuma credencial/venue externa. CI desta branch ainda obrigatório. |
| 9.2 | Separação API/serviços | Extrair routers (auth, operations, market-read, engine-control) e dependências de runtime para `app.state`/injeção; app factory configurável para testes; eliminar globais de `main.py` sem mudar schemas de endpoint. | Teste de contratos de rotas e autenticação antes de mover cada router. |
| 9.3 | Fronteira de persistência | Inventariar cada chamada ORM do event loop. Definir repositórios async SQLAlchemy para runtime ou ponte explícita limitada a threads; nunca mover `Session` viva entre thread e event loop. Medir p95 e testar cancelamento/pool exhaustion. | Escolher PostgreSQL async driver e política de pool; compatibilidade com migrations e CI. |
| 9.4 | Streaming read-only | Especificar evento normalizado, sequência, event-time, staleness, snapshots/gaps e recuperação. Implementar adapter read-only sob feature flag, sem rota de ordens. Provar duplicata, ordenação, disconnect, gap e resync. | Usuário escolhe venue, instrumentos e fonte de dados licenciada. |
| 9.5 | Broker paper/Demo/Testnet | Validar intent/idempotency, fills parciais, fees, cancel/replace, timeout ambíguo, reconciliação após restart, kill switch e rate limits, tudo por `OrderManager`; bloquear mainnet. | Ambiente Demo/Testnet autorizado e credenciais não live, fornecidas pelo operador fora do chat. |
| 9.6 | Contrato opcional de LLM read-only | Apenas se requerido: provider isolado atrás de interface, JSON schema estrito, evidência/proveniência, timeout, budget, redaction e `HOLD` em falha. Regressão assegura que LLM não chama `OrderManager`/`RiskAI`. | Aprovação de caso de uso, fornecedor e política de privacidade; não é gate para trading. |
| 9.7 | Auditoria integrada | Dataset/modelo e ledger continuam como gates prévios; staging VPS, restore, alertas e janela de shadow/Demo supervisionada antes de qualquer decisão humana sobre modos posteriores. | Dataset licenciado/verificado, ledger reconciliado, arquitetura VPS e revisão independente. |

**Não serão instaladas bibliotecas de WebSocket/LLM nesta 9.1:** o código possui suporte async de HTTP/CCXT e WebSocket de dashboard; as lacunas são principalmente contratos, stream de venue homologado, execução observada e persistência runtime não bloqueante. Dependência sem alvo/uso selecionado adicionaria superfície e risco de supply chain sem resolver esses gates.

## 4. CÓDIGO PRÁTICO: PRIMEIRA ATUALIZAÇÃO

Implementada a subfase 9.1, sem alteração de fórmula de sinal, indicadores, thresholds, sizing, risco, modelo/weights ou flags live:

- Novo `api/application_runtime.py` concentra ownership de banco e `TradingManager`, aplica migration `create_tables()` via `asyncio.to_thread`, conecta adapter somente no startup ASGI e fecha recursos no shutdown. Em falha parcial de startup, tenta fechar o manager e sempre dispõe o pool do banco.
- `main.py` agora cria somente app/rotas no import. Runtime inexistente responde 503 com `application_runtime_not_started`; managers são injetados por `app.state.runtime` durante o lifespan. Removida duplicidade do DDL/import.
- `TradingManager.stop_engines()` passa a interromper apenas os loops; endpoint `/trading/stop` preserva clients HTTP/exchange para que o mesmo processo possa iniciar de novo. `stop_all()` fica reservado ao teardown, onde fecha providers.
- Novos testes cobrem import sem instanciar DatabaseManager/TradingManager, runtime ausente fail-closed, migrations em thread, ordem de conexão/cleanup, startup incompleto, idempotência de close e stop reiniciável. Teste pré-start da API foi adaptado ao lifecycle.

### Evidência local

- Focada: **28 passed, 1 warning** (API/lifecycle, stop, cleanup parcial, safety gates e contratos de período/Kelly).
- Suíte integral: **198 passed, 3 skipped, 1 warning**, Python 3.12.3 em venv ARM64 limpo; skip de integração depende de serviço externo não configurado; warning conhecido Starlette/PendingDeprecation.
- `compileall -q .` e `git diff --check`: exit 0. Nenhum Docker/Compose ou VPS foi executado nesta sessão.
- Flags em `.env.vps.example`: `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, `AUTO_START_ENGINES=false`, `AUTONOMOUS_TRADING_ENABLED=false`, `MANUAL_TRADING_ENABLED=false`, `NEURAL_MODELS_ENABLED=false`, `BACKTEST_USE_ENSEMBLE=false` — mantidas.

### O que esta atualização não resolveu

`main.py` continua sendo módulo grande e importa o grafo de `TradingManager`/PyTorch quando as rotas são carregadas; esta subfase remove **construção/IO de runtime** no import, mas ainda não entrega app factory nem routers desacoplados. A persistência/queries do ORM e inferência CPU continuam síncronas dentro de algumas corrotinas. Próximas correções devem tratar esse caminho com medição e testes, não convertê-lo mecanicamente para `async`.

**Conclusão da subfase:** primeira melhoria estrutural concluída localmente e testada; Fase 9 como um todo permanece em andamento até revisão/CI e subfases seguintes. Nenhum teste comprova rentabilidade, execução de exchange, integridade de ledger ou readiness VPS.
