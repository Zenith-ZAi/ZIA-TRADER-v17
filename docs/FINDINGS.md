# Findings — ZIA-TRADER v17

Atualizado em 2026-10-05. Este registro contém gaps verificados que não foram alterados para preservar as restrições do prompt, além do escopo concluído nas fases abaixo. Não é uma declaração de ausência de outros defeitos.

| Arquivo/linha | Evidência observada | Correção sugerida (aguarda revisão/aprovação) |
| --- | --- | --- |
| `infra/redis_cache.py:94-105` | Se Redis não conecta na criação do objeto, `RedisCache` usa `_InMemoryFallback`, que é apenas local ao processo. Isso não é estado compartilhado entre API e worker. | Em modo de produção/autonomia, bloquear a inicialização em qualquer processo sem Redis persistente e uniformizar health checks/fail-closed em todos os serviços. Não trocar o backend de locks sem ensaios de concorrência. |
| `core/reconciliation.py:58-73, 93-97` | Cache de intenção é consultado como apoio; a tabela de intents é consultada primeiro e o fluxo depende do Redis apenas para dados transitórios/locks. | Formalizar por RFC quais campos são authoritative no PostgreSQL e quais são cache; executar testes de falha Redis/DB antes de alterar recuperação ou retry. |
| `core/manager.py:107-115`; `config/settings.py:30` | A ativação do kill switch atualiza a configuração do objeto em memória e registra evento persistente; não há evidência nesta fase de leitura de um estado único compartilhado após restart/entre processos. | Definir e revisar armazenamento atômico durável do estado do kill switch, carregamento no startup e consistência com cada adapter; manter fail-closed e cobrir restart/falhas antes de mudar código. |
| `docs/DATABASE_OPERATIONS.md` (TimescaleDB) | Hypertable opcional está implementada apenas para `market_candles`, desativada por padrão; a extensão não está disponível no serviço PostgreSQL padrão do Compose. | Validar em instância TimescaleDB de teste, medindo migração, constraint de candle e downgrade/restore antes de ativar a flag. |
| PostgreSQL/ambiente externo | A sandbox local não tem serviço PostgreSQL nem VPS/exchange; validação PostgreSQL é definida no CI, ainda depende da execução remota dos novos checks. | Aguardar CI verde e, antes de deploy, ensaiar backup/restore e migrações em ambiente isolado semelhante à VPS. |

Nenhuma lógica de sinais, cálculo de risco, envio de ordem, idempotência ou reconciliação foi alterada neste refinamento. Não foi feita conexão a broker/exchange, teste de mainnet ou execução de ordem real.


## Fase 2 — ingestão e integridade de feeds (2026-10-05)

- **Corrigido:** `MultiTimeframeFeed` agora valida OHLCV, ordenação, duplicatas, timestamps futuros, gaps em sessão e staleness antes de devolver o histórico. Histórico primário inválido segue o `FeedUnavailable` existente e não chega ao restante do ciclo de análise.
- **Corrigido:** eventos ativos/resolvidos são registrados em `data_gaps`; snapshots de order book com depth real são persistidos com intervalo mínimo e retenção configuráveis.
- **Observabilidade:** snapshots expõem idade, cobertura, cadência e contagem de gaps em `data_quality`; erros de timeframe secundário continuam explícitos.
- **Limitação mantida:** não foi conectado calendário oficial de feriados/DST para B3/Forex. Gaps históricos entre sessões não são inferidos; staleness do último candle é o controle fail-closed para parada atual do feed.
- **Limite de escopo:** adapters de ordens, engine de decisão/sinais, cálculo de risco, sizing, kill switch, idempotência e reconciliação não foram editados.
