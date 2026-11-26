# Auditoria de integração das PRs abertas — 2026-11-26

**Repositório:** `Zenith-ZAi/ZIA-TRADER-v17`
**Consulta:** 2026-11-26, aproximadamente 12:33 UTC−04
**Objetivo:** distinguir código presente em branches/PRs de código integrado em `master` e ordenar os bloqueios de integração. Esta auditoria não homologa gate, deployment nem operação.

## Estado verificado

| PR | Estado/base | Head consultado | Checks | Revisão/integração | Limite principal |
|---|---|---|---|---|---|
| [#35 Passkey MFA](https://github.com/Zenith-ZAi/ZIA-TRADER-v17/pull/35) | Aberta, draft; base `master` | `572c8d9a1a7517f08fd1d9bb10b21d05c536d01a` | `test` e `container` SUCCESS | Sem decisão/revisão humana; não mergeada | Cerimônias reais browser/TLS, integração frontend, recuperação/revogação e revisão independente pendentes; migration `e8c4b70d2a91` é head irmão sobre `c3f1e2a9b7d4`. O transporte JWT do WebSocket por query string está explicitamente fora do escopo. |
| [#36 Credential Vault](https://github.com/Zenith-ZAi/ZIA-TRADER-v17/pull/36) | Aberta, draft; base `master` | `f442b96d221377a28aa80125bf37463cf519db75` | `test` e `container` SUCCESS | Sem decisão/revisão humana; não mergeada | Sem validação real de KMS/IAM/CloudTrail/PostgreSQL staging, nem binding JWT→`PrincipalV1`/caller confiável, auditoria durable independente ou prova de recuperação/revogação. Migration `f72c4a8e1d90` é head irmão sobre `c3f1e2a9b7d4`. |
| [#37 Read-only Exchange gateway](https://github.com/Zenith-ZAi/ZIA-TRADER-v17/pull/37) | Aberta, draft; base `feature/gate-credential-vault` (empilhada sobre #36) | `37bcd62fb805b4fc230324d7676e8fc40a7c3e2c` | Nenhum check registrado na consulta | Sem decisão/revisão humana; não mergeada | CI, binding de identidade confiável, Testnet com chave comprovadamente read-only, staging e recuperação/revogação pendentes. Não pode ser tratado como parte de `master`; depende de #36. |
| [#38 Ledger schema foundation](https://github.com/Zenith-ZAi/ZIA-TRADER-v17/pull/38) | Aberta, não draft; base `master` | `10f9d3aea435acadf993bd5218f28fcfacda678c` | `test` e `container` SUCCESS; CodeRabbit SKIPPED | `reviewDecision` vazio, sem revisão humana; não mergeada | Schema-only: writer/produtor autenticado, adapter homologado, cobertura/cursor recuperável, reconciliação independente, recovery e grants separados ainda não existem. Migration `d8a11c4e52f0` também deriva de `c3f1e2a9b7d4`. |

`mergeStateStatus=CLEAN` nas PRs inspecionadas não significa revisão aprovada nem aceite. Checks verdes demonstram somente os checks executados para o SHA consultado; não provam integração de branches, autenticação de fonte financeira ou operação real.

## Bloqueio de cadeia Alembic

No `master` atual, a revisão compartilhada mais nova é `c3f1e2a9b7d4`. As PRs #35, #36 e #38 adicionam, respectivamente, `e8c4b70d2a91`, `f72c4a8e1d90` e `d8a11c4e52f0`, cada uma declarando `c3f1e2a9b7d4` como predecessor. Portanto, integrar as três heads requer uma cadeia ordenada ou uma revisão Alembic de merge deliberada, acompanhada por testes da migration consolidada. A PR #37 está empilhada sobre #36, embora não adicione migration nesta auditoria.

Não se deve rebasear/mesclar a pilha automaticamente apenas para remover múltiplos heads: antes é necessário verificar as migrations, a ordem funcional e o teste de upgrade/downgrade no branch combinado. A solução escolhida deve preservar dados e permitir upgrade desde a revisão atual, sem apagar schema existente.

## Ordem de integração recomendada

1. **Preservar os drafts e os limites atuais.** Não habilitar endpoints/flags de produção nem declarar gates `ACCEPTED` por causa de CI, hashes ou estado `CLEAN`.
2. **Concluir a fase de código do ledger em branches sandbox** com validação decimal exata, writer idempotente, adapter de origem explicitamente delimitado e reconciliação independente. A implementação deve continuar fail-closed e sem consumidor de risco até haver evidência e revisão apropriadas.
3. **Consolidar migrations e testes** de #35, #36, #38 e dependentes em uma branch de integração; obter um único head Alembic e rodar suíte completa + PostgreSQL no CI do conjunto efetivamente combinado. #37 só deve ser testada sobre a base de vault que realmente será integrada.
4. **Resolver os gaps próprios de segurança/integration** de Passkey, vault e gateway e obter revisão humana independente. Não transformar os atuais drafts em mergeáveis por simples retitulação.
5. **Integrar por PRs revisadas na base final** após checks do head combinado. Registrar cada SHA integrado e resultado pós-merge no roadmap. Se os PRs forem squash/mergeados em sequência, preservar a cadeia migratória consolidada e repetir CI pós-merge.
6. **Somente depois, em etapa separada**, executar homologação de staging/VPS, restauração, supervisão, fault injection e soak. Isso não é necessário para concluir os testes de código locais, mas continua necessário para provar a operação real.

## Estado de aceite

Nenhum dos quatro PRs foi contado como integrado ou `ACCEPTED` nesta consulta. A baseline histórica de gates não foi recalculada. Ledger financeiro, modelo/dados, operação distribuída e aceite ponta a ponta continuam gates distintos; qualquer avanço de código deve manter essa distinção explícita.
