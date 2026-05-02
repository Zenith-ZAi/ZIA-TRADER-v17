import torch
import torch.nn as nn
import math

class PositionalEncoding(nn.Module):
    def __init__(self, d_model, dropout=0.1, max_len=5000):
        super(PositionalEncoding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)

        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0).transpose(0, 1)
        self.register_buffer('pe', pe)

    def forward(self, x):
        x = x + self.pe[:x.size(0), :]
        return self.dropout(x)

class PriceTransformerModel(nn.Module):
    def __init__(self, input_dim, d_model, nhead, num_encoder_layers, dropout=0.1):
        super(PriceTransformerModel, self).__init__()
        self.model_type = 'Transformer'
        self.src_mask = None
        self.pos_encoder = PositionalEncoding(d_model, dropout)
        self.encoder_layer = nn.TransformerEncoderLayer(d_model, nhead, dropout=dropout)
        self.transformer_encoder = nn.TransformerEncoder(self.encoder_layer, num_encoder_layers)
        self.encoder = nn.Linear(input_dim, d_model)
        self.decoder = nn.Linear(d_model, 1) # Output 1 price prediction
        self.d_model = d_model

        self.init_weights()

    def init_weights(self):
        initrange = 0.1
        self.encoder.weight.data.uniform_(-initrange, initrange)
        self.decoder.bias.data.zero_()
        self.decoder.weight.data.uniform_(-initrange, initrange)

    def forward(self, src):
        # src shape: (sequence_length, batch_size, input_dim)
        src = self.encoder(src) * math.sqrt(self.d_model)
        src = self.pos_encoder(src)
        output = self.transformer_encoder(src, self.src_mask)
        output = self.decoder(output)
        return output

# Exemplo de uso (para fins de demonstração, não será executado diretamente aqui)
# if __name__ == "__main__":
#     input_dim = 10  # Ex: OHLCV, indicadores, etc.
#     d_model = 64
#     nhead = 4
#     num_encoder_layers = 2
#     model = PriceTransformerModel(input_dim, d_model, nhead, num_encoder_layers)
#     
#     # Exemplo de dados de entrada: (sequence_length, batch_size, input_dim)
#     sequence_length = 30
#     batch_size = 1
#     dummy_input = torch.rand(sequence_length, batch_size, input_dim)
#     
#     output = model(dummy_input)
#     print(f"Output shape: {output.shape}") # Esperado: (sequence_length, batch_size, 1)
