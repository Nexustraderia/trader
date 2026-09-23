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

O SENTINEL bloqueia uma eventual direção quando detecta manchetes de alto impacto. A fonte atual é um RSS público usado apenas como protótipo; ela não substitui um calendário econômico profissional nem representa integração oficial com o Investing.com. O diário é local ao serviço e pode ser reiniciado quando a instância gratuita do Render for recriada.

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
