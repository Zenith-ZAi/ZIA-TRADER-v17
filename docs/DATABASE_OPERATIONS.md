# Operação do banco de dados

## Escopo e segurança

O schema é versionado com Alembic. Em PostgreSQL, os processos da aplicação executam `alembic upgrade head` durante a inicialização; a migração usa advisory lock de sessão para serializar API e worker quando sobem juntos. `create_all` permanece somente para SQLite em desenvolvimento/testes. SQLite em `ENVIRONMENT=production` falha fechado. A execução de migrações não altera flags de trading nem promove modelos.

A revisão inicial `8d429f0ec081` foi gerada por autogenerate a partir do metadata SQLAlchemy atual, incluindo as tabelas do Admin CLI, e revisada manualmente. Ela cria tabelas/índices ausentes sem recriar objetos presentes, para permitir adoção do schema legado criado por `create_all`. Ela não altera colunas já existentes; antes de atualizar banco legado, faça backup e valide o resultado com `alembic check`.

## Inicialização/migração

```bash
# PostgreSQL: use a mesma URL usada pela aplicação, sem colocá-la em logs ou commits.
export DATABASE_URL='postgresql+psycopg2://<usuario>:<senha>@<host>:5432/<banco>'
python -m alembic upgrade head
python -m alembic check

# Desenvolvimento local/testes SQLite: a compatibilidade create_all continua ativa.
ENVIRONMENT=development DATABASE_URL=sqlite:///./data/zia_trader.db python -m pytest -q
```

O comando de downgrade remove dados das tabelas migradas. Execute-o somente em banco descartável ou após backup. Em banco existente, primeiro gere e valide um backup, aplique a migração e compare contagens/objetos antes de habilitar workers.

## Pool PostgreSQL

Configure por ambiente (valores ilustrativos):

| Variável | Padrão | Descrição |
| --- | ---: | --- |
| `DB_POOL_SIZE` | `5` | conexões mantidas no pool |
| `DB_MAX_OVERFLOW` | `10` | conexões temporárias adicionais |
| `DB_POOL_TIMEOUT_SECONDS` | `30` | espera máxima por conexão |
| `DB_POOL_RECYCLE_SECONDS` | `1800` | reciclagem de conexão |

`pool_pre_ping` permanece habilitado. SQLite não recebe parâmetros de pool PostgreSQL.

## Backup e restauração

Instale `pg_dump`, `pg_restore` e `sha256sum`. Os comandos recebem a URL por ambiente e não exibem credenciais:

```bash
export DATABASE_URL='postgresql+psycopg2://<usuario>:<senha>@<host>:5432/<banco>'
export BACKUP_DIR=/var/backups/zia
export BACKUP_RETENTION_DAYS=14
scripts/db_backup.sh

# Restaure inicialmente em um banco isolado. O destino é substituído para objetos com os mesmos nomes.
export DATABASE_URL='postgresql+psycopg2://<usuario>:<senha>@<host>:5432/<banco-de-teste>'
scripts/db_restore.sh /var/backups/zia/zia-<timestamp>.dump
```

O arquivo é formato custom do `pg_dump`, com checksum SHA-256 e retenção definida por `BACKUP_RETENTION_DAYS`. Nunca teste restauração diretamente no banco produtivo. A integração CI executa dump/restore para um banco PostgreSQL temporário e compara contagens e checksums ordenados das tabelas públicas.

## Tabelas temporais e TimescaleDB

O schema inclui `market_candles` com chave primária composta (`symbol`, `timeframe`, `timestamp`), que impede candles duplicados. Há índices compostos para candles, snapshots de decisão, ordens, fills e observações. A migração pode converter `market_candles` em hypertable somente quando `ENABLE_TIMESCALEDB_HYPERTABLES=true` e a extensão TimescaleDB estiver instalada e autorizada. O padrão é `false`; o Compose atual usa PostgreSQL sem TimescaleDB. A conversão e o desempenho em Timescale ainda não foram verificados neste ambiente.

## Redis e fonte de verdade

`order_intents` no PostgreSQL é a persistência durável da intenção de ordem; Redis é usado pelo código como cache/coordenação/lock, não como substituto da tabela. Em produção, mantenha `REQUIRE_PERSISTENT_REDIS=true`, conforme `.env.vps.example`; o worker já interrompe a inicialização se só houver fallback em memória. O fallback em memória é local ao processo e não compartilha estado entre API e worker.

**Limite não resolvido nesta fase:** kill switch tem flag/configuração em memória e eventos persistidos no banco, mas não foi convertido em um estado único compartilhado com Redis/PostgreSQL. Não alterei o comportamento, os locks, a idempotência ou o fluxo de reconciliação por serem invariantes protegidos pelo prompt. Consulte `docs/FINDINGS.md` antes de considerar esta arquitetura pronta para autonomia.


## Qualidade de feeds e histórico do livro

A Fase 2 adiciona `assess_ohlcv_quality` no caminho comum de `MultiTimeframeFeed`. Cada timeframe é verificado quanto a OHLCV vazio/inválido, timestamps futuros, ordenação, duplicatas, cadência/gaps e idade da última barra. `FEED_STALENESS_MULTIPLIER` (padrão `3.0`) define o limite como múltiplo do timeframe. A qualidade por timeframe é exposta em `MarketSnapshot.to_dict()` no campo `data_quality`; incidentes ficam em `data_gaps`, com estados `open`/`resolved` e deduplicação por tipo/início.

Um histórico primário inválido ou stale levanta `FeedUnavailable` antes de cotação e análise; o tratamento já existente do engine pula o ciclo do símbolo. Problemas em timeframes secundários são registrados em `errors` e não substituem o histórico primário. Não foram alterados critérios de sinal, sizing, risco, ordens, kill switch ou reconciliação.

Crypto é tratado como mercado 24/7. Em B3 e Forex, gaps só são inferidos dentro da mesma sessão/dia, para não confundir fechamento e fim de semana com falta de candles. **Não há calendário oficial de feriados nem tratamento completo de DST** nesta versão; a idade do último candle continua sendo o bloqueio conservador para feed parado.

Se um histórico Forex não fornecer a coluna/valores de volume, os valores ausentes são normalizados para zero (não se estima volume), e `data_quality.volume_missing_rows_filled_zero` informa quantas barras foram afetadas. Valores de volume não nulos que não sejam numéricos continuam sendo rejeitados.

`order_book_snapshots` guarda depth somente quando o feed usa CCXT ou Binance em `testnet`/`demo`, e apenas quando bids e asks têm conteúdo. Books sintéticos, paper e read-only sem profundidade não são persistidos. `ORDER_BOOK_HISTORY_INTERVAL_SECONDS` (60 s) limita a frequência e `ORDER_BOOK_HISTORY_RETENTION_DAYS` (7 dias; o código aceita 1–365) remove registros expirados durante cada gravação. A revisão `b7d2d043ee8a` é aditiva e o backup PostgreSQL inclui a tabela automaticamente.
