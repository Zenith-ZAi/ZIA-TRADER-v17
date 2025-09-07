import requests
import json
import time
from typing import Dict, List, Optional
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import logging
from transformers import pipeline

from utils import setup_logging

logger = setup_logging(__name__)

class AdvancedNewsAnalyzer:
    """
    Analisador de notícias avançado com PLN para análise de sentimento.
    Utiliza modelos pré-treinados do Hugging Face para sentiment analysis.
    """
    
    def __init__(self):
        # APIs de notícias disponíveis
        self.news_api_key = os.getenv("NEWS_API_KEY", "")
        self.alpha_vantage_key = os.getenv("ALPHA_VANTAGE_API_KEY", "")
        self.finnhub_key = os.getenv("FINNHUB_API_KEY", "")
        
        # Cache para evitar muitas requisições
        self.news_cache = {}
        self.cache_duration = 300  # 5 minutos
        
        # Inicializar pipeline de análise de sentimento do Hugging Face
        # Usar um modelo otimizado para finanças se possível, ou um geral robusto
        try:
            self.sentiment_pipeline = pipeline(
                "sentiment-analysis", 
                model="ProsusAI/finbert", 
                tokenizer="ProsusAI/finbert"
            )
            logger.info("Modelo FinBERT para análise de sentimento carregado.")
        except Exception as e:
            logger.warning(f"Falha ao carregar FinBERT, usando modelo geral: {e}")
            self.sentiment_pipeline = pipeline("sentiment-analysis")
        
        # Palavras-chave de alto impacto (ainda úteis para filtragem e ponderação)
        self.high_impact_keywords = [
            "federal reserve", "fed", "interest rate", "inflation", "gdp",
            "unemployment", "earnings", "merger", "acquisition", "ipo",
            "regulation", "policy", "central bank", "economic data",
            "trade war", "geopolitical", "oil price", "cryptocurrency"
        ]

    def get_market_news(self, symbols: List[str] = None, hours_back: int = 24) -> List[Dict]:
        """
        Obtém notícias de mercado relevantes.
        
        Args:
            symbols: Lista de símbolos para filtrar notícias
            hours_back: Horas para buscar notícias no passado
            
        Returns:
            Lista de notícias com análise de sentimento
        """
        cache_key = f"news_{symbols}_{hours_back}"
        
        # Verificar cache
        if cache_key in self.news_cache:
            cache_time, cached_news = self.news_cache[cache_key]
            if time.time() - cache_time < self.cache_duration:
                logger.info("Notícias obtidas do cache.")
                return cached_news
        
        news_articles = []
        
        # Tentar diferentes fontes de notícias
        try:
            if self.alpha_vantage_key:
                av_news = self._get_alpha_vantage_news(symbols)
                news_articles.extend(av_news)
            
            if self.finnhub_key:
                fh_news = self._get_finnhub_news(symbols)
                news_articles.extend(fh_news)
            
            if self.news_api_key:
                general_news = self._get_general_news(symbols, hours_back)
                news_articles.extend(general_news)
            
            if not news_articles:
                news_articles = self._generate_dummy_news()
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter notícias: {e}")
            news_articles = self._generate_dummy_news()
        
        # Analisar sentimento de cada notícia usando PLN
        analyzed_news = []
        for article in news_articles:
            sentiment_analysis = self._analyze_sentiment_with_nlp(article)
            article.update(sentiment_analysis)
            analyzed_news.append(article)
        
        # Armazenar no cache
        self.news_cache[cache_key] = (time.time(), analyzed_news)
        
        return analyzed_news

    def _get_alpha_vantage_news(self, symbols: List[str] = None) -> List[Dict]:
        """Obtém notícias do Alpha Vantage."""
        try:
            url = f"https://www.alphavantage.co/query"
            params = {
                "function": "NEWS_SENTIMENT",
                "apikey": self.alpha_vantage_key,
                "limit": 50
            }
            
            if symbols:
                params["tickers"] = ",".join(symbols)
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if "feed" in data:
                news_articles = []
                for item in data["feed"][:20]:  # Limitar a 20 artigos
                    article = {
                        "title": item.get("title", ""),
                        "summary": item.get("summary", ""),
                        "url": item.get("url", ""),
                        "source": item.get("source", "Alpha Vantage"),
                        "published_at": item.get("time_published", ""),
                    }
                    news_articles.append(article)
                
                return news_articles
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter notícias do Alpha Vantage: {e}")
        
        return []

    def _get_finnhub_news(self, symbols: List[str] = None) -> List[Dict]:
        """Obtém notícias do Finnhub."""
        try:
            url = "https://finnhub.io/api/v1/news"
            params = {
                "category": "general",
                "token": self.finnhub_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if isinstance(data, list):
                news_articles = []
                for item in data[:20]:  # Limitar a 20 artigos
                    article = {
                        "title": item.get("headline", ""),
                        "summary": item.get("summary", ""),
                        "url": item.get("url", ""),
                        "source": item.get("source", "Finnhub"),
                        "published_at": datetime.fromtimestamp(item.get("datetime", 0)).isoformat(),
                        "image": item.get("image", ""),
                        "category": item.get("category", "")
                    }
                    news_articles.append(article)
                
                return news_articles
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter notícias do Finnhub: {e}")
        
        return []

    def _get_general_news(self, symbols: List[str] = None, hours_back: int = 24) -> List[Dict]:
        """
        Obtém notícias gerais relacionadas ao mercado financeiro.
        """
        try:
            url = "https://newsapi.org/v2/everything"
            
            # Construir query baseada nos símbolos ou usar termos gerais
            if symbols:
                query = " OR ".join([f"\"{symbol}\"" for symbol in symbols])
            else:
                query = "stock market OR cryptocurrency OR bitcoin OR finance OR economy"
            
            from_date = (datetime.now() - timedelta(hours=hours_back)).isoformat()
            
            params = {
                "q": query,
                "from": from_date,
                "sortBy": "publishedAt",
                "language": "en",
                "pageSize": 20,
                "apiKey": self.news_api_key
            }
            
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            
            if data.get("status") == "ok" and "articles" in data:
                news_articles = []
                for item in data["articles"]:
                    article = {
                        "title": item.get("title", ""),
                        "summary": item.get("description", ""),
                        "url": item.get("url", ""),
                        "source": item.get("source", {}).get("name", "News API"),
                        "published_at": item.get("publishedAt", ""),
                        "image": item.get("urlToImage", ""),
                        "content": item.get("content", "")
                    }
                    news_articles.append(article)
                
                return news_articles
            
        except Exception as e:
            logger.error(f"❌ Erro ao obter notícias gerais: {e}")
        
        return []

    def _analyze_sentiment_with_nlp(self, article: Dict) -> Dict:
        """
        Analisa o sentimento de uma notícia usando um modelo de PLN.
        """
        text = article.get("title", "") + " " + article.get("summary", "")
        if not text.strip():
            return {
                "sentiment_label": "Neutral",
                "sentiment_score": 0.0,
                "impact_score": 0.0
            }
            
        try:
            # Analisar sentimento
            result = self.sentiment_pipeline(text[:512]) # Limitar texto para evitar estouro de token
            label = result[0]["label"]
            score = result[0]["score"]
            
            # Mapear labels para um score numérico (-1 a 1)
            sentiment_score = 0.0
            if label == "POSITIVE":
                sentiment_score = score
            elif label == "NEGATIVE":
                sentiment_score = -score
            elif label == "NEUTRAL":
                sentiment_score = 0.0
            
            # Calcular impacto baseado em palavras-chave de alto impacto
            text_lower = text.lower()
            high_impact_count = sum(1 for keyword in self.high_impact_keywords if keyword in text_lower)
            impact_score = min(1.0, high_impact_count * 0.2 + abs(sentiment_score) * 0.8) # Ponderar impacto
            
            return {
                "sentiment_label": label,
                "sentiment_score": sentiment_score,
                "impact_score": impact_score
            }
        except Exception as e:
            logger.error(f"Erro na análise de sentimento com PLN: {e}")
            return {
                "sentiment_label": "Neutral",
                "sentiment_score": 0.0,
                "impact_score": 0.0
            }

    def get_market_sentiment_summary(self, symbols: List[str] = None) -> Dict:
        """
        Obtém um resumo do sentimento geral do mercado.
        
        Args:
            symbols: Lista de símbolos para analisar
            
        Returns:
            Resumo do sentimento do mercado
        """
        news_articles = self.get_market_news(symbols)
        
        if not news_articles:
            return {
                "overall_sentiment": "Neutral",
                "sentiment_score": 0.0,
                "confidence": 0.0,
                "total_articles": 0,
                "positive_articles": 0,
                "negative_articles": 0,
                "high_impact_articles": 0,
                "recommendation": "No data available"
            }
        
        # Calcular métricas agregadas
        total_articles = len(news_articles)
        sentiment_scores = [article.get("sentiment_score", 0) for article in news_articles]
        impact_scores = [article.get("impact_score", 0) for article in news_articles]
        
        positive_articles = sum(1 for score in sentiment_scores if score > 0.1)
        negative_articles = sum(1 for score in sentiment_scores if score < -0.1)
        high_impact_articles = sum(1 for score in impact_scores if score > 0.5)
        
        # Calcular sentimento geral ponderado pelo impacto
        weighted_sentiment = sum(score * impact for score, impact in zip(sentiment_scores, impact_scores))
        total_impact = sum(impact_scores)
        
        if total_impact > 0:
            overall_sentiment_score = weighted_sentiment / total_impact
        else:
            overall_sentiment_score = sum(sentiment_scores) / len(sentiment_scores) if len(sentiment_scores) > 0 else 0.0
        
        # Determinar sentimento geral
        if overall_sentiment_score > 0.2:
            overall_sentiment = "Positive"
        elif overall_sentiment_score < -0.2:
            overall_sentiment = "Negative"
        else:
            overall_sentiment = "Neutral"
        
        # Calcular confiança baseada no número de artigos e impacto
        confidence = min(1.0, (total_articles / 10) * (total_impact / total_articles if total_articles > 0 else 0))
        
        # Gerar recomendação
        if overall_sentiment == "Negative" and high_impact_articles > 2:
            recommendation = "Avoid trading - High negative sentiment detected"
        elif overall_sentiment == "Positive" and confidence > 0.7:
            recommendation = "Favorable conditions for trading"
        else:
            recommendation = "Neutral conditions - Proceed with caution"
        
        return {
            "overall_sentiment": overall_sentiment,
            "sentiment_score": overall_sentiment_score,
            "confidence": confidence,
            "total_articles": total_articles,
            "positive_articles": positive_articles,
            "negative_articles": negative_articles,
            "high_impact_articles": high_impact_articles,
            "recommendation": recommendation
        }

    def _generate_dummy_news(self) -> List[Dict]:
        """Gera notícias simuladas para teste."""
        dummy_news = [
            {
                "title": "Bitcoin Reaches New All-Time High Amid Institutional Adoption",
                "summary": "Major corporations continue to add Bitcoin to their balance sheets, driving prices higher.",
                "url": "https://example.com/news1",
                "source": "Crypto News",
                "published_at": datetime.now().isoformat(),
            },
            {
                "title": "Federal Reserve Signals Potential Interest Rate Changes",
                "summary": "Fed officials hint at policy adjustments in response to economic indicators.",
                "url": "https://example.com/news2",
                "source": "Financial Times",
                "published_at": (datetime.now() - timedelta(hours=2)).isoformat(),
            },
            {
                "title": "Stock Market Volatility Increases Amid Geopolitical Tensions",
                "summary": "Global markets show increased uncertainty due to ongoing international conflicts.",
                "url": "https://example.com/news3",
                "source": "Market Watch",
                "published_at": (datetime.now() - timedelta(hours=4)).isoformat(),
            }
        ]
        
        return dummy_news

if __name__ == "__main__":
    # Teste do analisador de notícias avançado
    analyzer = AdvancedNewsAnalyzer()
    
    logger.info("📰 Testando analisador de notícias avançado...")
    
    # Obter notícias
    news = analyzer.get_market_news(["BTC", "ETH"], hours_back=24)
    logger.info(f"\n📊 Encontradas {len(news)} notícias")
    
    # Mostrar algumas notícias
    for i, article in enumerate(news[:3]):
        logger.info("\n" + str(i+1) + ". " + article["title"])
        logger.info("   Sentimento: " + article.get("sentiment_label", "N/A") + " (" + str(article.get("sentiment_score", 0)) + ")")
        logger.info("   Impacto: " + str(article.get("impact_score", 0)))
    
    # Obter resumo do sentimento
    sentiment_summary = analyzer.get_market_sentiment_summary(["BTC", "ETH"])
    logger.info(f"\n📈 Resumo do Sentimento do Mercado:")
    logger.info("   Sentimento Geral: " + sentiment_summary["overall_sentiment"])
    logger.info("   Score: " + str(sentiment_summary["sentiment_score"]))

    logger.info("   Confiança: " + str(sentiment_summary["confidence"]))
    logger.info("   Recomendação: " + sentiment_summary["recommendation"])






import torch

