# Fase 10.1 — Trend Alignment como veto independente

## Escopo implementado

A proposta `novahabilidades.txt` determina inspeção prévia do repositório, reaproveitamento de módulos existentes, implementação em incrementos pequenos e nenhuma ativação de trading live. A inspeção confirmou que RSS/GDELT e provedores opcionais já são tratados por `NewsProcessor`; o core já oferece `MarketRegimeDetector`, `detect_reversal_signal`, `analyze_order_flow`, `estimate_entry_costs`, os gates de notícias/eventos, `RiskAI` e `OrderManager`. Criar versões paralelas destes serviços aumentaria o risco de contratos divergentes.

O primeiro incremento implementa apenas um `TrendAlignmentFilter` em `core/trend_alignment.py`. Não altera pesos dos modelos, indicadores, thresholds existentes, sizing ou o modelo preditivo. O filtro só responde se seu próprio gate passou; não concede autorização final de ordem.

Em `strong_trend`, o sinal alinhado à direção do `trend_index` passa pelo filtro somente se risco e microestrutura também passarem. Um candidato contra a tendência exige simultaneamente uma reversão do detector existente com `detected=true`, `from` igual à direção da tendência e `to` igual ao candidato; confiança atual de pelo menos 0,70 (ou valor maior definido pelo limite existente); fluxo com dados completos e ação concordante; microestrutura aprovada; e circuito de risco não disparado. `high_volatility`, `unknown`, `uncertain`, `news_shock` e `liquidity_crisis` bloqueiam entradas. Regimes reconhecidos como neutros não substituem os gates seguintes.

`RoboTraderUnified` executa o veto antes do único caminho de entrada. Em falha, converte o candidato em `HOLD`, define confiança final como zero e mantém a explicação em `market_context`, observação shadow e snapshot de decisão. `OrderManager.submit(source="ai")` verifica de novo a presença de `trend_alignment.passed is True`, para rejeitar submissões IA que tentem omitir o resultado. A rota de saída por `submit_exit` não exige o filtro de entrada; assim, o novo veto não bloqueia um fechamento existente.

## Arquivos e dependências

- `core/trend_alignment.py`: avaliação pura do gate e validação do limite mínimo de confiança para reversões.
- `core/engine.py`: integração no ciclo de decisão e persistência do resultado em contexto de auditoria.
- `execution/order_manager.py`: enforcement do gate no boundary de entrada IA.
- `tests/test_trend_alignment.py` e `tests/test_final_safety_gates.py`: testes unitários e regressão anti-bypass.
- `docs/reports/zia_logic_flow_2026-11-02.mmd`: diagrama atualizado para mostrar o novo veto antes de risco e submissão.
- `docs/FINALIZATION_ROADMAP.md` e `docs/FINDINGS.md`: status desta subfase e limitações.

Nenhuma dependência foi adicionada. Não houve alterações a segredos, migrations, tabelas, conectores de dados, APIs de ordens ou flags de trading.

## Conectores e ingestão no ambiente atual

A sessão disponibiliza ao agente MCP CoinGecko e Supabase. O catálogo também lista Alpha Vantage, mas a descoberta das ferramentas deste servidor falhou por erro de autenticação nesta sessão. Isso descreve acesso do agente e não significa que as credenciais MCP sejam automaticamente entregues ao processo Python, ao container ou ao banco do ZIA-TRADER. Nenhum projeto Supabase foi consultado ou alterado.

No código, `NewsProcessor` implementa RSS e GDELT, tendências CoinGecko, e provedores opcionais dependentes de API keys. As chaves diretas Alpha Vantage, CoinGecko, Finnhub e Marketaux não estão definidas no ambiente corrente. `scripts/ingest_news.py` é um CLI de execução pontual que chama `fetch_all`/`fetch_trending` e persiste artigos e tendências no banco quando executado. A coleta opcional `market-snapshot-collector` usa o endpoint público de dados da Binance e grava arquivos em `app_data`; o serviço está sob profile `collector` e seu intervalo configurado é 60 segundos. Isso não é ingestão validada de snapshots no Postgres. O Compose principal não cria um Trigger/ScheduleTask do Manus. Não foi criado nenhum agendamento.

ScheduleTask/Triggers são automações do agente/serviço Manus, não conectores automáticos para o SQLAlchemy da aplicação. Para uma ingestão recorrente de produção, a opção apropriada é um worker de aplicação que chama APIs read-only diretamente, recebe apenas as chaves necessárias via secret store, valida timestamps/proveniência/licença, deduplica e grava com identificadores idempotentes. Não configurar segredos no código, em arquivos `.env` versionados, nem copiar autenticação OAuth/MCP para o container. Um worker disparado por ScheduleTask/Trigger exigiria um contrato autenticado de entrega à API de ingestão e não deve ser confundido com um stream ao vivo de baixa latência.

As capacidades e limitações de APIs estão registradas em [fontes consultadas](market_intelligence_source_notes_2026-11-02.md). Alpha Vantage expõe diferentes endpoints sujeitos a parâmetros e direitos por endpoint [1]. CoinGecko documenta rate limits variáveis por plano, rate limiting compartilhado por IP sem chave e cobrança das respostas de erro [2]; o histórico de mercado tem granularidade dependente da janela/plano [3]. A página DOC 2.0 do GDELT consultada documenta pesquisa de artigos/saída JSON, mas é material de 2017, não SLA atual [4].

## Testes e evidência

- Baseline focada, antes da alteração: `test_final_safety_gates.py`, `test_strategy_refinements.py`, `test_core_upgrade.py` e `test_upgrade_core.py`: **25 passed, 1 warning**.
- Primeira rodada focada após integração: `test_trend_alignment.py` e `test_final_safety_gates.py`: **18 passed, 1 warning**. Esse resultado antecede o teste adicional que fixa o limite mínimo de 0,70.
- Suíte integral final após o novo teste de payload inválido: **246 passed, 3 skipped, 1 warning**. Os skips são `test_database_migrations.py`, `test_model_registry.py` e `test_postgres_backup_restore.py`, todos exigindo `TEST_DATABASE_URL`; o warning é `PendingDeprecationWarning` de Starlette relacionado a `python_multipart`.
- `compileall`, scanner AST integrado (nenhum padrão suportado detectado), `uv pip check` (117 pacotes compatíveis) e `git diff --check` passaram. Scanner AST é apenas triagem, não SAST/DAST.
- O diagrama Mermaid atualizado foi renderizado para PNG **3120 × 7616** e inspecionado; o gate aparece antes de risco/submissão. CI remoto e integração ainda dependem do PR.
- Configuração efetiva verificada via `Settings(_env_file=None)`: `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, flags de autonomia/manual/autostart/neural e Ensemble de backtest `false`; shadow `true`. Nenhuma chave de provedor está presente no ambiente corrente.

## Limites remanescentes

Esta subfase não implementa o `NewsIntelligenceEngine`, `EventImpactAnalyzer`, classificação de novidade e confiabilidade, resolução de ativos, expected-vs-actual surprise, impacto cross-asset ou calendário de consenso. Não cria quatro estratégias adaptativas independentes, sizing dinâmico, slicing, participação máxima de mercado nem sinais adicionais de CVD/open interest/liquidity sweep. O fluxo existente é uma proxy de imbalance do livro; não identifica instituições. Não foi ingerido dataset licenciado, não houve validação OOS/replay histórico, Demo/Testnet, ensaio de feed outage, execução de ordem ou deployment/staging. O bloqueio financeiro continua porque ledger verificável e dados/modelos homologados ainda não existem.

`LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, `AUTONOMOUS_TRADING_ENABLED=false`, `MANUAL_TRADING_ENABLED=false`, `AUTO_START_ENGINES=false`, `NEURAL_MODELS_ENABLED=false` e `BACKTEST_USE_ENSEMBLE=false` permanecem inalterados.

## Referências

[1]: https://www.alphavantage.co/documentation/ "Alpha Vantage API Documentation"
[2]: https://docs.coingecko.com/docs/errors-and-rate-limits "CoinGecko Errors and Rate Limits"
[3]: https://docs.coingecko.com/reference/coins-id-market-chart "CoinGecko Historical Market Chart Endpoint"
[4]: https://blog.gdeltproject.org/gdelt-doc-2-0-api-debuts/ "GDELT DOC 2.0 API Overview"
