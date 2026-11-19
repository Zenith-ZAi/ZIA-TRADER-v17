# Backend ZIA-TRADER v17 — conectores e primeiro ensaio seguro

O primeiro ensaio de dados reais já foi executado no sandbox sem conta de exchange, sem chave de API e sem ordens. O caminho testado foi Binance pública → coletor unificado → SQLite isolado → features canônicas → leitura determinística do core. Isso valida uma parte concreta do backend, não libera trading nem comprova rentabilidade.

Data: 2026-11-19. Autor: Manus AI. Escopo: backend; o frontend não foi alterado ou homologado nesta rodada.

## Dados necessários para alimentar o algoritmo

Para a leitura inicial, use símbolo e classe de ativo, timeframe, candles fechados com timestamp UTC, preços OHLC e volume, identificação do provedor e horário da coleta. O banco `market_candles` mantém a identidade por provedor, ativo, símbolo, timeframe e timestamp. A coleta não transforma automaticamente esses dados em um feed autorizado para execução nem treina os pesos dos modelos.

Para uma entrada operacional, candles sozinhos não bastam. O core precisa avaliar qualidade e atualidade do feed, spread e profundidade reais do livro, custos estimados, notícias recentes de fontes saudáveis, bloqueios de eventos, saldo reconciliado, posições e exposição. Precisa ainda de filtros oficiais de quantidade/notional, idempotência de intenção e recuperação de ordens. Um preço disponível não substitui esses contratos.

Notícias já têm persistência própria em `news_articles`; tendências usam `trend_snapshots`. Observações shadow e o ledger financeiro audit-only são camadas separadas. Não foi criado um banco de senhas. O novo catálogo de integrações contém somente metadados e nomes dos campos de configuração; segredos ficam fora das tabelas e dos payloads administrativos.

## Conectores gratuitos e opcionais

**Binance pública é o caminho recomendado para começar.** `https://data-api.binance.vision` oferece endpoints somente de dados de mercado e não requer autenticação. O ensaio usa `GET /api/v3/klines`; esse host não serve para enviar ordens ou consultar saldo privado. O backend já valida destino, símbolo, timeframe e candles fechados. [1]

O coletor de Alpha Vantage está implementado para ações e câmbio. Precisa de `ALPHA_VANTAGE_API_KEY` e do gate específico de ingestão. Uma chave gratuita não concede todo dataset: a disponibilidade de cada função, a quota e a licença precisam ser verificadas. Não se deve usar uma coleta diária limitada como substituto de cotação executável intraday. [3] [4]

GDELT e RSS são fontes de contexto já programadas em `NewsProcessor`; não têm chave configurada neste código. Nesta rodada foram testadas por mocks, não homologadas por ingestão externa contínua. Falta medir latência, cobertura e qualidade temporal para a sua estratégia. Não se fabricam manchetes quando a fonte falha.

CoinGecko é contexto cripto/tendências neste core, não OHLCV oficial da exchange. O catálogo de candles o mantém bloqueado nesse papel. O cliente de tendências diferencia header Demo e Pro pelo host allowlisted. Para enviar uma chave, é necessário habilitar `coingecko` na lista opt-in. O host Pro fica bloqueado sem esse opt-in e sem chave; isso não concede acesso Pro sem plano. Yahoo/yfinance não foi promovido a fallback de produção: `yahoo_chart` permanece bloqueado no coletor até validação de contrato e licença.

Os conectores MCP disponíveis ao agente Manus, como Alpha Vantage, CoinGecko e Supabase, são ferramentas do ambiente de desenvolvimento. Suas credenciais não são herdadas pelo processo Python do ZIA. Para alimentar um runtime do ZIA é necessário configurar a API correspondente no ambiente do próprio backend, ou importar dados com origem e licença documentadas. Nenhum banco Supabase externo foi acessado nesta rodada.

## Notícias Premium sem consumo automático ou exposição de senha

Carregar uma chave deixou de ser autorização implícita para consultar todos os provedores de notícias. `NEWS_ENABLED_KEYED_PROVIDERS` tem padrão `[]`. Habilite somente os provedores escolhidos, com acesso contratado ou gratuito confirmado. A lista não aceita nomes desconhecidos ou duplicados.

Marketaux é uma opção para o primeiro ensaio de notícias com chave: o plano Free documenta 100 requisições por dia e até 3 artigos por requisição, sem cartão. O código agora limita conservadoramente o pedido a 3 artigos, inclusive se a conta for paga. Aumentar esse teto exige uma próxima configuração vinculada ao entitlement, não assumir que a presença de uma chave autoriza volume maior. Planos pagos ampliam quota e cobertura; o serviço fornece snippets e links, não licença automática sobre o texto integral de cada jornal. [5] [6] [7]

Alpha Vantage descreve `NEWS_SENTIMENT` como função Premium. A consulta usa `function=NEWS_SENTIMENT`; para BTC o namespace foi corrigido para `CRYPTO:BTC`, e moedas usam o namespace `FOREX`. Chave gratuita geral não deve ser tratada como acesso gratuito a essa função. Para usar a função, confirme entitlement e licença da conta antes de habilitar `alpha_vantage` na lista de notícias. [3] [4]

Benzinga, Finnhub, Twelve Data, NewsAPI e CryptoPanic têm métodos no backend. Isso significa que existe código de integração, não que cada endpoint/plano foi homologado ao vivo nesta rodada. Permanecem desabilitados até opt-in e credencial válida. Redistribuir dados para clientes exige verificar direitos comerciais; pagar uma assinatura não resolve automaticamente essa obrigação. Os termos Alpha Vantage e Marketaux exigem atenção específica para uso comercial. [8] [9]

Uma configuração local mínima para testar Marketaux é:

```dotenv
# Arquivo .env local, não versionado. O valor real da chave não aparece aqui.
NEWS_ENABLED_KEYED_PROVIDERS=["marketaux"]
LIVE_TRADING_ENABLED=false
LIVE_MODE=false
LIVE_KILL_SWITCH=true
AUTONOMOUS_TRADING_ENABLED=false
MANUAL_TRADING_ENABLED=false
AUTO_START_ENGINES=false
SHADOW_MODE_ENABLED=true
```

Forneça `MARKETAUX_API_KEY` por variável de ambiente do processo ou por secret file. Não cole a chave no chat, em issue, em commit ou em URL do frontend. `Settings(_env_file=..., _secrets_dir=...)` usa as fontes nativas do Pydantic Settings: argumentos explícitos > ambiente > dotenv > secret files > defaults. `_secrets_dir` é opt-in pelo construtor; o servidor não monta nem ativa `/run/secrets` automaticamente. Uma factory de deployment que use esse diretório precisa passá-lo ao construir Settings.

Um secret file tem o nome do campo, como `MARKETAUX_API_KEY`, e contém somente seu valor. Mantenha diretório com permissão `0700`, arquivo `0600` e mount somente leitura. Os diretórios locais `secrets/` e `.secrets/`, `.env`, `.pem` e `.key` estão excluídos do Git e do contexto Docker. A exclusão é preventiva: não remove um segredo que já tenha sido comitado; nesse caso é necessário revogar/rotacionar a credencial.

Campos sensíveis não entram em `repr`, `model_dump` ou JSON normal de Settings. Isso não é criptografia em memória nem um vault multiusuário: o processo ainda precisa acessar o segredo para autenticar. Evite `vars(settings)`, dumps arbitrários, debug de memória e tracing de headers/query em infraestrutura externa.

A allowlist de notícias verifica HTTPS, host, porta e caminho antes da chamada com chave. URLs arbitrárias vindas de configuração não são aceitas; redirecionamento HTTP foi desabilitado. Logs do transporte suprimem detalhes de request, erros/health usam códigos seguros e as chaves não ficam nas chaves do cache. Headers e método participam da identidade do cache para não reutilizar uma resposta autenticada entre contextos diferentes. Os clientes HTTP gerenciados de notícias, coletor, smoke e Spot Testnet/Demo usam `trust_env=False`: não herdam proxy nem configuração de CA de variáveis do ambiente. Um AsyncClient real injetado com essa herança habilitada é rejeitado pelo transporte compartilhado. Proxy HTTPS por si só não revela conteúdo dentro de TLS verificado; o risco também envolve configuração de CA não confiável herdada do ambiente. Um proxy interno novo precisa de política de egress própria e revisão de código; não existe bypass por `.env` para essas chamadas gerenciadas.

## Como reproduzir o ensaio no sandbox

No checkout, use o virtualenv do lock:

```bash
PYTHONPATH=. .venv/bin/python scripts/sandbox_backend_smoke.py --limit 120
```

Esse comando usa um banco temporário descartável. Não lê `.env`, não altera `os.environ`, não importa o singleton de Settings e não constrói adapter de execução. Para guardar o banco e o JSON de evidência, indique um diretório novo ou vazio:

```bash
PYTHONPATH=. .venv/bin/python scripts/sandbox_backend_smoke.py \
  --limit 120 --output-dir /tmp/zia-public-smoke-new
```

O script não aceita `DATABASE_URL` arbitrária nem reaproveita banco de produção. O escopo é BTC/USDT, 1h e no máximo 500 candles. Falha de fonte ou features insuficientes resulta em `attention` e saída não zero, sem fabricar dados. Workers de banco têm sessão própria; cancelar o await não desfaz um commit já iniciado. Nenhuma intenção de ordem é criada.

A evidência desta rodada foi: 119 candles fechados, 119 linhas antes e depois da reimportação, 10 features com 86 linhas válidas e uma requisição HTTP. A leitura do core apresentou candidata `buy`, confiança `0.6568271480759608` e estado `rejected`: faltou confiança operacional e não havia livro de ofertas. A decisão do ensaio foi `HOLD`; `execution_authorized=false`; ordens enviadas: zero. O snapshot não é uma recomendação de investimento ou um resultado de rentabilidade.

O catálogo administrativo está em `GET /integrations/catalog`: 401 sem autenticação, 403 para trader sem papel admin e 200 para admin. Não retorna chave, senha, URL configurada ou identificador de conta. `configured` descreve seleção/gates/credenciais locais, não saúde da rede, entitlement, saldo reconciliado ou permissão de trading.

O próximo teste com uma exchange deve ser **Spot Testnet**, não Mainnet. A Testnet tem URLs e chaves próprias, fundos virtuais e resets periódicos. Não foi enviada ordem Testnet nesta rodada. Uma próxima etapa deve usar credenciais exclusivas da Testnet, confirmar filtros do símbolo, simular falhas/restart e reconciliar fills/fees antes de qualquer autorização live. [2]

## Checklist verificável de “backend completo”

Não atribuir um percentual genérico de produção. Para clientes ou dados financeiros reais, completar os seguintes critérios com evidência e aceite:

- [x] Manter live/autostart/autonomia bloqueados por padrão; nenhuma liberação foi feita nesta rodada.
- [x] Ter coletor unificado com identidade de dados e teste de reimportação idempotente no sandbox.
- [x] Ter autenticação e RBAC no endpoint de catálogo; testar 401, 403 e 200 sem bypass de auth.
- [x] Proteger serialização de configurações, diagnósticos HTTP/cache e destinos de notícias com chave.
- [x] Ter persistência de notícias/tendências e cleanup de sessão também em falha; migrar esses dois callsites async para worker.
- [x] Executar teste de integração de dados reais até leitura do core sem enviar ordens.
- [ ] Aprovar requisitos e contrato de API com o frontend, incluindo testes manuais de login, expiração, reconexão e erros.
- [ ] Implementar identidade persistente por cliente, isolamento por tenant, recuperação/revogação de acesso, rotação e auditoria de credenciais. O auth por ambiente atual não é uma plataforma SaaS multiusuário homologada.
- [ ] Resolver autenticação de WebSocket sem token em query de URL em ambiente público; não registrar tokens nos access logs/proxy/APM.
- [ ] Verificar entitlement e direitos comerciais de cada fonte, além de orçamento persistente de quota/custo, retenção e descarte. Cache e retry limitado não são orçamento diário distribuído.
- [ ] Completar a migração das demais chamadas ORM síncronas; não declarar concluído o inventário histórico de 59 callsites.
- [ ] Homologar reconciliação financeira autoritativa de fill, fee e funding. O ledger audit-only não alimenta sizing/risco como fonte verificada.
- [ ] Executar Testnet/shadow prolongado, fault injection, restart, recuperação de intents e teste fora da amostra com custos reais estimados.
- [ ] Executar staging Compose/VPS com PostgreSQL/TimescaleDB e Redis, TLS, health/readiness, restarts e backup/restauração reais. Teste PostgreSQL efêmero de CI não substitui restore no staging escolhido.
- [ ] Configurar métricas e alertas com responsáveis, retenção de logs sem segredos, runbook de incidentes, RPO/RTO, capacidade e custos de operação aprovados.
- [ ] Concluir review/CI e aceite do incremento atual antes de integrar a branch; publicar o servidor exige uma etapa operacional separada.

A PR #32 da Fase 9 já foi integrada por squash autorizado, preservando sua branch. Esta rodada adiciona segurança de provedores e evidência sandbox em branch separada; não reinicia etapas concluídas e não publica um serviço acessível a clientes.

## Referências

[1]: https://developers.binance.com/en/docs/products/spot/faqs/market_data_only "Binance Spot — Market Data Only URLs"
[2]: https://developers.binance.com/en/docs/products/spot/testnet/general-info "Binance Spot Testnet — General Info"
[3]: https://www.alphavantage.co/documentation/ "Alpha Vantage API Documentation — News Sentiment"
[4]: https://www.alphavantage.co/support/ "Alpha Vantage Support — API Keys and Usage Limits"
[5]: https://www.marketaux.com/documentation "Marketaux API Documentation"
[6]: https://www.marketaux.com/pricing "Marketaux Subscriptions and Quotas"
[7]: https://www.marketaux.com/faq "Marketaux Frequently Asked Questions"
[8]: https://www.alphavantage.co/terms_of_service/ "Alpha Vantage Terms of Service"
[9]: https://www.marketaux.com/tos "Marketaux Terms of Use"
