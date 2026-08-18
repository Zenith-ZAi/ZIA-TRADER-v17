# Relatório de integração Binance Spot Testnet

> Nenhuma chave, assinatura, saldo ou valor sensível é exibido neste relatório. O smoke test não criou, cancelou nem modificou ordens.

## Implementação

Foi criado `execution/binance_adapter.py` com suporte a Binance Spot Testnet/Demo. O adapter utiliza HMAC-SHA256 para endpoints assinados, sincroniza o relógio pelo endpoint de servidor, consulta `exchangeInfo`, aplica `LOT_SIZE`, `PRICE_FILTER` e `MIN_NOTIONAL`, baixa candles reais, lê ticker/livro, consulta saldo e mantém o mapeamento de ordens para status/cancelamento.

A fachada `ExchangeConnector` agora seleciona `simulated`, `testnet` ou `demo`. O padrão permanece `simulated`. O adapter real rejeita hosts de produção e exige correspondência entre o modo e o host sandbox.

## Tentativa executada

A variável `BINANCE_BASE_URL` do arquivo fornecido foi auditada sem imprimir o valor e apontou para o host `testnet.binance.vision`. As credenciais estavam presentes e foram carregadas somente em memória durante o teste.

| Etapa | Resultado |
|---|---|
| Host Spot Testnet | Detectado |
| Endpoint público e `exchangeInfo` | Alcançados pelo adapter |
| HMAC e chamada privada | Executados pelo adapter |
| Saldo | Rejeitado pela Binance com `-2015` |
| Ordens enviadas | `0` |
| Diagnóstico | `BinanceAuthenticationError` |
| Suíte local | 19 testes aprovados |

A resposta `-2015 Invalid API-key, IP, or permissions for action` indica que a chave não foi aceita para aquela combinação de endpoint, IP ou permissões. Isso não é falha de conectividade do adapter. O teste foi interrompido antes de qualquer ordem.

## Configuração necessária

Crie ou confirme a chave no [Binance Spot Test Network](https://testnet.binance.vision/) ou no [Binance Demo Mode](https://demo.binance.com/), sem reutilizar chave de produção. Para Spot Testnet, use `BINANCE_MODE=testnet` e `BINANCE_BASE_URL=https://testnet.binance.vision/api`. Para Demo Mode, use `BINANCE_MODE=demo` e `BINANCE_BASE_URL=https://demo-api.binance.com/api`.

Confirme que a chave corresponde ao ambiente escolhido, que o acesso `USER_DATA` está permitido para saldo/status e que `TRADE` só seja habilitado quando for executar uma ordem de teste explicitamente aprovada. Se existir whitelist de IP, inclua o IP de saída do servidor que fará o smoke test. Nunca coloque chaves no `start.sh`, no GitHub ou em mensagens.

## Próximo teste

Depois de corrigir a chave no gerenciador de segredos, execute somente a leitura:

```bash
BINANCE_MODE=testnet ZIA_MODE=api ./start.sh
```

O teste de saldo e mercado deve ser repetido antes de qualquer criação ou cancelamento de ordem. A etapa de ordem de teste permanece deliberadamente bloqueada neste ciclo porque a autenticação privada ainda não foi validada.

## Referências

[1]: https://developers.binance.com/en/docs/products/spot/testnet/general-info "Binance Spot Testnet General Info"
[2]: https://developers.binance.com/en/docs/products/spot/testnet/rest-api "Binance Spot Testnet REST API"
[3]: https://developers.binance.com/en/docs/products/spot/demo-mode/general-info "Binance Spot Demo Mode General Info"
