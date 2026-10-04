# Findings — ZIA-TRADER v17

Atualizado em 2026-10-04. Este registro contém gaps verificados que não foram alterados para preservar as restrições do prompt (sinais, risco, gates, kill switch, idempotência, reconciliação e execução). Não é uma declaração de ausência de outros defeitos.

| Arquivo/linha | Evidência observada | Correção sugerida (aguarda revisão/aprovação) |
| --- | --- | --- |
| `infra/redis_cache.py:94-105` | Se Redis não conecta na criação do objeto, `RedisCache` usa `_InMemoryFallback`, que é apenas local ao processo. Isso não é estado compartilhado entre API e worker. | Em modo de produção/autonomia, bloquear a inicialização em qualquer processo sem Redis persistente e uniformizar health checks/fail-closed em todos os serviços. Não trocar o backend de locks sem ensaios de concorrência. |
| `core/reconciliation.py:58-73, 93-97` | Cache de intenção é consultado como apoio; a tabela de intents é consultada primeiro e o fluxo depende do Redis apenas para dados transitórios/locks. | Formalizar por RFC quais campos são authoritative no PostgreSQL e quais são cache; executar testes de falha Redis/DB antes de alterar recuperação ou retry. |
| `core/manager.py:107-115`; `config/settings.py:30` | A ativação do kill switch atualiza a configuração do objeto em memória e registra evento persistente; não há evidência nesta fase de leitura de um estado único compartilhado após restart/entre processos. | Definir e revisar armazenamento atômico durável do estado do kill switch, carregamento no startup e consistência com cada adapter; manter fail-closed e cobrir restart/falhas antes de mudar código. |
| `docs/DATABASE_OPERATIONS.md` (TimescaleDB) | Hypertable opcional está implementada apenas para `market_candles`, desativada por padrão; a extensão não está disponível no serviço PostgreSQL padrão do Compose. | Validar em instância TimescaleDB de teste, medindo migração, constraint de candle e downgrade/restore antes de ativar a flag. |
| PostgreSQL/ambiente externo | A sandbox local não tem serviço PostgreSQL nem VPS/exchange; validação PostgreSQL é definida no CI, ainda depende da execução remota dos novos checks. | Aguardar CI verde e, antes de deploy, ensaiar backup/restore e migrações em ambiente isolado semelhante à VPS. |

Nenhuma lógica de sinais, cálculo de risco, envio de ordem, idempotência ou reconciliação foi alterada neste refinamento. Não foi feita conexão a broker/exchange, teste de mainnet ou execução de ordem real.
