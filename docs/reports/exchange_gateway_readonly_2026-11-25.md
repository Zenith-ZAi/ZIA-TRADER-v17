# Gateway de Exchange — fundação read-only (2026-11-25)

**Branch:** `feature/gate-exchange-gateway`

**Base empilhada:** `feature/gate-credential-vault` (PR #36, ainda draft)

**Dependências relacionadas:** PR #35 (Passkey/WebAuthn, draft) e PR #36 (Vault KMS, draft).

**Status:** implementação candidata; **não aceita**; nenhuma autorização de trading foi criada.

## Escopo desta etapa

Esta entrega inicia um único gate: uma fronteira intermediária que combina resolução de conta/tenant, role persistida e acesso ao Vault para leituras privadas de Exchange. Não altera nem integra as PRs #35/#36. O novo código está empilhado sobre a branch do vault porque depende do contrato `CredentialVault`; a integração final exige resolver a cadeia de migrations do Passkey e do Vault, que atualmente são heads irmãos sobre `c3f1e2a9b7d4`.

## O que foi implementado

- `execution/exchange_gateway.py` fornece operações explícitas `fetch_balance`, `fetch_open_orders` e `fetch_trades`; não há método de ordem ou despacho genérico.
- Cada chamada resolve novamente o `TrustedCaller`, tenant, conta e membership ativo, exige role `trader` (ou `admin`) e não confia em tenant/account como prova de ownership.
- O primeiro allowlist admite somente adapters explicitamente registrados para ambiente `testnet`; Mainnet, ambiente não suportado e venue sem adapter falham fechados.
- Credenciais são lidas do Vault e a auditoria `accessed` é commitada numa sessão dedicada antes do I/O externo. A sessão DB fecha antes da chamada de rede; a lease é encerrada no `finally`. Chamadas têm timeout máximo de 15 segundos e o fechamento do adapter é limitado a 5 segundos.
- A exceção do provider é substituída por erro genérico para não repassar URL, headers ou conteúdo que possa carregar credenciais.
- `EXCHANGE_GATEWAY_READ_ONLY_ENABLED=false` foi adicionado às configurações e ao `.env.example`. Habilitar essa flag não habilita ordem, Mainnet, autonomia ou endpoints HTTP.
- A alteração está isolada da branch Passkey. Nenhuma migration nova foi criada neste incremento.

## Limites e critérios ainda pendentes

Este incremento **não comprova** identidade JWT → `TrustedCaller`, não expõe rota FastAPI, não registra adapter de Exchange real, não valida permissão read-only no painel/API do provedor, não faz chamadas reais em Testnet, não cobre rotação/revogação durante chamada em voo e não prova auditoria imutável/durável contra restore ou adulteração por administrador do banco. Não há autorização de credenciais de produção, envio/cancelamento de ordens ou execução Mainnet. A factory de adapter precisa ser código confiável, curta em duração e configurada com chave de Exchange restrita a leitura.

A aceitação do gate exige, no mínimo: revisão independente; cadeia Alembic unificada e CI/PostgreSQL; binding autenticador validado após a etapa Passkey; integração de adapter Testnet read-only com permissões de chave verificadas; evidência de negação de conta/tenant/role/env não permitidos; observabilidade sem segredos; e prova de recovery/revogação. Até lá, mantenha a flag OFF e não incremente o contador de 16 gates.

## Evidência local desta etapa

Validação focada: **47 passed, 1 warning** em `test_exchange_gateway.py`, `test_default_safety_flags.py`, `test_credential_vault.py`, `test_startup_validation.py` e `test_settings_secrets.py`. O warning é o `PendingDeprecationWarning` preexistente do parser de formulário do Starlette. A suíte usa SQLite e KMS stub; não representa chamada real à AWS, PostgreSQL de staging, Exchange ou cerimônia WebAuthn. `compileall` e `git diff --check` passaram localmente; o CI precisa repetir as checagens no head publicado.

CI integral do PR empilhado, revisão independente, unificação das migrations e validações de staging/Testnet ainda são gates pendentes; resultados de testes locais não constituem aceite.
