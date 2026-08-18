# Log de validação do launcher

## Falha encontrada no anexo

O `start.sh` recebido não passou em `bash -n`: havia um subshell iniciado com `(` sem o fechamento correspondente. Além disso, o anexo usava `BINANCE_API_SECRET`, enquanto o projeto usa `BINANCE_SECRET_KEY`. O arquivo também continha credenciais privadas em texto claro.

## Correção aplicada

O launcher do repositório foi reescrito sem credenciais hardcoded, com `set -Eeuo pipefail`, resolução do diretório do projeto e modos explícitos:

```bash
ZIA_MODE=test ./start.sh
ZIA_MODE=api ./start.sh
ZIA_MODE=worker ./start.sh
```

As credenciais devem ser fornecidas pelo gerenciador de segredos do servidor ou por um `.env` local ignorado. As chaves recebidas no anexo devem ser revogadas/rotacionadas antes de qualquer uso.

## Execuções

| Comando | Resultado |
|---|---|
| `bash -n start.sh` | Aprovado |
| `ZIA_MODE=test ./start.sh` | 17 testes aprovados |
| `ZIA_MODE=api ./start.sh` + `GET /healthz` | HTTP 200; shutdown limpo |
| `ZIA_MODE=worker ./start.sh` por 8 segundos | Startup do worker aprovado; encerrado pelo timeout intencional |
| Varredura das chaves recebidas no repositório | Nenhuma ocorrência |
| `python3 -m compileall -q .` | Aprovado |
| `git diff --check` | Aprovado |

## Limite importante

O worker inicializado neste ambiente ainda usa o `ExchangeConnector` simulado do projeto. Essa validação não emitiu ordens reais, não acessou uma conta de exchange e não comprova integração Binance Testnet/Demo. A implementação de um adapter de exchange real em modo sandbox é uma etapa separada.
