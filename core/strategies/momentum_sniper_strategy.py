class MomentumSniperStrategy:
    def generate_signal(self, data):
        if data["price"] > data["ema25"] > data["ema99"]:
            return {"type": "LONG", "entry": data["price"]}
        if data["price"] < data["ema25"] < data["ema99"]:
            return {"type": "SHORT", "entry": data["price"]}
        return None
