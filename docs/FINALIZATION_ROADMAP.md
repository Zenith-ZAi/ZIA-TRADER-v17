# Plano de finalização — ZIA-TRADER v17 após a Fase 7

**Atualizado:** 2026-10-21. **Base:** `master` após PR #19; branch de execução atual `phase8/cpu-lock-and-final-readiness`. O objetivo é chegar a **pré-produção supervisionada em VPS**, não prometer capital real ou código sem defeitos.

## Onde estamos: pontuação de engenharia, não métrica estatística

Os percentuais abaixo são uma avaliação de gates/evidências, não uma contagem de linhas implementadas, probabilidade de lucro ou certificação de segurança. Foram atribuídos conforme itens verificados e bloqueios ainda abertos.

| Dimensão | Estimativa | Evidência e limitador dominante |
|---|---:|---|
| Arquitetura backend e controles de segurança | **75–80%** | Alembic/PostgreSQL, gates fail-closed, OrderManager, reconciliação, controles de risco, logs e regressões temporais existem; ledger financeiro verificável e revisão independente continuam ausentes. |
| Estrutura de engenharia e testes locais | **75%** | 189 testes passaram no baseline Phase 7; agora 192 passaram no venv limpo Phase 8A; CI de #18/#19 passou e o CI Phase 8A aprovou `test` e `container`. `uv pip check` do venv antigo revelou wheel incompatível, tratado por lock CPU. |
| IA/dados prontos para validação OOS | **25–30%** | Pipeline walk-forward/registry/drift está presente; falta dataset real licenciado/proveniente e modelo validado/aprovado. |
| VPS e operação 24/7 comprovadas | **30–35%** | Compose e container build no CI existem; não houve boot, PostgreSQL/Redis persistentes, TLS, backup/restore, alertas ou restart test em VPS alvo. |
| Autonomia real autorizável hoje | **0% habilitado; cerca de 10% de prontidão de engenharia** | Flags reais continuam OFF; equity/trade ledgers inexistentes e não há soak Demo/Testnet. Não habilitar execução autônoma real nesta situação. |
| **Prontidão geral para VPS supervisionada com negociação** | **aprox. 40/100** | Estimativa conservadora e arredondada: código maduro não substitui proveniência financeira, modelo, homologação de venue, restore, operação contínua e aprovação humana. |

O repositório está mais adiantado que a prontidão do sistema para assumir risco. “75% de estrutura” não significa “75% seguro para operar dinheiro”.

## Fases finais propostas

### Fase 8A — Dependências e build reproduzível (em andamento nesta branch)

- **Defeito:** o lock anterior foi exportado de um ambiente diferente e continha `nvidia-cusparselt-cu13` (`manylinux2014_sbsa`), enquanto a virtualenv ativa do Sandbox é ARM64. O Dockerfile e CI instalavam `requirements.txt`, ignorando o lock; portanto o lock não era nem usado nem portátil.
- **Correção em implementação:** resolver Torch em backend CPU explícito, fixar dependências por versão e SHA-256, remover artefatos CUDA/NVIDIA desnecessários para VPS CPU, sincronizar exatamente o lock em CI e Docker e executar `uv pip check`.
- **Aceite local:** instalação limpa ARM64 a partir do lock, Torch reporta `cuda_build=None`, nenhum wheel NVIDIA incompatível, `uv pip check` passa e 192 testes passam. **Aceite da branch:** jobs `test` e `container` do PR #20 verdes no run `39651671722`; imagem construída em runner GitHub x86_64. Build ARM e execução do Compose/VPS continuam não testados.

### Fase 8B — Ledger financeiro e reconciliação

Implementar, em migração aditiva e compatível, eventos imutáveis de intents, ordem externa, fills parciais/completos, comissões, funding, depósitos/saques e snapshots de saldo/posição. Definir fonte autoritativa por adapter, chaves de idempotência, timestamps UTC, `Decimal`, completude/late data, reconstrução após restart e reconciliation. Construir `equity_ledger_v1` e `closed_execution_ledger_v1` somente a partir de eventos rastreáveis. Não converter dado ausente em zero. Cobrir duplicatas, atrasos, concorrência, cashflow, fees, funding e fronteiras UTC em testes determinísticos. **Entradas seguem bloqueadas até revisão de domínio, integração mock e evidência read-only/Demo confiável.**

### Fase 8C — Dados de mercado e aprovação de modelo

O operador precisa selecionar/prover uma fonte de dados autorizada para os instrumentos e período pretendidos. Registrar licença/origem, timezones, ajustes, cobertura/gaps, SHA-256 e maturidade de labels. Executar treinamento reprodutível e walk-forward com purge/embargo, OOS por regime, custos e slippage; comparar buy-and-hold/sinal determinístico; avaliar calibração e drift. Ausência de dados ou gate não aprovado continua `HOLD`. Não fabricar dataset ou artefato aprovado.

### Fase 8D — VPS de staging e segurança operacional

Escolher arquitetura/OS/região e provedor alvo; fornecer/autorizar ambiente **staging isolado** sem capital real. Validar `docker compose config`, build, migrations, volumes PostgreSQL/Redis, health/readiness, shutdown/restart, falhas de dependência, proxy TLS, firewall, SSH, NTP, secrets, rate limit, CORS e logs. Fazer backup e restore em banco separado e medir recursos. CI build verde não prova nenhum desses itens.

### Fase 8E — Trading autônomo apenas em shadow/paper e Demo/Testnet supervisionado

Antes de considerar autonomia, executar primeiro shadow/paper sem rota de ordem; provar que decisão, sizing, proteção, shutdown e reconciliação ficam consistentes. Depois, se o usuário selecionar e configurar explicitamente uma venue Demo/Testnet e houver gates aprovados, ensaiar timeout ambíguo, fill parcial, restart e kill switch. Exigir diário auditável, limites conservadores e acompanhamento humano; qualquer estado incompleto bloqueia novas entradas. Isso não autoriza mainnet.

### Fase 8F — Soak, auditoria e aceite

Operar em staging contínuo por janela acordada, revisar alertas, drift, disco, atraso de feed, falhas, backups e latência; demonstrar restore e rollback. Fazer revisão de segurança independente, LGPD/retention/export/delete, resposta a incidente e responsabilidade operacional. A autorização de qualquer modo de live é uma decisão humana separada, depois da evidência, e não será ativada automaticamente pelo código ou por um merge.

## Próximo passo executável

Concluir 8A com CI do PR desta branch e ajustar conforme o resultado. Em paralelo, definir interfaces e testes fake para 8B/8C sem substituir fontes reais nem enfraquecer risco. Só depois da aprovação desses contratos avançar a qualquer staging de venue. Manter permanentemente `LIVE_TRADING_ENABLED=false`, `LIVE_MODE=false`, `LIVE_KILL_SWITCH=true`, `AUTO_START_ENGINES=false`, `AUTONOMOUS_TRADING_ENABLED=false`, `MANUAL_TRADING_ENABLED=false`, `NEURAL_MODELS_ENABLED=false` e `BACKTEST_USE_ENSEMBLE=false` durante o trabalho desta fase.

## Limites e decisões externas

Para avançar a testes de integração são necessários: definição do alvo VPS (arquitetura/OS), escolha de fornecedor autorizado de dados, e venue Demo/Testnet pretendida. Não são necessários para a resolução local 8A. Credenciais de live ou de carteiras não devem ser solicitadas nem usadas nesta etapa.
