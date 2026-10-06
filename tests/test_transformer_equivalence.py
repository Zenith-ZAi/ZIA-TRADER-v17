from __future__ import annotations

import warnings

import torch
import torch.nn as nn

from ai.price_transformer_model import PriceTransformerModel


class LegacySequenceFirstTransformer(nn.Module):
    """Referência da arquitetura pré-refinamento, mantida somente neste teste."""

    def __init__(self, input_dim: int, d_model: int, nhead: int, num_encoder_layers: int):
        super().__init__()
        self.encoder_layer = nn.TransformerEncoderLayer(d_model=d_model, nhead=nhead)
        self.transformer_encoder = nn.TransformerEncoder(self.encoder_layer, num_layers=num_encoder_layers)
        self.input_projection = nn.Linear(input_dim, d_model)
        self.output_projection = nn.Linear(d_model, 1)

    def forward(self, src: torch.Tensor) -> torch.Tensor:
        return self.output_projection(self.transformer_encoder(self.input_projection(src)))


def test_batch_first_transformer_matches_legacy_outputs_and_shape():
    torch.manual_seed(2026)
    dimensions = (5, 8, 2, 2)
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", message="enable_nested_tensor is True.*", category=UserWarning)
        legacy = LegacySequenceFirstTransformer(*dimensions)
    refined = PriceTransformerModel(*dimensions)
    legacy.load_state_dict(refined.state_dict())
    legacy.eval()
    refined.eval()
    sequence_first = torch.randn(13, 4, dimensions[0])

    with torch.no_grad():
        legacy_output = legacy(sequence_first)
        refined_output = refined(sequence_first)

    assert refined_output.shape == (13, 4, 1)
    torch.testing.assert_close(refined_output, legacy_output, rtol=1e-5, atol=1e-6)


def test_transformer_rejects_non_three_dimensional_input():
    model = PriceTransformerModel(5, 8, 2, 1)
    try:
        model(torch.zeros(13, 5))
    except ValueError as exc:
        assert "seq_len" in str(exc)
    else:
        raise AssertionError("shape inválido não deve ser aceito")
