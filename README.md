# NEXUS IA TRADER

Bot de análise de mercado para Telegram. O sistema publica cenários analíticos em um canal privado e não envia ordens para corretoras.

## Estado atual

O modo padrão é `TESTE`. O bot coleta candles públicos para análise sob demanda e não envia ordens para corretoras.

## Comandos

- `/status` — verifica o estado do bot.
- `/analisar EUR/JPY` — compara M5, M15 e H1 e aplica o filtro NEXUS SENTINEL.
- `/noticias EUR/JPY` — consulta uma triagem de manchetes macroeconômicas recentes.
- `/sinal EUR/JPY` — cria um registro de paper trading somente quando houver CALL ou PUT confirmado.
- `/resultado ID WIN|LOSS|VOID` — fecha manualmente uma simulação.
- `/historico` — lista os registros simulados.
- `/stats` — mostra WIN, LOSS, VOID, pendentes e taxa da amostra; aceite `/stats EUR/JPY` para filtrar por ativo.
- `/ranking` — compara WIN, LOSS e taxa histórica entre os ativos.
- Publicação automática — desativada por padrão; quando habilitada, publica apenas paper signals com score mínimo, cooldown e limite diário.

O SENTINEL bloqueia uma eventual direção quando detecta manchetes de alto impacto. A fonte atual é um RSS público usado apenas como protótipo; ela não substitui um calendário econômico profissional nem representa integração oficial com o Investing.com. O diário é local ao serviço e pode ser reiniciado quando a instância gratuita do Render for recriada.

A publicação automática usa `AUTO_SIGNALS_ENABLED=true`, intervalo padrão de 5 minutos, score mínimo 80/100, cooldown de 20 minutos por ativo e máximo de 6 registros por dia. Mesmo habilitada, ela publica somente `PAPER TRADING`; não existe integração com corretoras.

## Próximas etapas

1. Integrar uma fonte autorizada e estruturada de calendário econômico.
2. Registrar análises em modo simulado para avaliação histórica.
3. Adicionar métricas de qualidade e trilha de auditoria.

## Segurança

Nunca coloque tokens ou chaves no GitHub. Configure as variáveis diretamente no Render ou em um arquivo `.env` local que não seja versionado.

## Variáveis necessárias

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHANNEL_ID`
- `BOT_MODE` (`TESTE` por padrão)
- `PORT` (fornecida pelo Render)

## Validação

Para executar os testes automatizados localmente:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile app/*.py
```

Os testes cobrem normalização de ativos, cálculo de score, bloqueio do SENTINEL e ciclo de vida do paper trading. O teste de candles depende de acesso à fonte pública de mercado.
