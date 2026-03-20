# ZIA Trader v17 - Projeto Finalizado

O **ZIA Trader v17** é um motor de trading de produção robusto e modular, desenvolvido em Python. Esta versão final consolida algoritmos avançados de trading, inteligência artificial para análise de sentimento e regime de mercado, e uma infraestrutura de backend escalável utilizando FastAPI.

## Estrutura do Projeto

O projeto está organizado nos seguintes módulos principais:

| Módulo | Descrição |
| :--- | :--- |
| **`main_final.py`** | Ponto de entrada principal da aplicação, integrando todos os componentes e expondo a API FastAPI. |
| **`database.py`** | Definição dos modelos de dados (SQLAlchemy) e gerenciamento da persistência. |
| **`core/`** | Lógica central do motor de trading e definições de estratégias. |
| **`ai/`** | Modelos de Inteligência Artificial, incluindo o `transformer_model.py`. |
| **`intelligence/`** | Módulos de inteligência de mercado, como liquidez global e simulador de baleias. |
| **`risk/`** | Gerenciamento rigoroso de risco e exposição do portfólio. |
| **`execution/`** | Motor de execução de ordens e conectores de exchange. |

## Documentação Adicional

Para informações detalhadas sobre a arquitetura e estratégias específicas, consulte:

*   **`estrutura_projeto_backend.md`**: Descrição técnica detalhada da arquitetura do sistema.
*   **`estrategia_queda_livre.md`**: Guia operacional para a estratégia de trading em cenários de queda livre (ETH/USDT).

## Configuração

1.  Certifique-se de configurar suas chaves de API no arquivo **`.env`**.
2.  Instale as dependências necessárias listadas em `requirements.txt`.
3.  Inicie a aplicação utilizando um servidor ASGI (ex: `uvicorn main_final:app`).

---
*Desenvolvido por Zenith-ZAi*
