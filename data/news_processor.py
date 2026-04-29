import asyncio
import aiohttp
import json
import logging
from typing import Dict, List, Optional

from config.settings import Settings

logger = logging.getLogger(__name__)

class NewsProcessor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.alpha_vantage_api_key = settings.ALPHA_VANTAGE_API_KEY
        self.benzinga_api_key = settings.BENZINGA_API_KEY
        self.session = None

    async def _get_session(self):
        if not self.session or self.session.closed:
            self.session = aiohttp.ClientSession()
        return self.session

    async def fetch_alpha_vantage_news(self, tickers: Optional[List[str]] = None) -> List[Dict]:
        if not self.alpha_vantage_api_key:
            logger.warning("ALPHA_VANTAGE_API_KEY não configurada.")
            return []

        base_url = "https://www.alphavantage.co/query"
        params = {
            "function": "NEWS_SENTIMENT",
            "apikey": self.alpha_vantage_api_key,
            "sort": "RELEVANCE",
            "limit": 100
        }
        if tickers:
            params["tickers"] = ",".join(tickers)

        session = await self._get_session()
        try:
            async with session.get(base_url, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                feed = data.get("feed", [])
                logger.info(f"Notícias Alpha Vantage fetched: {len(feed)} artigos.")
                return feed
        except aiohttp.ClientError as e:
            logger.error(f"Erro ao buscar notícias da Alpha Vantage: {e}")
            return []

    async def fetch_benzinga_news(self, symbols: Optional[List[str]] = None) -> List[Dict]:
        if not self.benzinga_api_key:
            logger.warning("BENZINGA_API_KEY não configurada.")
            return []

        base_url = "https://api.benzinga.com/api/v2/news"
        params = {
            "token": self.benzinga_api_key,
            "displayOutput": "full",
            "pageSize": 100
        }
        if symbols:
            params["symbols"] = ",".join(symbols)

        session = await self._get_session()
        try:
            async with session.get(base_url, params=params) as response:
                response.raise_for_status()
                data = await response.json()
                articles = data.get("articles", [])
                logger.info(f"Notícias Benzinga fetched: {len(articles)} artigos.")
                return articles
        except aiohttp.ClientError as e:
            logger.error(f"Erro ao buscar notícias da Benzinga: {e}")
            return []

    async def process_news_sentiment(self, news_articles: List[Dict]) -> List[Dict]:
        # Lógica para processar e extrair sentimento dos artigos
        # Para Alpha Vantage, o sentimento já vem pré-processado
        # Para Benzinga, pode ser necessário um NLP local ou integração com outro serviço
        processed_results = []
        for article in news_articles:
            sentiment_score = 0.0 # Placeholder
            if "sentiment_score" in article: # Alpha Vantage
                sentiment_score = float(article["sentiment_score"])
            # Adicionar lógica de NLP para Benzinga se necessário
            processed_results.append({
                "title": article.get("title"),
                "source": article.get("source"),
                "sentiment_score": sentiment_score,
                "relevance_score": article.get("relevance_score", 0.0) # Alpha Vantage
            })
        return processed_results

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

# Exemplo de uso (para testes)
async def main():
    settings = Settings()
    news_processor = NewsProcessor(settings)

    # Teste Alpha Vantage
    alpha_vantage_news = await news_processor.fetch_alpha_vantage_news(tickers=["IBM", "MSFT"])
    processed_alpha_news = await news_processor.process_news_sentiment(alpha_vantage_news)
    print("\n--- Alpha Vantage Processed News ---")
    for news in processed_alpha_news:
        print(news)

    # Teste Benzinga
    benzinga_news = await news_processor.fetch_benzinga_news(symbols=["AAPL", "TSLA"])
    processed_benzinga_news = await news_processor.process_news_sentiment(benzinga_news)
    print("\n--- Benzinga Processed News ---")
    for news in processed_benzinga_news:
        print(news)

    await news_processor.close()

if __name__ == "__main__":
    asyncio.run(main())
