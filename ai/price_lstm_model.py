import torch
import torch.nn as nn

class PriceLSTMModel(nn.Module):
    def __init__(self, input_size, hidden_size, num_layers, output_size, dropout=0.1):
        super(PriceLSTMModel, self).__init__()
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        
        self.lstm = nn.LSTM(input_size, hidden_size, num_layers, batch_first=True, dropout=dropout)
        self.fc = nn.Linear(hidden_size, output_size)
        
    def forward(self, x):
        # x shape: (batch_size, sequence_length, input_size)
        
        # Initialize hidden and cell states
        h0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(x.device)
        c0 = torch.zeros(self.num_layers, x.size(0), self.hidden_size).to(x.device)
        
        # Forward propagate LSTM
        out, _ = self.lstm(x, (h0, c0))  # out: (batch_size, sequence_length, hidden_size)
        
        # Decode the hidden state of the last time step
        out = self.fc(out[:, -1, :])
        return out

# Exemplo de uso (para fins de demonstração, não será executado diretamente aqui)
# if __name__ == "__main__":
#     input_size = 10  # Ex: OHLCV, indicadores, etc.
#     hidden_size = 128
#     num_layers = 2
#     output_size = 1 # Previsão de preço
#     
#     model = PriceLSTMModel(input_size, hidden_size, num_layers, output_size)
#     
#     # Exemplo de dados de entrada: (batch_size, sequence_length, input_size)
#     batch_size = 1
#     sequence_length = 30
#     dummy_input = torch.rand(batch_size, sequence_length, input_size)
#     
#     output = model(dummy_input)
#     print(f"Output shape: {output.shape}") # Esperado: (batch_size, 1)
