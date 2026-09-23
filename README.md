# NEXUS IA TRADER

Bot de análise de mercado para Telegram. O sistema publica cenários analíticos em um canal privado e não envia ordens para corretoras.

## Estado atual

Esta é a primeira estrutura do projeto. O modo padrão é `TESTE` e ainda não há coleta automática de dados nem geração de sinais reais.

## Próximas etapas

1. Conectar e testar o Telegram.
2. Adicionar uma fonte autorizada de dados de mercado.
3. Implementar a primeira análise simples de tendência.
4. Adicionar notícias e calendário econômico.
5. Registrar sinais em modo simulado.

## Segurança

Nunca coloque tokens ou chaves no GitHub. Configure as variáveis diretamente no Render ou em um arquivo `.env` local que não seja versionado.

## Variáveis necessárias

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHANNEL_ID`
- `BOT_MODE` (`TESTE` por padrão)
- `PORT` (fornecida pelo Render)
