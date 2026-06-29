import torch
import torch.nn as nn
import numpy as np
from typing import Optional

class PriceTransformerModel(nn.Module):
    def __init__(self, input_dim: int, d_model: int, nhead: int, num_encoder_layers: int):
        super(PriceTransformerModel, self).__init__()
        self.encoder_layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=nhead)
        self.transformer_encoder = nn.TransformerEncoder(self.encoder_layer, num_layers=num_encoder_layers)
        self.input_projection = nn.Linear(input_dim, d_model)
        self.output_projection = nn.Linear(d_model, 1)

    def forward(self, src: torch.Tensor) -> torch.Tensor:
        # src shape: (seq_len, batch, input_dim)
        src = self.input_projection(src)
        output = self.transformer_encoder(src)
        output = self.output_projection(output)
        return output
