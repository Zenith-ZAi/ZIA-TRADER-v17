import asyncio
import aiohttp
from typing import List, Dict, Any
from datetime import datetime
from config.settings import settings
from utils import logger

class NewsProcessor:
    """Módulo de Processamento de Notícias e Calendário Econômico em Tempo Real."""
    
    def __init__(self):
        self.api_key = settings.GNEWS_API_KEY
        self.high_impact_keywords = ["NFP", "FOMC", "CPI", "Interest Rate", "Inflation", "GDP", "Unemployment"]
        self.current_impact_score = 0.0

    async def fetch_latest_news(self, symbol: str) -> List[Dict[str, Any]]:
        """Busca notícias recentes para um símbolo específico."""
        url = f"https://gnews.io/api/v4/search?q={symbol}&lang=en&token={self.api_key}"
        
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get("articles", [])
                    else:
                        logger.error(f"Erro ao buscar notícias: {response.status}")
                        return []
            except Exception as e:
                logger.error(f"Falha na conexão com GNews: {e}")
                return []

    def analyze_impact(self, articles: List[Dict[str, Any]]) -> float:
        """Calcula o impacto macroeconômico baseado em palavras-chave e sentimento."""
        impact_score = 0.0
        
        for article in articles:
            title = article.get("title", "").upper()
            description = article.get("description", "").upper()
            
            # Verifica palavras-chave de alto impacto
            for keyword in self.high_impact_keywords:
                if keyword in title or keyword in description:
                    impact_score += 0.25  # Incrementa impacto por palavra-chave encontrada
                    
        # Normaliza o score entre 0.0 e 1.0
        self.current_impact_score = min(impact_score, 1.0)
        return self.current_impact_score

    async def get_economic_calendar_impact(self) -> float:
        """
        Simula a leitura do calendário econômico.
        Em produção, integraria com APIs como Trading Economics ou Investing.com.
        """
        # Exemplo: Se for horário de NFP (12:30 PM UTC), impacto é máximo.
        now = datetime.utcnow()
        if now.hour == 12 and 20 <= now.minute <= 45:
            logger.warning("Horário de NFP detectado! Impacto macroeconômico máximo.")
            return 1.0
            
        return self.current_impact_score

news_processor = NewsProcessor()
