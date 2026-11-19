# ZIA-TRADER v17 — ZT01: control-plane, análise segura e escopo por cliente

**Data:** 2026-11-19. **Autor:** Manus AI. **Base:** `master` no squash `10168db2bf49ebdf47c1c1fbb0f25ea6e463591d`, após PR #33. **Nova branch:** `fix/zt01-control-plane-and-client-scope`.

## 1. Fechamento da PR #33

A PR #33 foi revisada antes do merge. O CI original verde não bastava: Codex identificou o P2 de fontes Premium intencionalmente disabled degradando `/healthz`. O fix distingue `enabled/state/ok`; ignora somente opt-out explícito na agregação de readiness; fonte selecionada sem chave e falha real continuam unhealthy. Disabled nunca conta como fonte saudável no news entry gate. Isso evita tanto falso alarme operacional quanto falsa autorização de entrada.

O head corretivo `d672a84` passou **368 testes locais, 4 skips e um warning preexistente**. CI PostgreSQL/container `44565431970` passou. A thread P2 foi respondida e resolvida; o squash merge autorizado ocorreu em 2026-11-19 16:26:17 UTC, preservando `fix/backend-provider-security-nov19`. CI pós-merge `44566095102` também passou. Não houve publicação de servidor, negociação real ou habilitação de flags.

## 2. Maior dificuldade para concluir o Trading híbrido

O gargalo não é criar mais endpoints ou indicadores. É fechar uma cadeia de confiança verificável:

**principal autenticado → cliente/conta/venue/ambiente → dados de mercado com unidade/proveniência → fatos econômicos autenticados → reconciliação por ativo → gates de risco e autorização → efeito externo idempotente → recuperação após restart.**

Hoje existem coleta pública, análise técnica, notícias opcionais, intents/reconciliação, controles fail-closed e ledger audit-only. Ainda faltam produtor financeiro autenticado e cobertura completa de fills/fees/cashflows; identidade ligada a todas as tabelas privadas; RLS e papéis de banco adequados; ponte multiativo; OOS/modelos/limiares calibrados; e staging com restore/soak. Somar componentes prontos não comprova o funcionamento do sistema completo. Um sinal de alta confiança heurística não é probabilidade calibrada nem promessa de resultado.

## 3. Código implementado nesta fase

### 3.1 Gates de execução e menu

`execution/live_authorization.py` centraliza diagnóstico de configuração e rechecagem de autonomia/Redis. O status distingue flags pedidas/configuradas de autorização de ordem: `live_flags_passed` é apenas o resultado dos gates globais, explicitamente marcado como `configuration_gates_only_not_order_authorization`. Não substitui risco, ledger, reconciliação ou aceite humano.

`core/manager.py` e `api/runtime_services.py` deixaram de esconder configurações live com campos hardcoded false. Status/health mostram os valores reais de live, kill switch, manual, autonomia, shadow e autostart. Os defaults continuam OFF; a alteração é de diagnóstico, não de ativação.

`execution/mainnet_adapter.py` reavalia flags globais, latch local e shadow também em proteção herdada e na fronteira HTTP de todo POST. Proteções precisam de `client_order_id`; ordens/OCO usam identidade idempotente, e endpoints POST não homologados são rejeitados. A segunda checagem cobre alteração de kill switch durante awaits de normalização/leitura. GET e cancelamentos DELETE seguem o contrato existente; a política de emergência/rearm e reconciliação de proteções ainda exige homologação operacional. A checagem pré-dispatch não é atomicidade com o servidor remoto: aceite ambíguo continua exigindo recuperação por ID e reconciliação.

`execution/market_connector.py` aplica o veto antes de delegar ordem, proteção ou OCO; configuração ausente falha fechado. `cli/runtime_menu.py` agora inspeciona ou desativa LIVE localmente e arma kill switch; não pode ativar live, nem mesmo por uma confirmação textual superficial. Desativação funciona inclusive quando LIVE_MODE=true e LIVE_TRADING_ENABLED=false. `config/startup_validation.py` bloqueia autostart de rota live em desenvolvimento, staging e produção até existir rearm durável homologado. Isso não é uma implementação de rearm.

### 3.2 Autonomia e Redis no instante da tentativa

`core/engine.py` substitui o snapshot de `autonomy_blocked` por property dinâmica. Sniper e OrderManager usam o mesmo helper para novas entradas. Ativar AUTONOMOUS_TRADING_ENABLED depois da construção não ignora a exigência de Redis persistente. Confirmar pending de IA também revalida; o marcador interno de sinal validado é preservado no pending, mas não vira autorização fornecida pelo cliente.

Cache ausente/não persistente bloqueia quando Redis é obrigatório. Saídas pelo caminho específico de redução de risco não receberam o veto de novas entradas. As fixtures positivas antigas passaram a declarar Redis fake persistente/configuração simulada; não se desligou o gate real para fazer testes passarem. A propriedade de persistência não comprova sozinha liveness: leases, reconciliação, fault injection e testes reais de Redis continuam necessários.

### 3.3 Analisar mercados

`/core/analyze` continua **sob demanda, read-only**. Agora verifica os históricos exigidos por TIMEFRAME/ANALYSIS_TIMEFRAMES quando multi-timeframe está habilitado. Erro/ausência em histórico secundário obrigatório causa `data_sufficient=false`, `status=attention` e `entry_allowed=false`, mesmo se o primário gerou buy/good. News offline/falho não autoriza entrada. A candidata permanece diagnosticável, com `execution_authorized=false` e `orders_sent=0`.

`core/regime_detector.py` rejeita dados OHLC inválidos/ausentes, NaN/infinito, preços não positivos e high<low: retorna unknown/bad_data com índices finitos, sem KeyError. O cálculo de dados válidos foi preservado.

**Análise contínua independente não está habilitada nem implementada.** O shadow contínuo atual está acoplado ao motor de trading e autostart permanece false. Há lógica de regime/reversão/pivôs, mas não um módulo ZigZag explícito e persistente. A próxima entrega observacional deve ter task nativa default OFF, lifecycle/cancelamento/timeout, exclusão por símbolo/timeframe, identidade por candle fechado/fonte/versão e deduplicação. Eventos ZigZag/pivôs precisam de confirmação causal; barras futuras não podem alterar um sinal que se dizia confirmado no instante anterior. Não foi criado polling permanente ou ScheduleTask no sandbox.

### 3.4 Fundação de isolamento por cliente

A migration aditiva `c3f1e2a9b7d4`, ligada a `a5c74e8d2b91`, cria:

| Tabela | Papel e invariantes |
|---|---|
| `tenant_v1` | Identidade UUID e estado do cliente; sem senha. |
| `principal_v1` | Identidade persistida por issuer+subject único; sem credenciais de login. |
| `tenant_membership_v1` | Relação principal/cliente, role viewer/trader/admin e estado ativo. |
| `broker_account_v1` | Conta UUID pertencente ao cliente, venue/environment e referência opaca; unicidade venue/environment/ref; sem API key/secret/token. |

FKs usam RESTRICT, environment/roles/states têm CHECK e conta paper/testnet/demo/live é identidade distinta, não permissão de execução. A migration rejeita tabelas preexistentes e impede downgrade se houver dados, evitando perda silenciosa. Não houve backfill de `default_account` ou alteração do ledger antigo.

`core/client_scope.py` resolve `ClientScope` frozen por um JOIN explícito de cliente, conta, issuer/subject autenticados, membership/role e estados ativos. Tenant/account recebidos como seletores não constituem prova de ownership: o banco precisa confirmar a relação. Principais desconhecidos, conta de outro cliente, role insuficiente e payload/dict em vez de TrustedCaller são rejeitados por erro uniforme. Issuer/subject não sofrem trimming silencioso que poderia colapsar identidades; whitespace periférico é rejeitado.

**Limite essencial:** TrustedCaller é handoff de uma autenticação que já ocorreu; não valida JWT. O Scope não concede ordens, não autentica fatos financeiros e não protege contra código hostil já executando no mesmo processo Python. RLS não foi ativada; não há ligação automática ao auth por ambiente, novo endpoint privado, banco de passwords, vault, ou migração dos intents/logs/proteções/configs legados. Portanto o sistema **não está homologado como SaaS multi-cliente**. No estado atual, as rotas legadas continuam single-account; não se devem cadastrar clientes reais compartilhando esse caminho.

## 4. Matriz operacional ON/OFF

| Função | Estado entregue | O que uma flag ON não pode ignorar |
|---|---|---|
| Live | LIVE_TRADING_ENABLED=false; LIVE_MODE=false; kill=true | Shadow, IDs, reconciliação, risco/ledger, allowlist e aceite operacional. |
| Manual | MANUAL_TRADING_ENABLED=false | Modo manual, confirmação e rechecagens antes de submit/confirm. |
| Agente automatizado | AUTONOMOUS_TRADING_ENABLED=false | Modo auto, sinal interno validado, Redis, notícias/timeframes, risco e reconciliação. |
| Autostart | AUTO_START_ENGINES=false | Rota live não reativa automaticamente em qualquer ambiente. |
| Análise sob demanda | Capacidade existente e corrigida | Histórico/quote válidos; diagnóstico não é ordem autorizada. |
| Observer contínuo independente | Não implementado/ativo | Deve ser separado de saldo/posição/OrderManager e ter idempotência causal. |
| Ledger verificado | Não implementado | Getters de risco/retorno verificado permanecem None. |
| Isolamento | Fundação de escopo implementada | Falta binding auth, repositories privados completos e RLS PostgreSQL. |

Combinações ON/OFF foram exercitadas somente com mocks. Nenhuma configuração real foi ativada.

## 5. Ledger autoritativo: sequência concreta de implementação

O `equity_ledger_v1` continua **audit-only**. Append-only, Decimal e SHA-256 detectam mutação/conflito; não autenticam um provider. Não se deve criar `verified=true` vindo do cliente, aceitar source declarado como prova, nem converter omissões em zero.

1. **Enrollment autenticado e escopo.** Integrar JWT verificado ao principal/membership persistente; resolver escopo por operação; ligar account UUID a uma identidade de conta verificada pelo venue e ao ambiente/host correto. Referência de secret/vault é configuração privada do servidor, nunca URL/chave do payload. Rotação de chave não pode inventar uma conta nova nem vincular duas contas sem evidência. Se o venue não fornecer identidade adequada, exigir enrollment explicitamente homologado; hash da chave não prova ownership.
2. **Adapter read-only autoritativo.** Buscar balances, orders/trades/fees e cashflows por API autenticada/allowlisted, usando IDs/cursors completos. POST de ordem e status agregado não substituem a leitura dos fills. Paper/FIX stub/simulação não entram na allowlist de autoridade; Testnet/Demo têm homologação própria, sem promover resultados virtuais a Mainnet.
3. **Fatos imutáveis tipados.** Criar `ledger_scope_v1`, `ledger_fact_v1`, `ledger_balance_snapshot_v1`, `ledger_coverage_manifest_v1` e `ledger_period_closure_v1`. FKs ligam escopo à conta/cliente; facts têm fill/fee/funding/cashflow, asset/unidade, quantidade/preço/amount Decimal(38,18), lado/delta, trade/order/event ID, namespace de evento/símbolo quando necessário, UTC e cursor/sequence. Identidade única deve respeitar o domínio do ID do venue, não presumir IDs globais. Replay idêntico é no-op; divergente falha sem sobrescrever. Writer privado aceita somente DTOs produzidos pelo adapter autorizado; nenhum writer HTTP genérico promove dicts a fatos verificados.
4. **Cobertura e restart.** Gravar o que foi consultado, intervalo, ativos, paginação/cursor, watermark, falhas e late data. Snapshot com ativo ausente não é saldo zero. Funding de spot só é not_applicable quando o contrato de produto comprova isso; não fabricar funding=0 para um produto desconhecido. Reprocessar janela sobreposta após restart e testar falha depois de reserve, aceite remoto, fill e antes do commit. Cancelamento do await não significa rollback de efeito remoto ou de commit já iniciado.
5. **Fechamento independente.** Para cada ativo, reconciliar saldo inicial + fills/fees/funding/cashflows = saldo final na precisão homologada. Validar snapshots/cursors compatíveis, lacunas, eventos futuros/tardios e consistência temporal; um REST snapshot mutável sem sequência/cobertura não é atomicidade. Completeness precisa de manifesto, não de boolean autoatestado. Residual não explicado mantém attention. A valorização em moeda-base requer fonte/unidade próprios: USD, USDT e EUR não são intercambiáveis por conveniência.
6. **Liberação controlada de getters/risco.** Só closures persistidas geradas pelo reconciliador independente podem alimentar get_verified_risk_periods/get_verified_trade_returns. Até esse aceite, ambos permanecem None e sizing/Kelly não usam evidência audit-only. Fixtures que monkeypatcham getters validam gates downstream, não autenticidade econômica.

Aceite mínimo: fills parciais 0,04+0,06, fee em outro asset, cancelamento/fill tardio, replay concorrente, cashflow, snapshots incompletos, cursor quebrado e restart; depois PostgreSQL/role/RLS, Testnet read-only, shadow prolongado e staging. Não liberar live por checklist parcial.

## 6. Dados BTC, dólar, euro, cripto e ações

Binance público já entrega OHLCV cripto read-only. BTC/USDT tem quote USDT, não cotação Forex USD por definição. Alpha Vantage no coletor cobre equity/forex **diário** com chave, feature gate e entitlement/licença a confirmar; EUR/USD e AAPL diários não viram feeds intraday executáveis. CoinGecko é contexto agregado; Yahoo permanece bloqueado como feed executável nesse coletor.

A persistência em market_candles ainda não alimenta automaticamente o MultiTimeframeFeed do motor. Falta ponte class-aware que preserve source, asset_class, venue, moeda e timeframe; runtime global não deve normalizar EUR/USD como se fosse par crypto. Próximo piloto: BTC/USDT 1h, EUR/USD 1d e AAPL 1d com mocks e provedores admitidos, respostas explicitamente read-only, frescor/gaps/unidades e rejeição de classes mistas sem roteamento. Fontes Premium ajudam contexto, não comprovam fills ou resultado de negociação; chave não autoriza consumo pago automático.

## 7. Evidências e progresso

O smoke público da fase ZT01 confirmou novamente **119 candles fechados recebidos/persistidos/reimportados**, 119 linhas após replay, 10 features e 86 linhas válidas; resultado HOLD, `execution_authorized=false`, zero ordens, sem import de adapter de execução. Evidência: `evidence/zt01_backend_sandbox_smoke_2026-11-19.json`. Nenhuma notícia paga foi requisitada. Sintaxe, dependências e único head Alembic foram verificados. A suite e a revisão independente do novo head precisam ser registradas antes de publicar a PR desta fase.

O checklist versionado mantém **16 critérios**, com **7 aceitos: 43,75%**, calculados por `scripts/backend_progress_status.py`. Snapshot: `../progress/zt01_current_2026-11-19.json`. O único avanço no denominador global foi o fechamento efetivo da revisão/CI/aceite da PR #33 (antes: 6/16, 37,5%). Fundação de scope não fecha isolamento completo; fix de análise não fecha observer contínuo; esquema audit-only não fecha ledger autoritativo. Percentual não é segurança certificada, lucro ou porcentagem de linhas prontas.

## 8. Próximos gates, sem pular homologação

Prioridade seguinte: ligar auth/membership/conta ao piloto com RLS PostgreSQL USING/WITH CHECK e role não-superuser/NOBYPASSRLS; migrar explicitamente todas as queries privadas e chaves Redis sem adivinhar ownership de dados legados. Em paralelo funcional, criar observer read-only idempotente e ponte multiativo. Depois implementar produtor/manifesto/closure financeiro e somente então integrar risco. VPS precisa de TLS real, restart, round-trip PostgreSQL/Redis, alertas, custos/cotas e plano de incidentes. Frontend/manual/API e WebSocket/auth ainda requerem aceites próprios. Nenhuma publicação ou execução real foi autorizada nesta entrega.

## Diagrama

Linhas sólidas representam componentes implementados; tracejadas representam integrações pendentes. Azul não significa autorização operacional. Veja `../diagrams/zt01_trust_boundaries.png` e sua fonte Mermaid.

## Addendum — follow-up independente e validação final

A revisão independente inicial encontrou duas reproduções P1 (janela no worker de transporte e kill não restaurado) e um P2 (client_order_id divergente devolvendo intent antiga). Foram corrigidas antes da publicação: hook antes do request efetivo em FakeSession/HTTPX, POST unsigned rejeitado, leitura limitada/determinística do último kill event antes do adapter, latch e gravação antes do await externo, falha/ausência fechadas e **nenhum rearm live automático**, mais identidade canônica de conta/parâmetros em DAO/reconciliador com conflito explícito inclusive no insert concorrente. Nenhum payload divergente retorna os dados da intent anterior. A camada de intents permanece legada/Float; essa igualdade de replay não a promove a ledger financeiro.

O follow-up independente repetiu os oito testes novos, confirmou as três reproduções fechadas para refinamento default OFF e não encontrou novo P1 específico. Parecer inicial e follow-up: `zt01_audit/initial_independent_review.md` e `zt01_audit/followup_independent_review.md`. O veredito **operacional/Mainnet continua NÃO ACEITO**, por ledger, RLS, identidade integrada e staging; as correções não criam uma operação de rearm habilitadora.

Suíte integral definitiva: **421 passed, 5 skipped, 1 warning**. Os cinco skips exigem PostgreSQL/TEST_DATABASE_URL, incluindo a nova prova PG de constraints/escopo. `uv pip check` (117 pacotes), compileall, único head Alembic e git diff --check passaram. O CI do head publicado será consultado na PR ZT01; versões locais anteriores de 413 testes eram o checkpoint anterior ao follow-up. Não houve execução financeira, deploy ou treinamento de modelo. O snapshot distingue baseline já aceita de incremento atual ainda sem autorização de merge/deployment.
