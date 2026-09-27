# Pesquisa de price action para OTC — NEXUS IA TRADER

## Conclusão prática

Não existe uma estratégia publicamente comprovada que garanta assertividade no OTC da IQ Option. A própria descrição da IQ Option explica que os preços OTC são gerados por modelos internos da plataforma, com menor transparência e comportamento diferente dos mercados regulares [1]. Portanto, a estratégia deve ser tratada como hipótese testável em paper trading, nunca como garantia de lucro.

A mudança recomendada é substituir o atual uso simplificado de `range_position` por uma leitura de **zonas**:

1. Identificar suporte e resistência por swing highs/lows recentes em candles da própria IQ Option.
2. Agrupar níveis próximos em zonas, em vez de tratar um preço exato como barreira.
3. Exigir que o preço esteja próximo de uma zona relevante.
4. Exigir rejeição clara da zona no candle fechado, por pavio e fechamento de volta para dentro da faixa.
5. Exigir confirmação da direção em M15/H1 e usar M1 apenas como gatilho.
6. Bloquear rompimentos ainda sem reteste e entradas após uma vela anormalmente ampla.

A literatura educacional descreve suporte e resistência como áreas onde o preço historicamente pausa ou reage, e ressalta que são zonas aproximadas, não linhas exatas [2]. Também descreve que um antigo suporte pode virar resistência após rompimento, e vice-versa, e que um sinal de price action ganha contexto quando aparece junto de um nível relevante [3].

## O que será testado no motor

- `support_level` e `resistance_level` derivados somente de máximas e mínimas dos candles M5.
- `support_touches` e `resistance_touches` para medir relevância mínima.
- `near_support` e `near_resistance` usando tolerância proporcional à volatilidade recente.
- Rejeição bullish: mínima testa a zona de suporte e o fechamento termina acima dela, com corpo positivo ou fechamento forte.
- Rejeição bearish: máxima testa a zona de resistência e o fechamento termina abaixo dela, com corpo negativo ou fechamento fraco.
- Engolfo opcional somente como confirmação adicional, não como sinal isolado.
- CALL perto de suporte e PUT perto de resistência; evitar CALL encostado em resistência e PUT encostado em suporte.
- Em tendência forte, permitir continuação somente após rompimento confirmado e reteste, nunca no primeiro impulso.

## Limitações

Suporte/resistência pode falhar, especialmente em períodos curtos. Indicadores baseados em dados passados podem atrasar reversões [2] [4]. A fonte oficial da IQ Option recomenda atenção a padrões simples, suporte/resistência e rompimentos, mas também reconhece riscos específicos do OTC, incluindo preços internos, menor liquidez e possível diferença em relação a mercados regulares [1]. Alertas regulatórios também destacam que payout assimétrico torna uma taxa de acerto de 50% insuficiente e que opções binárias envolvem riscos elevados [5].

## Critério de validação

A estratégia revisada deve ser comparada com a atual em amostras separadas, sem martingale e com entrada fixa. Nenhuma alteração deve ser considerada validada antes de pelo menos 100 resultados liquidados, com análise por ativo, direção e horário.

## Referências

[1]: https://blog.iqoption.com/en/otc-trading-on-iq-option-how-to-trade-securities-over-the-counter/ "OTC Trading on IQ Option – How to Trade Securities Over-the-Counter"
[2]: https://www.investopedia.com/trading/support-and-resistance-basics/ "Support and Resistance Basics"
[3]: https://priceaction.com/price-action-university/strategies/support-resistance-levels/ "Support and Resistance Levels Trading Strategy"
[4]: https://www.dukascopy.com/swiss/english/marketwatch/articles/binary-options-trading-signals/ "Binary Options Trading Signals"
[5]: https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/fraudadv_binaryoptions.html "CFTC/SEC Investor Alert: Binary Options and Fraud"
