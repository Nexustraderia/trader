# Pesquisa de estratégia OTC — NEXUS IA TRADER

## Conclusão operacional

Não existe um indicador universalmente mais confiável para OTC. A própria IQ Option descreve seus ativos OTC como preços gerados por modelos internos da plataforma, sem depender diretamente de uma bolsa ou de um fluxo externo em tempo real. Por isso, indicadores calculados sobre as velas da própria IQ Option são mais coerentes do que importar sinais de outra fonte, mas nenhum indicador elimina o risco estrutural do produto.

A abordagem escolhida para a próxima iteração é:

1. filtro de regime para separar tendência de lateralização;
2. confirmação de tendência por média/momentum;
3. suporte e resistência derivados exclusivamente das velas IQ Option;
4. rejeição de entrada atrasada quando RSI/Stochastic estiverem extremos contra o timing;
5. confirmação M1/M5/M15 e H1 não contrário;
6. validação em nova amostra sem misturar o histórico atual.

## O que as fontes sustentam

- A IQ Option afirma que o OTC usa modelos internos, tem menor transparência de preços, liquidez limitada e pode apresentar comportamento diferente do mercado regular. O artigo recomenda observar padrões simples de price action, suporte/resistência e rompimentos, sem tratar isso como garantia.
- A Dukascopy organiza indicadores em tendência, momentum, volatilidade e volume e cita médias, RSI, MACD, Stochastic, ATR e Bollinger. Isso apoia combinar funções diferentes, mas não prova que um indicador específico tenha vantagem no OTC da IQ Option.
- A IG destaca que indicadores interpretam dados passados, não garantem lucro e funcionam melhor como confirmação conjunta. Também alerta que RSI pode permanecer extremo durante tendências fortes e que MACD pode gerar sinais falsos em lateralização.
- A CFTC/SEC alertam que opções binárias têm estrutura de ganho/perda assimétrica e que, em alguns ambientes, o retorno esperado pode ser negativo mesmo com 50% de acerto.

## Implicação para o projeto

Com payout de 90%, o ponto de equilíbrio matemático é aproximadamente 52,63% de acerto antes de outros custos. Os dois blocos observados (11/9 e 5/15) somam 16 WIN e 24 LOSS em 40 sinais, ou 40%, abaixo do equilíbrio. O segundo bloco sugere que liberar entradas com RSI extremo piorou a seleção; essa regra não deve permanecer sem validação.

## Fontes

1. IQ Option — OTC Trading on IQ Option: https://blog.iqoption.com/en/otc-trading-on-iq-option-how-to-trade-securities-over-the-counter/
2. Dukascopy Bank SA — Binary Options Trading Signals: https://www.dukascopy.com/swiss/english/marketwatch/articles/binary-options-trading-signals/
3. IG — What are trading indicators?: https://www.ig.com/en/trading-strategies/10-trading-indicators-every-trader-should-know-NEW-190604
4. CFTC/SEC — Binary Options and Fraud: https://www.cftc.gov/LearnAndProtect/AdvisoriesAndArticles/fraudadv_binaryoptions.html
5. FCA — Permanent ban on sale of binary options to retail consumers: https://www.fca.org.uk/news/statements/fca-confirms-permanent-ban-sale-binary-options-retail-consumers
