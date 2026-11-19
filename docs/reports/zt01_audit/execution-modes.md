# Auditoria read-only — Gates de Live, automático e manual

**Checkout auditado:** `/home/ubuntu/ZIA-TRADER-v17-phase9-resume` (base PR33, head `09ea8c8`)

**Escopo:** flags `LIVE_*`, `MANUAL_TRADING_ENABLED`, `AUTONOMOUS_TRADING_ENABLED`, `AUTO_START_ENGINES`, `ORDER_MANAGER_MODE`, `SNIPER_ENABLED`; autorização, menu/API/config/worker, alternância em memória, divergência entre status e autorização e risco de reativação/restart.

**Método e limites:** leitura estática e testes unitários mockados, sem browser, sem credenciais e sem adapter de trading real. O caminho de dados públicos/shadow permanece fora de uma autorização de ordens. O checkout não foi alterado; `git status --short` permaneceu limpo. Foram executados com o virtualenv local: `38 passed, 1 warning` em `tests/test_execution_live_authorization.py`, `tests/test_final_safety_gates.py` e `tests/test_startup_validation.py`.

## Conclusão executiva

Os defaults consolidados continuam fail-closed para live: `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, autonomia/manual/autostart desligados e shadow ligado (`config/settings.py:36-44`; `docs/BACKEND_SANDBOX_GUIDE.md:39-49`). A autorização de uma ordem em adapter transacional exige os três gates globais (`execution/live_authorization.py:42-50`) e o `OrderManager` ainda exige modo, flag de origem e reconciliação (`execution/order_manager.py:79-112`, `execution/order_manager.py:195-207`, `execution/order_manager.py:259-265`).

O problema material é a fragmentação: o status não é a mesma avaliação usada para autorizar, a autonomia não compartilha o requisito de Redis persistente em todos os motores, e nem todo método de escrita passa por um último gate. O maior risco de reativação está em restart/autostart fora de produção, não no estado atual consolidado.

## Achados materiais

### 1. Status/controle não representa a autorização efetiva nem a alternância parcial

**Evidência.** `TradingManager.runtime_status()` expõe autonomia, shadow, adapter/modo e modo do `OrderManager`, mas não expõe `LIVE_KILL_SWITCH`, `LIVE_TRADING_ENABLED`, `LIVE_MODE`, `MANUAL_TRADING_ENABLED` ou `AUTO_START_ENGINES` (`core/manager.py:94-113`). O health compartilhado pelos endpoints `/healthz` e `/health` retorna literalmente `"live_trading_enabled": False` e `"live_mode": False`, independentemente do objeto `settings` (`api/runtime_services.py:58-99`; `api/routers/health.py:16-25`). Já a decisão real lê os três valores de `settings` em cada submissão live (`execution/live_authorization.py:42-50`).

O menu também apresenta uma operação que só altera `settings.LIVE_MODE` no processo corrente, depois de verificar `LIVE_TRADING_ENABLED`; não altera kill switch, manual, autonomia, autostart nem configuração persistente (`cli/runtime_menu.py:124-134`). O reload autenticado não é um reload dos gates: chama o registro de perfil e atualiza apenas modo do `OrderManager`, símbolos/timeframe e parâmetros de estratégia (`api/routers/engines.py:21-32`; `core/manager.py:87-92`; `core/runtime_registry.py:69-93`).

**Impacto verificável.** Um operador pode observar health/status como live falso mesmo com uma combinação em memória que satisfaz a autorização, e não consegue distinguir pelo status se manual ou autostart estão ligados. O toggle do menu pode anunciar `LIVE_MODE=true`, mas o envio continuar bloqueado por `LIVE_KILL_SWITCH`; a superfície administrativa não mostra esse motivo.

**Correção recomendada neste achado.** Produzir um único snapshot de gate, usado tanto por `runtime_status`/health como pelo `OrderManager`, contendo os cinco flags, adapter efetivo, `requires_live_authorization`, `authorization_reason`, modo manual/auto, estado do kill switch e saúde/persistência do Redis. Remover os dois literais `False` do health; manter a mudança somente diagnóstica inicialmente.

### 2. O requisito `REDIS_REQUIRED_FOR_AUTONOMOUS` é calculado uma vez no engine principal e não é aplicado no Sniper/OrderManager

**Evidência.** O engine principal calcula `self.autonomy_blocked` apenas no construtor, com base em autonomia e Redis persistente (`core/engine.py:67-76`). `refresh_runtime_config()` apenas atualiza símbolos e timeframe (`core/engine.py:186-189`), mas a entrada posterior usa o valor potencialmente obsoleto em `not self.autonomy_blocked` (`core/engine.py:693-704`). Assim, iniciar com autonomia desligada e ligá-la em memória não reavalia a exigência de Redis.

O Sniper autoriza o evento confirmado com `AUTONOMOUS_TRADING_ENABLED` e os demais sinais, mas não consulta `autonomy_blocked`, `REDIS_REQUIRED_FOR_AUTONOMOUS` nem `redis_cache.is_persistent` (`core/sniper_engine.py:237-251`). O `OrderManager` valida apenas que a autonomia está ligada para origem `ai` e para saída automática (`execution/order_manager.py:79-96`, `execution/order_manager.py:220-229`). A exigência configurável permanece true por default (`config/settings.py:140`).

**Impacto verificável.** Com Redis não persistente, o engine principal pode aceitar uma habilitação de autonomia feita depois de sua construção; o Sniper não tem essa barreira nem quando começa já habilitado. Se os três gates live estiverem autorizados, isso pode alcançar o caminho de submissão; em adapter simulado o efeito fica restrito à simulação, mas o contrato de autonomia está inconsistente entre os motores.

**Correção recomendada neste achado.** Reavaliar esse requisito no instante da submissão, em um gate compartilhado por entrada, saída e Sniper, além de recalculá-lo no reload. O bloqueio deve ocorrer antes de `place_order`, sem depender de estado calculado no construtor.

### 3. Proteção pós-fill não tem o mesmo último gate de live/kill switch

**Evidência.** O contrato do módulo declara que adapters transacionais devem consultar `live_submission_block_reason` imediatamente antes do efeito externo (`execution/live_authorization.py:1-4`). Porém `MarketConnector.place_protection_order()` delega diretamente ao adapter (`execution/market_connector.py:497-503`), e o `OCOManager` prefere esse método nativo quando anexa proteção (`execution/oco_manager.py:35-45`, `execution/oco_manager.py:47-76`).

`BinanceMainnetAdapter.place_order()` verifica autorização global e kill switch (`execution/mainnet_adapter.py:62-80`), mas a classe só sobrescreve `place_order`; o método herdado `BinanceSpotAdapter.place_protection_order()` monta e envia um `POST /v3/order` sem essa verificação (`execution/mainnet_adapter.py:17-18`, `execution/binance_adapter.py:434-460`). O `ExecutionEngine` chama o OCO depois de um fill (`execution/execution_engine.py:191-204`), portanto uma mudança do kill switch entre o envio da entrada e a proteção não é reavaliada nesse segundo efeito externo.

**Impacto verificável.** O kill switch é forte para a entrada normal, mas não é uma garantia uniforme para cada escrita do adapter. Um mock do adapter mainnet pode demonstrar que `place_protection_order()` ainda alcança o método de transporte quando a entrada de `place_order()` seria bloqueada. A política de proteção/redução precisa ser explícita: bloquear tudo no kill switch ou permitir somente proteção `reduce_only` sob um gate específico, nunca por omissão.

**Correção recomendada neste achado.** Centralizar o último gate em todos os métodos de escrita (`place_order`, proteção/OCO e saídas), com um tipo de operação explícito (`entry`, `exit`, `reduce_only_protection`). Para o primeiro incremento, o comportamento mais reversível é bloquear por padrão e registrar a razão; uma permissão de proteção durante kill switch só deve existir com teste dedicado de redução de exposição.

### 4. Restart e autostart não têm um estado durável de “armado”; a contenção forte depende do ambiente

**Evidência.** Os campos de flags são reconstruídos a partir de variáveis de ambiente/defaults no processo (`config/settings.py:30-44`, `config/settings.py:396-408`). A validação de flags perigosas retorna imediatamente sem impor restrições quando o ambiente não é `production`, `prod` ou `staging` (`config/startup_validation.py:19-23`); as restrições que mantêm flags false e kill switch true só são avaliadas a partir dali (`config/startup_validation.py:43-73`).

Em API, `AUTO_START_ENGINES=true` inicia o motor principal e, se habilitado, o Sniper depois da reconciliação (`api/application.py:59-85`). No worker, a mesma flag cria as tasks dos motores (`worker.py:35-49`). O helper de start verifica conexão/reconciliação e apenas bloqueia Sniper quando `SNIPER_ENABLED=false`; não há uma etapa de “armar execução” (`api/runtime_services.py:129-153`). Além disso, `BINANCE_MODE=live` seleciona o adapter mainnet na construção do connector (`execution/exchange_connector.py:155-168`).

**Impacto verificável.** No estado atual documentado, nenhuma reativação ocorre: os defaults estão desligados e os testes de startup confirmam o fail-closed em produção (`tests/test_startup_validation.py:56-71`). Mas, em `development`, um restart com ambiente contendo `AUTO_START_ENGINES=true`, `BINANCE_MODE=live`, live flags autorizadas, shadow false e autonomia true pode construir o mainnet e iniciar os loops automaticamente; a validação não impede esse cenário. Em produção/staging a validação rejeita a combinação, mas essa proteção não é universal para cada processo/configuração.

**Correção recomendada neste achado.** Separar “motor iniciado” de “execução armada”: em todo restart, iniciar no máximo observabilidade/shadow, manter kill switch ativo e exigir um rearm explícito após reconciliação e health dos providers. O rearm deve ser somente em memória, auditável e invalidado no próximo restart; `AUTO_START_ENGINES` nunca deve, sozinho, armar live.

## Matriz binária de flags e efeito esperado

| Cenário | `LIVE_KILL_SWITCH` | `LIVE_TRADING_ENABLED` | `LIVE_MODE` | `MANUAL_TRADING_ENABLED` / `ORDER_MANAGER_MODE` | `AUTONOMOUS_TRADING_ENABLED` / modo | `AUTO_START_ENGINES` | Efeito esperado |
|---|---:|---:|---:|---|---|---:|---|
| Sandbox seguro consolidado | `true` | `false` | `false` | `false` / `manual` | `false` / qualquer | `false` | Nenhuma ordem; worker verifica infraestrutura/reconciliação e não cria engines. |
| Shadow/observabilidade | `true` | `false` | `false` | `false` / `manual` | `false` / `auto` | `true` | Engines podem analisar e registrar shadow após reconciliação; nenhuma entrada manual/IA autorizada. |
| Manual simulado/Testnet | `true` | `false` | `false` | `true` / `manual` | `false` / `manual` | `false` | Pode enviar somente ao adapter explicitamente simulado/testnet, com confirmação e reconciliação; não é autorização mainnet. |
| Manual transacional live | `false` | `true` | `true` | `true` / `manual` | `false` / `manual` | `false` | Só então a etapa live global pode passar; ainda exige adapter live válido, reconciliação, saldo, risco e confirmação. Em produção, a validação de startup atual rejeita essa configuração. |
| Autônomo transacional live | `false` | `true` | `true` | `false` / `auto` | `true` / `auto` | `false` ou start explicitamente armado | Deve exigir shadow false, Redis persistente quando `REDIS_REQUIRED_FOR_AUTONOMOUS=true`, todos os gates de sinal/risco e rearm pós-restart. |
| Qualquer cenário com `LIVE_KILL_SWITCH=true` em adapter live | `true` | qualquer | qualquer | qualquer | qualquer | qualquer | Entrada live deve ser bloqueada e o status deve mostrar razão; proteção/redução deve seguir política explícita, sem bypass. |

A matriz distingue autorização de execução do simples estado de task: `AUTO_START_ENGINES=true` inicia loops, mas não deve ser reportado como autorização live nem substituir o rearm.

## Incremento reversível de maior impacto

Implementar primeiro um **gate efetivo central somente em memória**, sem alterar defaults nem o menu atual: uma função recebe `settings`, adapter, operação e Redis e retorna os booleans acima mais uma razão determinística. Usá-la em quatro pontos: `OrderManager` antes da submissão e confirmação, `submit_exit`, métodos de proteção/OCO e payloads de status/health. Recalcular a cada tentativa, não no construtor. Em paralelo, tornar `AUTO_START_ENGINES` incapaz de armar live no restart: o processo começa com kill switch efetivo e exige rearm explícito após reconciliação.

A migração é reversível porque conserva os valores atuais e pode ser liberada primeiro em modo diagnóstico; o modo de enforcement só deve ser ligado depois dos checks abaixo. Não há necessidade de mudar menus, flags ou credenciais nesta auditoria.

## Checks de aceite binários

1. Com a matriz “sandbox seguro”, `/healthz`, `/status`, `/dashboard/status` e o websocket exibem os valores reais dos cinco flags, sem literais hardcoded; `authorization_reason` indica bloqueio.
2. Para cada combinação dos três flags live, um teste mock confirma: somente `LIVE_KILL_SWITCH=false`, `LIVE_TRADING_ENABLED=true` e `LIVE_MODE=true` remove o motivo global; qualquer outra combinação não chama o transporte.
3. Um `FakeRedis(is_persistent=False)` com `AUTONOMOUS_TRADING_ENABLED` alterado de false para true após a construção do engine bloqueia `OrderManager.submit(source="ai")` e o evento confirmado do Sniper; a lista de chamadas do adapter permanece vazia.
4. O mesmo teste com Redis persistente passa somente os gates já existentes de sinal, risco, reconciliação e adapter; nenhuma credencial real ou rede é usada.
5. Um mock de mainnet chama diretamente proteção/OCO com kill switch ativo e verifica zero chamadas de transporte; com política explícita de proteção permitida, verifica que a ordem é `reduce_only` e que a decisão fica auditada.
6. Um teste de restart em `development` com `AUTO_START_ENGINES=true` e flags live completas confirma que nenhuma task live é criada sem rearm; em `production`/`staging`, a mesma configuração continua rejeitada por `validate_startup_configuration`.
7. O caminho manual exige simultaneamente `ORDER_MANAGER_MODE=manual`, `MANUAL_TRADING_ENABLED=true` e confirmação; o caminho IA exige `ORDER_MANAGER_MODE=auto`, `AUTONOMOUS_TRADING_ENABLED=true` e `signal_validated=true`. Cada falha retorna razão distinta e zero chamada ao adapter.
8. Reexecutar a suíte mockada atual e os checks acima com `PYTHONPATH=. .venv/bin/python`; nenhum teste deve instanciar adapter mainnet/testnet real, abrir rede ou ler credencial.
