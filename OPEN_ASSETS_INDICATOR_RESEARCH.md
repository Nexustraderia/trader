# Pesquisa: indicadores para pares abertos — NEXUS IA TRADER

## Conclusão

Não existe evidência confiável de que um único indicador respeite sempre os pares abertos ou produza assertividade constante em expirações de cinco minutos. As fontes técnicas consultadas recomendam combinar indicadores com funções diferentes e validar a regra em conta demo/backtest, porque médias móveis atrasam, RSI pode permanecer sobrecomprado/sobrevendido em tendências e qualquer indicador produz falsos sinais.

A combinação mais coerente para testar nos pares regulares é:

1. **EMA 20/50** para direção da tendência no M5 e contexto no M15.
2. **ADX com +DI/-DI** para medir força e direção auxiliar. ADX mede força, não direção; a direção deve vir das médias e dos componentes direcionais.
3. **MACD acima/abaixo de zero e histograma na mesma direção** para confirmar momentum.
4. **RSI como filtro de regime, não como gatilho isolado**: evitar CALL muito esticado e PUT muito esticado; em tendência, não tratar automaticamente RSI alto como reversão.
5. **ATR/volatilidade** para evitar mercado parado e candles anormalmente grandes.
6. **Candle M5 fechado** como gatilho, sem usar a vela ainda em formação.

## Regra testável proposta para pares abertos

### CALL

- EMA20 M5 acima da EMA50 M5;
- preço de fechamento M5 acima da EMA20;
- EMA20 M15 acima da EMA50 M15;
- ADX M5 >= 25 e +DI > -DI;
- MACD M5 acima de zero ou histograma crescente;
- RSI entre 52 e 68, evitando entrada depois de aceleração extrema;
- ATR/volatilidade dentro de uma faixa mínima e máxima;
- confirmação por candle M5 fechado.

### PUT

- EMA20 M5 abaixo da EMA50 M5;
- preço de fechamento M5 abaixo da EMA20;
- EMA20 M15 abaixo da EMA50 M15;
- ADX M5 >= 25 e -DI > +DI;
- MACD M5 abaixo de zero ou histograma decrescente;
- RSI entre 32 e 48;
- ATR/volatilidade dentro de uma faixa mínima e máxima;
- confirmação por candle M5 fechado.

### Não operar

- ADX M5 abaixo de 20;
- conflito entre EMA20/50 do M5 e M15;
- MACD contrário à tendência;
- RSI extremo sem confirmação de continuação;
- candle M5 ainda aberto;
- volatilidade insuficiente ou movimento excepcionalmente grande.

## Como testar sem excluir ativos

Todos os ativos regulares confirmados pela IQ Option permanecem no catálogo. Cada sinal deve registrar o conjunto de condições, a confiança efetiva, o ativo, a direção, o horário Brasília e os preços OPEN/CLOSE da vela M5. A nova regra deve ser comparada com a anterior em uma amostra separada de pelo menos 100 sinais, sem martingale e sem misturar os resultados antigos.

O histórico atual mostrou que PUT teve desempenho melhor que CALL, mas isso não prova uma vantagem permanente. Portanto, a nova regra deve usar a mesma lógica simétrica para as duas direções e permitir auditoria por ativo, direção e horário.

## Limitações e riscos

A Fidelity descreve o ADX acima de 25 como indicação de tendência forte e abaixo de 20 como ausência de tendência, mas também ressalta que ADX mede força, não direção. A FOREX.com destaca que médias móveis são atrasadas e que RSI, Bollinger e estratégias de tendência produzem falsos sinais; a recomendação é combinar ferramentas e validar em ambiente de demonstração. A Investopedia também recomenda combinar indicadores complementares, em vez de depender de um único sinal.

Essas referências são educacionais e não demonstram uma taxa de acerto específica para a IQ Option, OTC ou expiração M5. A CFTC/SEC alertam que opções binárias têm estrutura de pagamento assimétrica e riscos de fraude em algumas plataformas, incluindo alegações de manipulação de software. A FCA proibiu a venda de opções binárias a consumidores de varejo no Reino Unido por considerar os riscos inerentes e as perdas inesperadas relevantes.

## Referências

[1]: https://www.fidelity.com/bin-public/060_www_fidelity_com/documents/learning-center/Understanding-Indicators-TA.pdf "Fidelity — Understanding Indicators in Technical Analysis"

[2]: https://www.forex.com/en-us/trading-guides/trend-trading/ "FOREX.com — Trend Trading: Strategies, Indicators and Examples"

[3]: https://www.investopedia.com/top-7-technical-analysis-tools-4773275 "Investopedia — 7 Technical Indicators to Build a Trading Tool Kit"

[4]: https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/fraudadv_binaryoptions.html "CFTC/SEC — Binary Options and Fraud Investor Alert"

[5]: https://www.fca.org.uk/news/statements/fca-confirms-permanent-ban-sale-binary-options-retail-consumers "FCA — Permanent ban on retail binary options"
