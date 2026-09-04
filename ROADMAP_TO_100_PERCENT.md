# Roteiro para Prontidão Total (100%): ZIA-TRADER-v17

**Data:** 2026-09-02
**Status:** Definição dos 10% Ausentes
**Autor:** Manus AI

Embora o ZIA-TRADER-v17 esteja estruturalmente completo e validado em ambiente Sandbox, a transição para um ambiente de produção real (VPS) exige a implementação de camadas que não podem ser simuladas virtualmente de forma fidedigna. Este documento detalha os requisitos técnicos para atingir os 100% de prontidão.

## 1. Infraestrutura Física e Persistência (3%)

O ambiente Sandbox é efêmero. No VPS, o sistema deve ser configurado para resiliência de dados a longo prazo.

*   **Volumes Persistentes:** Configuração de montagens de volume Docker para o PostgreSQL e Redis, garantindo que reinicializações do servidor não causem perda de dados históricos ou snapshots de decisão.
*   **Limites de Recursos (cgroups):** Definição estrita de limites de CPU e Memória no `docker-compose.yml` para evitar que o coletor de dados consuma recursos necessários para a execução da IA em momentos de alta volatilidade.
*   **Estratégia de Backup:** Implementação de rotinas automatizadas de dump do banco de dados para armazenamento externo (ex: S3 ou servidor de backup), com testes periódicos de restauração.

## 2. Segurança de Perímetro e Gestão de Segredos (3%)

A segurança no Sandbox é isolada; no mundo real, o bot estará exposto à internet pública.

| Camada | Ação Necessária | Objetivo |
|---|---|---|
| **TLS/SSL Real** | Substituir certificados autoassinados por certificados de uma Autoridade Certificadora (CA) como Let's Encrypt. | Proteger a comunicação entre o frontend/trader e o backend contra ataques de interceptação. |
| **Firewall (WAF)** | Aplicar regras de firewall (UFW/Iptables) que bloqueiam todo o tráfego, exceto portas SSH (com chave) e HTTPS. | Minimizar a superfície de ataque contra tentativas de invasão no servidor VPS. |
| **Secrets Manager** | Migrar chaves de API da Binance e B3 de arquivos `.env` para um gerenciador de segredos seguro (ex: HashiCorp Vault ou variáveis de ambiente criptografadas). | Impedir o vazamento de credenciais em caso de comprometimento do código ou logs. |

## 3. Treinamento Massivo e Calibração de IA (2%)

O "cérebro" da IA precisa de uma base histórica vasta para reconhecer padrões de longo prazo.

*   **Dataset de 5 Anos:** O Sandbox permite testes rápidos, mas a produção exige a ingestão de 5 anos de dados OHLCV e microestrutura para B3, Forex e Cripto. Isso é necessário para que a IA compreenda ciclos econômicos completos.
*   **Aprovação do Modelo Ensemble:** Execução do `learning/training_pipeline.py` sobre este dataset massivo para gerar os pesos finais dos modelos. Apenas após a validação estatística desses pesos (Sharpe Ratio, Max Drawdown) o modelo deve ser ativado em conta real.
*   **Ajuste de Limiares:** Refinamento dos gatilhos de entrada (ex: relação comprador/vendedor 2x1) com base no aprendizado do banco de dados histórico.

## 4. Homologação de Broker e Latência (2%)

A execução no mundo real sofre com slippage e latência de rede que o ambiente simulado não possui.

*   **Teste de Latência de Rede:** Medição do tempo de ida e volta (RTT) entre o VPS e os endpoints das corretoras (ex: Binance Tokyo vs AWS Tokyo) para ajustar os tempos de expiração de ordens.
*   **Validação de Slippage:** Execução de ordens em conta Demo/Testnet no ambiente real para medir a diferença entre o preço solicitado pela IA e o preço de execução final.
*   **Teste de Kill-Switch:** Validação manual e automática do botão de emergência, garantindo que todas as ordens abertas sejam canceladas e posições fechadas instantaneamente em caso de anomalia do mercado.

## Conclusão

Os 10% restantes não são falhas de código, mas sim a **conectorização física e endurecimento de segurança** necessários para qualquer sistema financeiro de alta criticidade. Ao seguir este roteiro no seu servidor VPS, o ZIA-TRADER-v17 passará de um protótipo avançado para um sistema de trading institucional.

---
*Documento de orientação técnica para deploy em produção.*
