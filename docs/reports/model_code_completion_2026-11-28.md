# Incremento de contratos de modelos — 2026-11-28

**Repositório:** `Zenith-ZAi/ZIA-TRADER-v17`
**Branch:** `fix/ai-model-contracts`, criada sobre `origin/master`
**Escopo:** correções locais e verificáveis nos contratos do pipeline de features, do registry de artefatos e do detector de regime. Nenhum modelo foi promovido e nenhum gate de operação foi habilitado.

## O que foi concluído neste incremento

- **RSI em casos-limite:** a feature `rsi_norm` agora distingue série estritamente crescente (`+1`), estritamente decrescente (`-1`) e plana (`0`). O período de aquecimento permanece inválido/NaN até haver observações suficientes, em vez de ser preenchido artificialmente com RSI neutro.
- **Compatibilidade de artefatos:** a versão do schema foi elevada de `ohlcv_features_v1` para `ohlcv_features_v2`. O loader já rejeita metadata da versão antiga, evitando usar um modelo treinado com a semântica anterior. A versão nova requer retreino e validação OOS antes de qualquer candidato ser considerado.
- **Bundle do registry:** `artifact_sha256()` agora exige os três arquivos de inferência (`rf_model.joblib`, `xgb_model.joblib`, `ensemble_metadata.json`) antes de registrar/verificar um hash. Diretórios incompletos falham fechados.
- **Validação OHLC:** `MarketRegimeDetector` rejeita `close` abaixo de `low` ou acima de `high` como `unknown/bad_data`, sem modificar thresholds, sinais ou sizing.
- **Fluxo de testes no Sandbox:** o checkout anterior estava na branch documental; este trabalho foi isolado em branch a partir de `origin/master`. O Python global não tinha `pytest` nem dependências de teste/ML necessárias. As dependências usadas foram instaladas em `.venv` local, ignorado pelo Git; `pytest.ini` define `pythonpath = .`, corrigindo a descoberta dos módulos do repositório ao invocar o console `pytest` a partir do root. Nenhuma dependência versionada foi alterada.

## Evidência executada

- Testes focados de features/model registry/treinamento/walk-forward/drift/estratégias/regime: **68 passed, 1 skipped**.
- O teste ignorado é a integração PostgreSQL condicionada a `TEST_DATABASE_URL`, ausente neste Sandbox.
- `compileall` dos arquivos Python alterados: passou.
- `git diff --check`: passou.
- A suíte integral do repositório não foi executada.

Os casos de treino/predição com fixtures servem apenas para validar contratos e determinismo; fixtures não representam preços reais nem evidência de performance.

## Estado atual e pendências

| Área | Estado após este incremento | Ainda falta |
|---|---|---|
| Features/Ensemble ML | **Parcial, contrato de RSI corrigido** | Dataset verificado/licenciado, treino reprodutível real, walk-forward OOS por regime com custos/slippage, calibração e aprovação humana independente. |
| Registry de modelos | **Parcial, bundle obrigatório endurecido** | Testes PostgreSQL/concorrência no CI e processo operacional de backup/rollback validado. |
| Detector de regime | **Parcial, validação de OHLC reforçada** | Validação causal e de performance com dados autorizados; não há ajuste de limiar nesta mudança. |
| Modelos LSTM/Transformer | **Incompletos para inferência operacional** | Treinadores/datasets e protocolo OOS aprovados; permanecem desabilitados por default. |

Não foi feito treino de mercado, não há novo modelo aprovado e nenhum modelo `v1` foi convertido automaticamente para `v2`. O operador precisará fornecer/prover fonte autorizada, instrumento, timeframe, timezone, política de gaps e período antes do treino OOS. Os gates existentes devem continuar rejeitando ausência de evidência.

## Limites preservados

Este incremento **não** altera risco/sizing/Kelly, parâmetros de estratégia, sinais/thresholds, permissão de ordem, credenciais, migrations, APIs de execução ou flags. Não implementa módulos ausentes como ponte multiativo/observer contínuo, writer financeiro autoritativo, autenticação/isolamento JWT completo, vault KMS, gateway de exchange homologado, nem WebSocket sem token em query. Live, autonomia, neural/ensemble em runtime e ordens reais permanecem desabilitados.

## Próxima sequência recomendada

1. Selecionar e validar um dataset OHLCV autorizado, com proveniência, timezone, timeframe e tratamento documentado de gaps.
2. Treinar uma versão nova com schema `v2` em ambiente isolado e produzir relatório walk-forward com purge/embargo, baseline determinístico, custos e slippage; fixtures não podem cumprir este gate.
3. Manter o resultado como `candidate/rejected` até revisão das métricas OOS, registry PostgreSQL e critérios humanos de aprovação; nenhuma promoção automática nesta rodada.
4. Só depois tratar monitoramento/drift operacional e, em trabalho separado, os bloqueadores críticos de segurança e dados.
