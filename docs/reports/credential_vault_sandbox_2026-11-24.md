# Cofre de credenciais KMS — implementação e evidências no Sandbox

**Data:** 2026-11-24
**Branch:** `feature/gate-credential-vault`
**Base:** `master` em `360073b288dacc48367e33f7d0c29835ed43d1e5`
**Estado do gate:** **PARCIAL / NÃO ACEITO (`NOT ACCEPTED`)**

## Escopo desta entrega

Foi implementado um serviço interno de cofre por tenant/conta, sem endpoint público nem integração ao gateway/adapter de Exchange. O cofre dá suporte a gravação, leitura autorizada, versionamento/rotação do conjunto de credenciais, revogação local e eventos de auditoria de metadados. A existência deste serviço não habilita execução real, trading live, armazenamento de segredos de produção nem recuperação de credenciais por qualquer componente existente.

## Arquitetura implementada

- `core/credential_vault.py` usa `GenerateDataKey` do AWS KMS com `AES_256`; cada gravação/versão recebe uma nova chave de dados. O payload é cifrado localmente com AES-256-GCM e nonce aleatório de 96 bits.
- O KMS Encryption Context e o AAD do AES-GCM vinculam o envelope a aplicação/finalidade, tenant, conta, identificador do registro e versão; o AAD também vincula venue, ambiente e ARN KMS. Um ciphertext transplantado para outro escopo, versão ou chave falha na autenticação.
- PostgreSQL/SQLite guardam somente ARN da chave, chave de dados cifrada pelo KMS, nonce, ciphertext, versão/status, ator e timestamps. Não há colunas para API key, secret ou passphrase. Constraints limitam estados, versão, tamanho do nonce, envelope revogado vazio e formato dos IDs.
- A autorização é reavaliada via `resolve_client_scope`: criação, rotação e revogação exigem papel `admin`; leitura exige `trader`. As operações exigem tenant e conta explícitos, fazem lock de linha para mutações e usam `expected_version` para impedir gravação obsoleta.
- Os eventos `created`, `rotated`, `accessed` e `revoked` contêm somente metadados. Eles são gravados na mesma transação SQL do chamador; **não** formam um log externo append-only e podem ser revertidos se a transação for desfeita. Em particular, `retrieve()` faz `flush` e devolve o segredo antes do commit do chamador, que ainda pode reverter o evento de acesso.
- Revogação limpa o envelope cifrado local. Ela **não** chama a Exchange para revogar/desabilitar a credencial externa.
- O provider AWS usa a cadeia padrão de credenciais do Boto3, fora das configurações de aplicação. Em produção, o deployment deve usar identidade de workload com privilégio mínimo, restrita à chave dedicada e apenas às ações KMS necessárias (`GenerateDataKey` e `Decrypt`); nunca conceder `kms:*` nem colocar credenciais AWS estáticas no repositório.
- O cofre está desligado por padrão. O startup em production/staging falha fechado sem provider AWS, região válida e ARN completo de chave KMS correspondente à região configurada; aliases e key IDs sem ARN são recusados.

## Migração e coexistência com Passkey

A migration aditiva `f72c4a8e1d90` cria `credential_vault_v1` e `credential_vault_audit_v1`, com chaves estrangeiras e constraints. Ela parte de `c3f1e2a9b7d4`.

A migration Passkey `e8c4b70d2a91` do PR draft #35 também parte de `c3f1e2a9b7d4`. Portanto, são heads irmãos no estado atual das branches. **Não integrar as duas migrations diretamente sem rebase/ajuste da cadeia Alembic**; os PRs permanecem separados e a branch Passkey não foi alterada nesta entrega.

## Evidências executadas no Sandbox

- Suíte completa: **436 passed, 5 skipped, 1 warning** (2026-11-24). Os cinco skips requerem `TEST_DATABASE_URL`/PostgreSQL: `test_database_migrations.py`, `test_equity_ledger.py`, `test_model_registry.py`, `test_postgres_backup_restore.py` e `test_postgres_client_scope.py`. O aviso restante é `PendingDeprecationWarning` de `python_multipart` via Starlette.
- Suíte focada de cofre, startup e factory: **35 passed**.
- `python -m compileall` para os módulos alterados: passou.
- `uv pip check --python .venv/bin/python`: 121 pacotes compatíveis.
- Alembic em SQLite temporário: upgrade até `f72c4a8e1d90` e downgrade vazio até `c3f1e2a9b7d4` passaram. `alembic check` após upgrade indicou `No new upgrade operations detected`.
- `git diff --check`: passou.
- O contrato do adapter AWS foi exercitado com `botocore.stub.Stubber`, incluindo `GenerateDataKey` AES-256, contexto e ARN explícito. Foram adicionadas regressões para mismatch entre ARN/região e para IDs não canônicos.

Esses resultados demonstram comportamento local/mocks e coerência do schema no SQLite; não comprovam operação com PostgreSQL real, identidade IAM, policy/key policy AWS, autorização KMS, CloudTrail, latência, rotação real ou recuperação operacional.

## Pendências que mantêm `NOT ACCEPTED`

1. Validar em ambiente isolado real com AWS KMS e identidade IAM/role dedicada; revisar key policy/IAM com menor privilégio, Encryption Context e eventos CloudTrail. Nenhuma chamada real ao KMS foi feita nesta sessão e não há identidade AWS disponível.
2. Executar migration, constraints e testes em PostgreSQL real/CI; os cinco testes listados acima foram pulados localmente por falta de `TEST_DATABASE_URL`.
3. Resolver a cadeia Alembic junto ao PR Passkey #35 antes de qualquer integração de ambas as alterações, mantendo PRs e branches separados.
4. Integrar identidade confiável antes de expor o serviço: `TrustedCaller` é um objeto construível e não se autentica sozinho; o runtime atual não mapeia JWT para `PrincipalV1` nem instancia o vault. Criá-lo somente a partir de dependência autenticadora que valide e vincule o principal persistido; nunca aceitar tenant/conta/issuer/subject como identidade confiável do payload.
5. Garantir que cada leitura seja auditada de modo durável e append-only antes de devolver o segredo. Hoje o evento `accessed` permanece na transação do chamador, não há proteção de banco contra alteração/exclusão e um rollback após `retrieve()` pode apagar o registro já depois da entrega do material. Definir sink/fronteira transacional durável e testar falhas de commit.
6. Definir política de backup/restore para revogação: snapshots anteriores ainda podem conter ciphertext e chave de dados embrulhada; restaurar um backup antigo pode ressuscitar a credencial. Exigir reconciliação/invalidadores pós-restore ou isolamento criptográfico apropriado, com teste de restauração após revogação.
7. Fazer revisão operacional independente e definir resposta a falha/indisponibilidade e retenção/recuperação compatível. A limpeza de `bytearray` é best-effort em Python; strings e cópias internas não têm garantia de zeroização.
8. Implementar e revisar separadamente o gateway de Exchange, a integração de chamada autorizada do cofre, revogação externa, e testes e2e em Demo/Testnet. Esta entrega não conecta o cofre ao fluxo de ordem nem ao conector existente.
9. Planejar rotação/migração entre chaves KMS diferentes. A implementação grava o ARN por envelope, mas o provider atual só opera com o ARN configurado; trocar o ARN sem recriptografar/reescrever envelopes antigos pode tornar registros antigos inacessíveis. Rotação automática do material da mesma chave KMS não é o mesmo que substituir seu ARN.

Até fechar essas pendências e obter evidência em ambiente isolado, não declarar o gate concluído/`ACCEPTED`, não alterar contagem cumulativa de gates e não ativar credenciais, gateway ou trading real. O próximo gate de segurança permanece bloqueado até confirmação do usuário após revisão desta consolidação.
