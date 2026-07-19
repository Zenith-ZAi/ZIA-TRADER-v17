# MANUAL DE ELITE - ZIA-TRADER-v17 WMM Edition

Este manual detalha a configuração e operação do ZIA-TRADER-v17 WMM Edition, um sistema de trading avançado com inteligência artificial real, execução via CCXT/APIs e backtesting completo.

## 1. Visão Geral

O ZIA-TRADER-v17 WMM Edition é projetado para operar em mercados de criptomoedas e Forex, utilizando modelos de IA (Transformer e LSTM) para previsão de preços, um detector de atividade de "baleias" para identificar grandes movimentos de mercado, e um motor de risco cirúrgico para proteger o capital. A execução de ordens é realizada através de conectores de exchange reais (CCXT para cripto, OANDA para Forex).

## 2. Estrutura do Projeto

```
zia_project/
├── ZIA-TRADER-v17_review/ (código-fonte principal)
│   ├── ai/ (modelos de IA: Transformer, LSTM, Whale Detector)
│   ├── config/ (configurações do sistema)
│   ├── core/ (motores de trading, sniper, backtest, manager)
│   ├── data/ (processamento de notícias)
│   ├── database/ (configuração do banco de dados)
│   ├── execution/ (conectores de exchange, motor de execução)
│   ├── infra/ (cache Redis)
│   ├── risk/ (motor de gerenciamento de risco)
│   └── main.py (ponto de entrada)
└── sync_repo/ (repositório GitHub para sincronização)
    └── MANUAL_DE_ELITE.md
```

## 3. Configuração Inicial

### 3.1. Variáveis de Ambiente (`.env`)

Crie um arquivo `.env` na raiz do projeto (`ZIA-TRADER-v17_review/`) com as seguintes variáveis:

```dotenv
# Configurações Gerais
PROJECT_NAME="ZIA-TRADER-v17 WMM Edition"
VERSION="1.0.0"
TRADING_LOOP_INTERVAL=5 # Segundos
ERROR_RETRY_INTERVAL=10 # Segundos

# Configurações de Banco de Dados (PostgreSQL recomendado)
DATABASE_URL="postgresql+asyncpg://user:password@host:port/dbname"

# Configurações do Redis
REDIS_URL="redis://localhost:6379/0"

# Símbolos de Trading (Ex: BTC/USDT, ETH/USDT, EUR/USD)
SYMBOLS=["BTC/USDT", "ETH/USDT"]
TIMEFRAME="1h"

# Configurações da Exchange (CCXT para Cripto)
CCXT_EXCHANGE_ID="binance" # Ex: binance, bybit, okx
CCXT_API_KEY="SUA_API_KEY_CCXT"
CCXT_SECRET_KEY="SUA_SECRET_KEY_CCXT"

# Configurações da Exchange (OANDA para Forex - Opcional)
OANDA_API_KEY="SUA_API_KEY_OANDA"
OANDA_ACCOUNT_ID="SUA_ACCOUNT_ID_OANDA"
OANDA_ENVIRONMENT="practice" # ou "live"

# Configurações de Notícias (Alpha Vantage)
ALPHA_VANTAGE_API_KEY="SUA_API_KEY_ALPHA_VANTAGE"

# Configurações de Notícias (Benzinga - Opcional)
BENZINGA_API_KEY="SUA_API_KEY_BENZINGA"

# Configurações de Risco
MAX_RISK_PER_TRADE=0.01 # 1% do capital por trade
DAILY_LOSS_LIMIT=0.05 # 5% de perda diária máxima
WHALE_ACTIVITY_THRESHOLD=0.05 # Limiar para detecção de baleias
MIN_NEWS_SENTIMENT_FOR_BUY=0.6 # Sentimento mínimo para compra
MAX_NEWS_SENTIMENT_FOR_SELL=-0.6 # Sentimento máximo para venda

# Configurações do Sniper Engine
SNIPER_VOLATILITY_THRESHOLD=0.02 # 2% de variação em 1 minuto
SNIPER_TRADE_QUANTITY=0.01 # Quantidade de trade para o sniper
SNIPER_TIMEFRAME="1m"
SNIPER_CYCLE_INTERVAL_SECONDS=1 # Ciclo de 1 segundo para o sniper
SNIPER_PRICE_CACHE_EXPIRE=60 # Expiração do cache de preço do sniper em segundos
WHALE_ACTIVITY_SNIPER_THRESHOLD=0.7 # Limiar de baleia para o sniper
```

### 3.2. Instalação de Dependências

```bash
pip install -r requirements.txt
```

Certifique-se de que `requirements.txt` contenha:

```
asyncio
pandas
numpy
torch
torchvision
torchaudio
sqlalchemy
asyncpg
redis
python-dotenv
ccxt
aiohttp
```

## 4. Operação

### 4.1. Inicialização do Banco de Dados

Certifique-se de que seu banco de dados PostgreSQL esteja rodando e acessível. O `init_db()` em `database.py` criará as tabelas necessárias.

### 4.2. Execução do Trader

Para iniciar o motor de trading principal:

```bash
python main.py
```

O `main.py` utiliza o `TradingManager` para orquestrar os motores. Você pode alternar entre `start_trading()`, `start_sniper()` ou `run_backtest()` no `main.py` conforme sua necessidade.

## 5. Modos Operacionais

- **Trading Principal**: `trading_manager.start_trading()` - Utiliza IA e gerenciamento de risco para trades de médio/longo prazo.
- **Sniper**: `trading_manager.start_sniper()` - Focado em eventos de alta volatilidade para execução rápida.
- **Backtesting**: `trading_manager.run_backtest(symbol, historical_data, strategy_name)` - Para validar estratégias com dados históricos.

## 6. Considerações Finais

- **Segurança**: Mantenha suas chaves de API seguras e nunca as exponha publicamente.
- **Monitoramento**: Monitore o desempenho do trader e os logs para identificar e resolver problemas rapidamente.
- **Otimização**: Ajuste os parâmetros em `config/settings.py` e as estratégias em `core/strategies/manager.py` para otimizar o desempenho.

**Desenvolvido por Manus AI para Zenith-ZAi**
