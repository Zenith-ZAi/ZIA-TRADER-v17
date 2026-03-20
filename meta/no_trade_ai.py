class NoTradeAI:
    def evaluate(self, data):
        return data.get("volume", 1) < 0.5
