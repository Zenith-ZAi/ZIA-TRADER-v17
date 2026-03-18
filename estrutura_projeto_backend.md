# Estrutura do Projeto Back-end

O projeto Back-end é uma aplicação robusta e modular, desenvolvida em Python, que emprega o framework FastAPI para a criação de APIs assíncronas e de alta performance. A arquitetura do sistema foi concebida para integrar algoritmos de trading avançados, gerenciar estratégias de investimento, facilitar a conexão com diversas exchanges de criptomoedas e garantir a persistência segura dos dados em um banco de dados relacional.

## Componentes Essenciais do Sistema

### `main_final.py`

Este arquivo atua como o ponto central da aplicação, orquestrando a interação entre os diversos módulos e funcionalidades. Ele engloba as seguintes seções e classes:

*   **Configurações:** Um conjunto de classes Pydantic (`Settings`, `SecuritySettings`, `AISettings`, `DataSettings`, `TradingSettings`) é utilizado para gerenciar de forma estruturada as configurações da aplicação. Isso inclui chaves de API para serviços externos, parâmetros específicos para modelos de Inteligência Artificial, definições de símbolos de trading e timeframes operacionais, além dos modos de execução do sistema (por exemplo, `REAL`).

*   **Gerenciador de Credenciais (`CredentialManager`):** Esta classe é responsável por abstrair o processo de busca e armazenamento das credenciais de API dos usuários no banco de dados. Atualmente, inclui placeholders para a implementação futura de criptografia robusta, garantindo a segurança das informações sensíveis.

*   **Sistema de Logging:** Uma configuração unificada de logging é implementada para monitorar o fluxo da aplicação, registrar eventos importantes e auxiliar na depuração de possíveis problemas, direcionando as saaídas para `stdout` para compatibilidade com ambientes como o Uvicorn.

*   **Gerenciador de Conexões WebSocket (`ConnectionManager`):** Essencial para a comunicação em tempo real, esta classe gerencia as conexões WebSocket ativas, permitindo que a aplicação interaja dinamicamente com clientes e forneça atualizações instantâneas sobre o estado do mercado e das operações.

*   **`RoboTraderUnified`:** Esta é a classe central que consolida as funcionalidades de trading. Sua inicialização envolve a configuração do ID do usuário, a conexão com o banco de dados e a instanciação dos conectores de exchange e gerenciadores de estratégia. Inclui um método assíncrono, `fetch_news_sentiment`, para buscar e analisar o sentimento de notícias via GNews API, com uma simulação interna de análise de sentimento. Além disso, possui métodos internos (`_get_exchange_connector` e `_get_strategy_manager`) para obter instâncias dos respectivos conectores e gerenciadores.

*   **`ExchangeConnector`:** Esta classe é a ponte para a interação com diversas exchanges e APIs de dados de mercado. Ela contém métodos para inicializar clientes de API específicos, como CCXT para exchanges de criptomoedas, Polygon para dados de mercado gerais e Brapi para dados do mercado brasileiro. Suas funcionalidades incluem `fetch_ohlcv` para buscar dados históricos de OHLCV, `check_connection` para verificar a conectividade com a exchange principal, `fetch_balance` para consultar o saldo da conta e `create_order` para criar ordens de trading, com suporte a simulações para ambientes de teste.

*   **`StrategyBase`:** Servindo como a classe base abstrata para todas as estratégias de trading, `StrategyBase` define uma interface comum e fornece métodos utilitários. Entre eles, `fetch_data` é responsável por buscar dados OHLCV (atualmente simulados, mas projetado para integração com o banco de dados), `_simulate_ohlcv` para gerar dados simulados para backtesting, `calculate_atr` para computar o Average True Range (ATR) e `calculate_adx` para o Average Directional Index (ADX). O método `generate_signal` é abstrato e deve ser implementado por cada estratégia filha para gerar sinais de trading específicos.

*   **Estratégias de Trading:** O sistema incorpora diversas estratégias de trading, como `SimpleMACrossoverStrategy`, `BollingerBandsStrategy`, `ConfluenceStrategy`, `MomentumStrategy` e `VolumePriceStrategy`. Cada uma dessas classes herda de `StrategyBase` e implementa lógicas de trading específicas, baseadas em indicadores técnicos e regras de decisão predefinidas.

*   **`StrategyManager`:** Esta classe é encarregada de gerenciar múltiplas estratégias de trading. Ela mantém uma lista de `active_strategies` e é capaz de combinar seus sinais através do método `generate_combined_signal`, aplicando filtros baseados em notícias e no regime de mercado. Além disso, `update_strategy_risk` ajusta o risco das estratégias com base nos resultados das operações.

*   **`TradeExecutor`:** O `TradeExecutor` é o componente responsável pela execução efetiva das ordens de trading e pelo gerenciamento das posições. Ele inclui métodos como `execute_trade` para realizar compras/vendas, `manage_position` para controlar as posições abertas e `update_portfolio` para manter o portfólio do usuário atualizado.

*   **APIs FastAPI:** A aplicação expõe uma série de endpoints RESTful e WebSocket através do FastAPI, permitindo a interação com o sistema. Estes incluem rotas para autenticação de usuários (`/token`, `/users/me`), gerenciamento de chaves de API (`/api-keys`), operações de trading (`/trade/signal`, `/trade/execute`) e comunicação em tempo real via WebSockets (`/ws`).

### `database.py`

Este arquivo, importado pelo `main_final.py`, é dedicado à definição dos modelos de banco de dados utilizando o SQLAlchemy ORM. Ele também contém funções essenciais para a interação com o banco de dados, como `get_db`. Os modelos abrangem entidades como `UserAPIKey`, `OHLCVData`, `NewsArticle`, `TradingStrategy`, `Portfolio`, `Position`, `Order`, `Trade`, `User`, e diversas enums para tipificar `ExchangeType`, `OrderSide`, `OrderType`, `PositionStatus` e `StrategyStatus`.

### `.env`

O arquivo `.env` é utilizado para armazenar variáveis de ambiente, como chaves de API e outras configurações sensíveis. Esta prática garante que tais informações não sejam diretamente expostas no código-fonte, aumentando a segurança e facilitando a gestão de diferentes ambientes (desenvolvimento, produção).

## Fluxo de Execução da Aplicação

O ciclo de vida da aplicação segue uma sequência lógica de eventos:

1.  **Inicialização:** Ao ser iniciada, a aplicação FastAPI carrega todas as configurações definidas e procede à inicialização dos gerenciadores de conexão e das estratégias de trading.
2.  **Autenticação de Usuários:** Os usuários devem se autenticar para ter acesso às funcionalidades de trading, garantindo que apenas indivíduos autorizados possam interagir com o sistema.
3.  **Geração de Sinais:** O `RoboTraderUnified`, em conjunto com o `StrategyManager`, trabalha para gerar sinais de trading combinados. Este processo leva em consideração dados de mercado em tempo real, a análise de indicadores técnicos e o sentimento de notícias relevantes.
4.  **Execução de Trades:** Com base nos sinais gerados, o `TradeExecutor` é acionado para executar as ordens de compra ou venda nas exchanges configuradas. Ele também se encarrega de gerenciar as posições abertas e de manter o portfólio do usuário atualizado.
5.  **Monitoramento em Tempo Real:** Através das conexões WebSocket, os clientes podem monitorar continuamente o status de suas operações e o desempenho de seu portfólio, recebendo atualizações em tempo real.

## Tecnologias Empregadas

A base tecnológica do projeto é composta por:

| Tecnologia         | Descrição                                                              |
| :----------------- | :--------------------------------------------------------------------- |
| **Python**         | Linguagem de programação principal, escolhida por sua versatilidade e ecossistema robusto. |
| **FastAPI**        | Framework web moderno para construção de APIs de alta performance e assíncronas. |
| **SQLAlchemy**     | ORM (Object-Relational Mapper) para interação eficiente e abstrata com o banco de dados. |
| **CCXT**           | Biblioteca abrangente para conexão com diversas exchanges de criptomoedas via API. |
| **Polygon.io**     | API para acesso a dados de mercado financeiros em tempo real e históricos. |
| **Brapi**          | API especializada para dados do mercado financeiro brasileiro.         |
| **GNews API**      | API para busca e análise de notícias, fundamental para o módulo de sentimento. |
| **Pandas/NumPy**   | Bibliotecas essenciais para manipulação, análise e processamento de dados numéricos. |
| **TA-Lib**         | Biblioteca de análise técnica para cálculo de indicadores de trading. |
| **`python-dotenv`**| Utilizado para carregar variáveis de ambiente de arquivos `.env`, protegendo informações sensíveis. |

Esta estrutura, caracterizada por sua modularidade e natureza assíncrona, resulta em um sistema de trading escalável, eficiente e altamente adaptável a diferentes estratégias de investimento e às dinâmicas voláteis do mercado financeiro.
