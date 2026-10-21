# Runbook de preparação e migração para VPS

**Projeto:** ZIA-TRADER-v17
**Objetivo:** executar um mês de backtesting multiativo com banco persistente, alimentar observações de aprendizado e operar inicialmente somente em histórico, shadow, paper, Demo ou Testnet.
**Regra principal:** este runbook não habilita mainnet nem trading com capital real.

## 1. Arquitetura recomendada

O VPS deve executar o projeto em Docker Compose com quatro camadas isoladas. PostgreSQL guarda o estado operacional, intents, reconciliação, proteções, observações e registros de backtest. Redis fornece estado/cache persistente com AOF e senha. A API fica separada do worker e exposta inicialmente apenas em `127.0.0.1`; um proxy reverso com TLS pode ser adicionado depois. Os jobs de coleta, backtesting e notícias são one-shot e entram pelo perfil `jobs`, não pelo loop principal.

| Serviço | Função | Exposição | Persistência |
|---|---|---|---|
| `db` | PostgreSQL 16 para estado e auditoria | somente rede interna | volume `postgres_data` |
| `redis` | cache/estado com AOF | somente rede interna | volume `redis_data` |
| `api` | FastAPI, health, métricas e controle | localhost inicialmente | `app_data`, `app_models`, `app_logs` |
| `worker` | análise contínua e reconciliação | nenhuma | mesmos volumes de aplicação |
| `monthly-backtest` | coleta pública e backtest histórico | job one-shot | datasets e resultados em `app_data` |
| `news-ingest` | ingestão opcional de notícias/tendências | job one-shot | artigos e snapshots no PostgreSQL |

A rede externa necessária para o primeiro mês é somente leitura: OHLCV público e, caso o operador configure chaves próprias, provedores de notícias. Nenhuma chave de trading é necessária para o backtesting. O endpoint de saúde da API não deve ser publicado diretamente na Internet sem TLS, autenticação adequada e controles no proxy.

## 2. Fases de operação

| Fase | Configuração | O que medir | Critério de passagem |
|---|---|---|---|
| Sandbox | `BINANCE_MODE=simulated`, `SHADOW_MODE_ENABLED=true`, todas as flags live false | testes, integridade, latência local, reconciliação fake | suíte verde e preflight aprovado |
| Histórico no VPS | banco PostgreSQL, Redis persistente, `monthly-backtest` para 31 dias e múltiplos ativos | PnL, drawdown, trades, taxas, slippage/fricção, cobertura, gaps de candles, hash do dataset | relatório reproduzível; nenhuma promoção automática |
| Shadow/paper | worker ativo sem envio ou com simulador; notícias e tendências opcionais | divergência entre sinal, modelo, risco e execução simulada; saúde Redis/DB; reinícios | período prolongado sem perda de estado e sem ordens inesperadas |
| Demo/Testnet | `BINANCE_MODE=demo` ou `testnet`, apenas chaves dedicadas de sandbox | fills, rejeições, rate limits, OCO, reconciliação e kill switch | testes manuais e automatizados de incidente aprovados |
| Capital real | fora deste escopo | auditoria independente, permissões mínimas, capital e limites aprovados | somente após aprovação humana explícita e mudança controlada de configuração |

O aprendizado deve ser **observacional e controlado**. O replay histórico pode criar observações causais e rótulos somente quando houver candles futuros suficientes. Um modelo candidato deve permanecer separado de `models/production` até que suas métricas OOS, estabilidade por ativo/regime, custos, drawdown e qualidade dos dados sejam revisados. O resultado de um mês não prova robustez para outro regime de mercado.

## 3. Preparação do servidor

No VPS, instale Docker Engine e o plugin Compose por procedimento oficial do provedor escolhido. Crie um usuário de deploy sem uso cotidiano de root, habilite SSH por chave, desabilite login root e senha, aplique atualizações do sistema e configure firewall. Libere somente SSH a partir de faixa confiável e HTTP/HTTPS no proxy reverso; **não libere publicamente as portas 8000, 5432 ou 6379**.

Clone a branch publicada e crie o ambiente privado:

```bash
git clone https://github.com/Zenith-ZAi/ZIA-TRADER-v17.git
cd ZIA-TRADER-v17
cp .env.vps.example .env.vps
chmod 600 .env.vps
```

Gere valores privados fora do Git, por exemplo com `openssl rand -hex 32`, e substitua `POSTGRES_PASSWORD`, `REDIS_PASSWORD`, `AUTH_PASSWORD` e `SECRET_KEY`. Não reutilize credenciais que tenham sido expostas em arquivos antigos. Chaves de Binance, se necessárias para Demo/Testnet, devem ser criadas com permissões mínimas e sem saque; para o primeiro backtest, deixe-as vazias.

## 4. Subida inicial e preflight

Suba primeiro somente os serviços de persistência e valide o schema e os volumes:

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml up -d db redis
docker compose --env-file .env.vps -f docker-compose.vps.yml run --rm db-init
docker compose --env-file .env.vps -f docker-compose.vps.yml run --rm --no-deps api python scripts/vps_preflight.py --strict
docker compose --env-file .env.vps -f docker-compose.vps.yml up -d api worker
curl --fail http://127.0.0.1:8000/healthz
```

O serviço `db-init` executa `alembic upgrade head`; API e worker só são iniciados depois de sua conclusão. O preflight, com `REQUIRE_ALEMBIC_HEAD=true`, verifica a revisão atual contra o head versionado e **não cria schema** durante a checagem. Também bloqueia flags live/autonomia/manual ativas, PostgreSQL/Redis indisponíveis, tabelas mínimas ausentes, persistência não confirmada ou diretórios não graváveis. O caminho PostgreSQL de `DatabaseManager.create_tables()` também delega ao Alembic e serializa upgrades com advisory lock; SQLite/create_all permanece restrito a desenvolvimento/testes locais.

## 5. Backtesting de um mês

Execute o job one-shot com o perfil `jobs`. O comando baixa candles fechados do endpoint público, pagina em lotes, remove duplicatas, calcula SHA-256, aplica fricção configurada, executa o backtest sem olhar o futuro e grava cada resultado na tabela `backtest_runs`:

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml --profile jobs run --rm monthly-backtest
```

Para uma janela reprodutível, use datas UTC explícitas no runner:

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml --profile jobs run --rm monthly-backtest \
  python -m scripts.run_monthly_backtest \
  --symbols BTCUSDT,ETHUSDT,SOLUSDT,BNBUSDT,XRPUSDT \
  --interval 1h --days 31 \
  --start-date 2026-07-01T00:00:00Z \
  --end-date 2026-08-01T00:00:00Z \
  --data-dir /app/data/monthly_backtest \
  --output /app/data/monthly_backtest_result.json
```

A janela acima é apenas um exemplo de forma de execução; datas e ativos devem ser definidos pelo operador conforme o objetivo do experimento. Registre o intervalo, timezone, dataset, hash, versão do commit, configuração de fricção, taxas, quantidade de operações, drawdown e falhas de coleta. OHLCV não contém histórico completo de bid/ask, profundidade, latência ou slippage realizado; portanto essas dimensões devem ser marcadas como não observadas ou aproximadas por fricção explícita, nunca inventadas.

## 6. Aprendizado e replay

Após o backtest, o replay causal pode gerar observações históricas no PostgreSQL:

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml run --rm --no-deps api \
  python scripts/run_learning_replay.py \
  --symbol BTC/USDT --interval 1h --limit 744
```

O serviço `api` já recebe `DATABASE_URL` pelo Compose; não coloque senhas na linha de comando em um shell compartilhado. O exemplo serve para explicar o fluxo; em operação use a variável de ambiente já injetada no serviço e uma conta PostgreSQL com menor privilégio. O treinamento OOS deve apontar para uma cópia versionada do CSV, salvar o candidato em diretório separado e exigir revisão humana antes de alterar `ENSEMBLE_MODEL_DIR`:

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml run --rm --no-deps api \
  python -m learning.training_pipeline /app/data/monthly_backtest/btcusdt_1h.csv \
  --model-dir /app/models/candidates/$(date -u +%Y%m%dT%H%M%SZ)
```

O resultado de teste negativo ou instável deve permanecer como evidência de validação, sem promoção. Não se deve treinar ou ativar Transformer/LSTM automaticamente no loop do worker.

## 7. Notícias e fontes auxiliares

A ingestão de notícias/tendências é opcional e deve ser executada como job separado, com limites, cache, timeout, health dos provedores e persistência do horário de coleta. Chaves devem ser fornecidas somente por `.env.vps` ou secret manager. Falha de provedor não deve ser convertida em sentimento neutro quando a política de entrada exige fail-closed; a saúde da fonte precisa aparecer no relatório.

```bash
docker compose --env-file .env.vps -f docker-compose.vps.yml --profile jobs run --rm news-ingest
```

## 8. Backup, restauração e observabilidade

Execute backup periódico com permissões restritas:

```bash
chmod +x scripts/vps_backup.sh
COMPOSE_FILE=docker-compose.vps.yml ENV_FILE=.env.vps BACKUP_ROOT=/srv/zia-backups ./scripts/vps_backup.sh
```

O script salva `pg_dump`, solicitação de snapshot Redis, dados e modelos montados, além de checksum do dump. Ele não copia `.env` e não deve ser considerado suficiente até que a restauração seja ensaiada em outro projeto/volume. Agende uma restauração mensal em ambiente isolado; valide contagem de tabelas, intents, backtests, observações, arquivos e checksum antes de confiar no backup.

Colete logs da API e do worker, `/healthz`, `/status` autenticado e `/metrics` atrás de uma camada de acesso controlado. Crie alertas para processo reiniciando, Redis em fallback de memória, banco indisponível, reconciliação em `attention`/`error`, crescimento anormal de intents pendentes, perda de dados e ativação de kill switch. Não envie tokens, URLs com senha ou payloads de credenciais para logs.

## 9. Critérios antes de qualquer saldo controlado

Antes de qualquer operação com saldo, mantenha pelo menos: um ciclo histórico reprodutível; um período de shadow/paper sem perda de estado; teste de reinício de API, worker, PostgreSQL e Redis; reconciliação após queda de rede; duplicidade de `clientOrderId`; proteção OCO/fallback; cancelamento pelo kill switch; limites de perda diária/semanal/mensal; testes de rate limit; backup e restauração; e revisão dos logs por uma pessoa responsável.

Mesmo depois desses critérios, o saldo deve ser mínimo, as chaves devem negar saque, as permissões devem ser limitadas ao produto necessário, a autonomia deve continuar desligada até aprovação explícita e o operador deve conseguir interromper todos os processos. Perder e ganhar em um mês de dados faz parte da medição do sistema; não é prova de que o algoritmo aprendeu uma regra transferível ao mercado ao vivo.

## 10. Alternativas de hospedagem

| Abordagem | Tradeoffs | Custo | Complexidade |
|---|---|---:|---:|
| VPS Docker solicitado | Controle de sistema, volumes, cron, firewall e recursos acima do Sandbox; exige hardening, backup, TLS e manutenção do operador. | Conforme provedor e tamanho escolhido | Média/alta |
| Hospedagem gerenciada persistente | Menos manutenção de SO e TLS; limites de CPU/RAM, customização e execução de componentes pesados podem impedir o backtest mensal e o stack Docker atual. | Conforme plano/uso | Baixa/média |
| Máquina local sempre ligada | Sem novo custo de servidor e adequada para dados sensíveis; depende de energia, rede, IP, disponibilidade e não é um ambiente independente. | Custo marginal de operação | Média |

Para o workload descrito, o VPS é uma escolha coerente porque o projeto já usa Docker, Python científico, PostgreSQL/Redis, jobs e volumes persistentes. A recomendação é começar com recursos moderados e medir CPU, RAM, I/O, tempo de coleta e duração do backtest antes de aumentar o plano; não é necessário GPU para o fluxo Ensemble/OOS descrito.

## 11. Validação pré-VPS (atualizada em 2026-10-21)

Nesta rodada, `docker`/Compose/Podman não estavam instalados no Sandbox. Os dois arquivos Compose passaram por leitura YAML estática e por asserts de contrato: `db-init` usa `alembic upgrade head`, flags live/autostart permanecem false, API está vinculada a loopback e API/worker usam filesystem somente leitura e `cap_drop`. Isso não é equivalente a `docker compose config`, build ou smoke real; a execução no VPS/runner Docker continua obrigatória. Consulte `docs/INFRASTRUCTURE_AUDIT.md`.

A suíte local desta revisão terminou com **189 passed, 3 skipped, 1 warning**; `compileall` e `git diff --check` passaram. `uv pip check` terminou com exit 1 por incompatibilidade de plataforma em `nvidia-cusparselt-cu13`. Um experimento histórico de backtest de 31 dias BTCUSDT/1h, 743 barras, persistido em SQLite temporário e com zero trades continua registrado como fluxo técnico de uma rodada anterior; ele não é dataset de procedência validada, evidência OOS nem indicação de retorno. Nenhum treino, promoção de modelo, conexão a exchange, deploy VPS ou ordem real foi executado nesta avaliação.
