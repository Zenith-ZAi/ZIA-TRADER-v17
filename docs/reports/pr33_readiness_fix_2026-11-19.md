# PR #33 — revisão corretiva de readiness e progresso por gates

A PR #33 estava OPEN/CLEAN e com CI verde no head `09ea8c8`, mas a revisão automatizada posterior apontou um P2 válido: `NEWS_ENABLED_KEYED_PROVIDERS=[]` gravava `ok=false` nos providers intencionalmente disabled, e a agregação de `/healthz` degradava o serviço mesmo com fontes gratuitas saudáveis. O merge autorizado pelo usuário foi condicionado à correção e à nova validação.

Autor: Manus AI. Revisão corretiva: 2026-11-19. Este relatório complementa `backend_provider_security_2026-11-19.md`, sem apagar seus resultados históricos.

## Correção aplicada

`NewsProcessor` agora expõe `enabled`, `state` e `ok`: um provider opt-out tem state=disabled e ok=false, sem requisitar HTTP; um provider selecionado sem chave tem state=unhealthy e detail=provider_credentials_missing; erro de transporte/resposta de fonte habilitada continua unhealthy. CoinGecko Pro separa opt-in ausente de chave ausente. Valores de credenciais não entram em mensagens ou status.

A agregação de `health_payload` ignora apenas enabled=false explicitamente. Status legado sem esse campo continua sendo tratado como fonte ativa: ok=false degrada o serviço. A correção não transforma ausência em fonte saudável, não permite start de motores e não remove os requisitos de dados/notícias/ledger.

`evaluate_news_gate` não conta fontes disabled como saudáveis, mesmo que um status inconsistente declare ok=true. Serviço healthy não significa que existem notícias frescas suficientes ou que uma entrada esteja autorizada. A regressão comprova readiness ok com fontes gratuitas saudáveis e Premium disabled, enquanto a ausência de artigos continua bloqueando entrada.

Os testes novos cobrem opt-out sem request, seleção com chave ausente, falha ativa, compatibilidade com status legado, CoinGecko Pro e tentativa de contar disabled como fonte saudável. O fix não muda peso de modelo, fórmula de sinal, sizing, ledger ou flags live/manual/autonomia.

## Progresso mensurável

`scripts/backend_progress_status.py` gera JSON a partir das marcações do checklist versionado em `docs/BACKEND_SANDBOX_GUIDE.md`. O denominador é o número de critérios e seu hash é calculado somente sobre os textos; alterar um requisito muda a identidade do checklist e impede tratar séries diferentes como uma melhora comparável.

O indicador é **porcentagem de gates de checklist aceitos**, não porcentagem de código escrito, segurança certificada, precisão de sinais, lucratividade ou autorização live. O próprio snapshot não concede permissão de execução. Checklist vazio, inválido ou duplicado é rejeitado. Snapshot antes do merge: `docs/progress/pr33_readiness_fix_before_merge_2026-11-19.json`.

O próximo snapshot deve fechar o gate de CI/review/aceite apenas depois do merge efetivo, com evidência do SHA/CI. Refinar um bug em um gate já aceito não aumenta artificialmente a porcentagem. Ledger autoritativo, isolamento por cliente, modelos/OOS e staging só contam como fechados quando o critério completo for demonstrado, não quando sua fundação parcial estiver programada.

## Validação e limites

As regressões focadas de readiness, notícias, HTTP e API passaram com 39 testes e um warning preexistente. A contagem integral e o CI do fix são registrados na PR #33 para o novo head; os resultados anteriores (357 locais e 361 PostgreSQL) não são a aprovação deste novo diff.

Não houve negociação real, ordem Testnet, publicação de servidor, treinamento de modelo ou mudança de configuração operacional. A próxima fase audita cinco fronteiras separadas — controles de modos, análise observacional, ledger autoritativo, isolamento e dados multiativo — antes de escolher incremento reversível. A análise contínua deve ser nativa da aplicação e independente de motores com rota de ordem, não um processo de polling permanente improvisado no sandbox.

### Resultado integral do diff corretivo

Após os sete casos de health e quatro casos do gerador de progresso, o código congelado passou com **368 passed, 4 skipped, 1 warning**. O snapshot inicial calculado foi 6/16 gates (37,5%). O CI do novo head é independente; o resultado deve ser consultado na PR #33 antes do merge. A revisão de segurança separa explicitamente health de serviço de autorização de entrada.
