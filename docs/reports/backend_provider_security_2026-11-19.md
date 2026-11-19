# Backend: segurança de provedores e ensaio sandbox — 2026-11-19

O incremento fecha exposições concretas na fronteira credencial → provedor → cache/log/status e comprova coleta pública até análise determinística do core sem enviar ordens. A suíte local final passou com **357 passed, 4 skipped e 1 warning**. O ensaio externo validou 119 candles fechados, persistência/reimportação idempotente e decisão HOLD. Isso não é homologação de trading ou publicação de servidor.

Autor: Manus AI. Branch: `fix/backend-provider-security-nov19`. Base: master pós-squash da PR #32, `56c20252e28605e3c6568bbcd3ebbf0c3935a6a5`. A branch anterior da Fase 9 foi preservada. O escopo solicitado é backend; frontend, modelos treinados e dados financeiros de clientes não foram alterados.

## Credenciais e catálogo administrativo

`config/settings.py` mantém strings internas compatíveis com os adapters, mas 19 campos sensíveis usam `Field(repr=False, exclude=True)`, incluindo passwords, API keys, SECRET_KEY e DSNs de banco/Redis. Inputs são ocultados na representação padrão de erros de validação; nomes inválidos de provedor não são refletidos na mensagem. Isso evita dumps comuns, não implementa criptografia em memória ou um vault.

As fontes nativas Pydantic continuam com precedência argumentos > ambiente > dotenv > secret files > defaults. `_secrets_dir` é opt-in pelo construtor: não existe mount automático de /run/secrets. `.gitignore` e `.dockerignore` excluem diretórios locais de segredos e material .pem/.key, além de .env. Nenhuma credencial real foi criada, exibida ou armazenada na branch.

`core/provider_catalog.py` fornece metadados e reutiliza o catálogo de candles do coletor existente. CoinGecko continua contexto; Yahoo não vira fallback executável. `GET /integrations/catalog`, no router de mercado, exige admin e não depende de TradingManager para construir a resposta. Testes exercitam JWT real e 401/403/200. Não são retornadas keys, senhas, URLs configuradas ou contas; `configured` não significa health, entitlement ou autorização de ordens.

## Transporte HTTP, destinos e custos

`infra/provider_security.py` valida HTTPS, host, porta, caminho, ausência de userinfo/fragmento e queries não esperadas antes de notícias enviarem chaves. Hosts e paths são constantes do código, não input do frontend. O HTTP não segue redirects, inclusive quando um AsyncClient real é injetado no transporte compartilhado.

`infra/async_http.py` substitui erros públicos por códigos seguros. Status/health não guardam texto arbitrário de provedor ou request URL; logs httpx/httpcore registrados pelo módulo suprimem os detalhes da requisição. Cache keys usam HMAC com salt de instância e incorporam método e headers explícitos além dos parâmetros, para não expor chaves nem compartilhar a resposta entre credenciais distintas. Métricas de erro/retry e circuit breaker foram preservadas, e CancelledError continua propagado.

A revisão estática independente encontrou um ponto material: `trust_env=True` permitiria herdar proxies e configuração de CA. Foi corrigido nos clients próprios do transporte, coletor, smoke e Spot Testnet/Demo; um AsyncClient real injetado com herança habilitada é rejeitado. Há testes com proxy/CA dummy e arquivo CA inexistente, sem requisições privadas. Um proxy HTTPS isolado não lê o payload dentro de TLS validado; o risco inclui desvio de tráfego e cadeia de confiança injetada. Um proxy operacional legítimo precisa de configuração explícita revisada, não bypass no .env. A revisão não equivale a auditoria externa integral ou aprovação humana da PR.

`NEWS_ENABLED_KEYED_PROVIDERS=[]` evita consumo implícito somente por carregar uma chave. CoinGecko Pro exige chave e opt-in; o contexto público sem opt-in não recebe a chave. Marketaux pede no máximo três artigos nesta etapa. Alpha Vantage usa CRYPTO/FOREX no NEWS_SENTIMENT em vez de consultar BTC como ação. Planos/licenças continuam sendo verificação externa; a presença da integração não concede conteúdo Premium gratuito. O guia detalha fontes oficiais e requisitos de configuração.

## Persistência e limpeza

`NewsProcessor` move apenas dois callers leaf — notícia e tendência — para `asyncio.to_thread`, mantendo os writes sequenciais. `DatabaseManager.create_news_article` e `create_trend_snapshot` criam e fecham suas sessões por context manager dentro do worker, incluindo falha de commit. Não foi criada Session atravessando await nem alterado ledger, risco, sizing ou reserva de intenção.

`scripts/ingest_news.py` fecha HTTP e pool em finally, usa offload na criação/contagem do banco e diferencia itens processados de linhas presentes. Não afirma que `len(articles)` é o número de inserts bem-sucedidos. Total de linhas não prova persistência completa de cada lote; erros de escrita ainda exigem política operacional de recuperação.

Não se declarou concluída a Fase 9.3 ou recontado o inventário de 59 calls: faltam mapeamento interprocedural atualizado, orçamento de workers, baseline de latência e migração dos caminhos críticos de intents/fills/reconciliação. Cancelar await de to_thread não desfaz um commit iniciado; o smoke usa estado descartável, nunca uma origem financeira verificada.

## Evidência de teste

Comando integral local:

```bash
PYTHONPATH=. .venv/bin/python -m pytest -q
# 357 passed, 4 skipped, 1 warning
```

Os quatro skips locais dependem de PostgreSQL/TEST_DATABASE_URL. O warning é PendingDeprecationWarning da importação multipart pelo stack Starlette; não foi removido por upgrade indiscriminado. `uv pip check` aprovou 117 pacotes instalados, compileall e git diff --check passaram e Alembic manteve o head único `a5c74e8d2b91`. Não houve nova migration ou mudança de lock de dependências.

O CI PostgreSQL/container deste novo SHA é gate independente; consultar os checks da PR associada para o resultado vigente. CI verde da PR #32 é evidência histórica daquela base, não uma aprovação automática deste incremento.

Smoke real com egress direto e sem chave:

```bash
PYTHONPATH=. .venv/bin/python scripts/sandbox_backend_smoke.py \
  --limit 120 --output-dir /tmp/zia-public-smoke-new
```

O diretório deve ser novo/vazio. O script não usa DATABASE_URL de produção, não carrega .env, não altera os.environ, não executa código de configuração dinamicamente e não importa adapters de execução. Usa configuração mínima imutável somente para o coletor. Falha de fonte/feature resulta em attention e exit não zero, sem fabricação de dados.

Resultado salvo em [evidência pública do smoke](evidence/backend_sandbox_smoke_2026-11-19.json): BTC/USDT, 1h, 119 candles fechados, 119 rows antes e depois da reimportação, 10 features e 86 linhas válidas, igualdade com o builder canônico e uma requisição HTTP. Hash das features: `5ad14dcbcbf7e06070e39f73a540e91030fa868f33c508562c098930fed05bd4`. A leitura do core apresentou candidata buy, confiança `0.6568271480759608` e estado rejected. A confiança não atingiu o limiar operacional, e não havia livro de ofertas. A decisão final do ensaio foi HOLD, execution_authorized=false e orders_sent=0. Não houve notícia externa Premium, chamada privada à exchange, ordem Testnet ou Mainnet, treino ou promoção de modelo.

## Limites e próxima etapa segura

O backend ainda não está aprovado para atender clientes com capital real. Permanecem identidade persistente e isolamento por tenant, rotação/revogação de credenciais, auth WebSocket público sem token em query, direitos comerciais de dados, orçamento distribuído de quotas/custos e retenção. É necessário concluir o ledger autoritativo de fill/fee/funding e validar modelo/dataset fora da amostra.

A próxima execução de ordens, se selecionada em uma etapa separada, deve ser supervisionada em Testnet após os gates de reconciliação, não Mainnet. Ainda faltam soak, fault injection, integração manual frontend/backend e staging Compose/VPS com TLS, restart, PostgreSQL/Redis, restore, alertas e incident response. Nenhum servidor foi publicado. Defaults live/manual/autonomia/autostart permanecem OFF; kill switch permanece ON.

O checklist verificável e os dados/conectores necessários estão em [Backend Sandbox Guide](../BACKEND_SANDBOX_GUIDE.md). Roadmap, Findings e Infrastructure Audit foram atualizados nesta branch. Merge e publicação são decisões separadas da implementação e do ensaio de dados.
