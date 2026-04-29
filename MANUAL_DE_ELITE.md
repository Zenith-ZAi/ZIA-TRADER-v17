# 🦅 ZIA-TRADER-v17: WMM Edition (World Multi-Market)
## Manual de Instrução de Elite - Produção & Cloud

Bem-vindo à versão mais avançada do ecossistema **ZIA TRADER**. Este sistema foi reconstruído para performance institucional, integrando detecção de baleias, análise de sentimento em tempo real e execução multi-mercado.

---

## 🚀 1. Arquitetura do Sistema

O ZIA-v17 opera em uma estrutura modular de alta performance:
- **Core Engine**: Orquestração de ciclos de trading e sniper.
- **Risk AI**: Validação cirúrgica baseada em VSA (Volume Spread Analysis) e Contexto de Vela.
- **Whale Detector**: Rastreamento de ordens institucionais via fluxo de ordens e anomalias de volume.
- **News Processor**: Integração premium com Alpha Vantage e Benzinga para análise de sentimento.

---

## 🛠️ 2. Configuração e Instalação

### Pré-requisitos
- Python 3.10+
- Redis (Cache de baixa latência)
- Kafka (Opcional para processamento de eventos em larga escala)
- Docker & Docker-Compose (Recomendado para Cloud)

### Instalação Rápida
```bash
# Clone o repositório
git clone https://github.com/Zenith-ZAi/ZIA-TRADER-v17.git
cd ZIA-TRADER-v17

# Instale as dependências
pip install -r requirements.txt

# Configure as variáveis de ambiente
cp .env.example .env
```

---

## 🔑 3. Configuração de APIs (Crucial)

Para o funcionamento 10/10, configure as seguintes chaves no seu arquivo `.env`:

| Provedor | Função | Importância |
| :--- | :--- | :--- |
| **Binance/ByBit** | Execução de Crypto | Obrigatório |
| **OANDA/IC Markets** | Execução de Forex/Indices | Obrigatório para WMM |
| **Alpha Vantage** | Notícias e Sentimento Premium | Alta |
| **Benzinga** | Notícias de Impacto em Tempo Real | Alta |
| **OpenAI** | Refinamento de Decisão por LLM | Opcional (Modo Advanced) |

---

## 📊 4. Modos Operacionais

### A. Modo Standard (TradingEngine)
Ciclos de análise técnica clássica com validação de IA. Ideal para Swing e Day Trade.

### B. Modo Sniper (SniperEngine)
Alta frequência focada em scalping. Requer latência mínima e conexão direta com o servidor da Exchange.

### C. Modo Arbitragem (ArbitrageEngine)
Monitoramento de spreads entre diferentes exchanges/mercados.

---

## 🛡️ 5. Gerenciamento de Risco Cirúrgico

O **RiskAI** não apenas calcula o tamanho da posição, mas bloqueia entradas se:
1. **Notícia de Alto Impacto**: Bloqueio automático 15 min antes/depois de eventos macro.
2. **Atividade de Baleia Contrária**: Se uma baleia entrar vendendo enquanto o sistema prevê compra, o trade é abortado.
3. **Volume Inconsistente**: Entradas sem confirmação de volume real são descartadas.

---

## ☁️ 6. Recomendações de Deploy (Go-Live)

1. **VPS/Cloud**: Utilize instâncias com proximidade geográfica aos servidores da exchange (ex: AWS Tokyo para Binance).
2. **Monitoramento**: O sistema gera logs detalhados em `logs/trading.log`. Utilize ferramentas como Grafana para visualizar a performance.
3. **Backtesting**: Sempre valide novas estratégias no módulo de backtest antes de alocar capital real.

---

**Desenvolvido por Zenith-ZAi & Manus AI**
*Status: Production Ready | Version: 17.0.0 WMM*
