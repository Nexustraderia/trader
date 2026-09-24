# NEXUS IA TRADER

Bot de análise de mercado para Telegram. O sistema publica cenários analíticos em um canal privado e não envia ordens para corretoras.

## Estado atual

O modo padrão é `TESTE`. O bot coleta candles públicos para análise sob demanda e não envia ordens para corretoras.

## Comandos

- `/status` — verifica o estado do bot.
- `/analisar EUR/JPY` — compara M1, M5, M15 e H1 e aplica o filtro NEXUS SENTINEL.
- `/noticias EUR/JPY` — informa que o módulo de notícias está temporariamente desativado.
- `/sinal EUR/JPY` — cria um registro de paper trading somente quando houver CALL ou PUT confirmado.
- `/resultado ID WIN|LOSS|VOID` — fecha manualmente uma simulação.
- `/historico` — lista os registros simulados.
- `/stats` — mostra WIN, LOSS, VOID, pendentes e taxa da amostra; aceite `/stats EUR/JPY` para filtrar por ativo.
- `/ranking` — compara WIN, LOSS e taxa histórica entre os ativos.
- Publicação automática — desativada por padrão; quando habilitada, publica apenas paper signals com score mínimo, cooldown e limite diário.

O módulo de notícias está temporariamente fora do fluxo operacional para evitar falsos bloqueios. Ele poderá ser retomado no futuro somente com uma fonte estruturada e autorizada. O M1 é usado apenas como gatilho de entrada: ele confirma ou bloqueia a direção definida por M5/M15/H1, mas nunca cria um sinal sozinho.

Para candles intraday, o bot tenta primeiro a IQ Option em modo somente leitura. Se a conexão IQ Option falhar, `IQ_OPTION_STRICT=false` permite fallback para Twelve Data quando `TWELVEDATA_API_KEY` está configurada e, depois, para a Yahoo Finance Chart API. Com `IQ_OPTION_STRICT=true`, a falha da IQ Option é propagada e nenhum fallback é usado. As chaves devem ser configuradas somente no Render, nunca no GitHub.

A publicação automática usa `AUTO_SIGNALS_ENABLED=true`, varredura de 60 segundos, score mínimo 80/100, cooldown de 20 minutos por ativo e máximo de 6 registros por dia. Mesmo habilitada, ela publica somente `PAPER TRADING`; não existe integração com corretoras.

Resultados liquidados como `WIN` e `LOSS` são enviados ao Telegram com as artes correspondentes em `app/assets/win.png` e `app/assets/loss.png`. A imagem e o texto são tratados como uma entrega única: se o envio da foto falhar, o resultado fica aguardando e é reenviado automaticamente.

Cada sinal tem seu próprio `entry_at` e `expires_at`: o resultado só é calculado depois do fechamento da vela M5 de expiração daquele sinal. O loop de liquidação consulta os vencimentos periodicamente, mas não substitui o horário individual de cada entrada.

O SQLite mantém o sinal e o resultado fechado até que o Telegram confirme o envio da imagem junto com o texto. Se o Render, a rede ou o Telegram falhar, a entrega permanece pendente e é tentada novamente nos ciclos seguintes, em vez de ser descartada. Para conservar o banco entre deploys, configure `PAPER_DB_PATH` para um volume persistente montado em `/var/data/signals.sqlite3`; sem armazenamento persistente, o plano gratuito pode recriar o filesystem e apagar o histórico.

A página inicial executa uma verificação no endpoint `/health` a cada cinco minutos enquanto estiver aberta no navegador. Isso gera tráfego de entrada e pode reduzir o adormecimento por inatividade, mas não substitui um processo sempre ativo: se a página for fechada, o serviço poderá dormir conforme as regras do Render Free.

Depois do primeiro envio de cada arte, o bot armazena o `file_id` fornecido pelo Telegram e reutiliza esse identificador. Assim, as mensagens seguintes enviam imagem e texto sem fazer upload repetido do arquivo pesado.

Opcionalmente, `WIN_STICKER_FILE_ID` e `LOSS_STICKER_FILE_ID` substituem a arte por um sticker. Como stickers não aceitam legenda, o bot envia o sticker e, em seguida, o texto completo do resultado.

## Próximas etapas

1. Acumular histórico de paper trading para avaliar desempenho por ativo.
2. Registrar análises em modo simulado para avaliação histórica.
3. Adicionar métricas de qualidade e trilha de auditoria.

## Segurança

Nunca coloque tokens ou chaves no GitHub. Configure as variáveis diretamente no Render ou em um arquivo `.env` local que não seja versionado.

## Variáveis necessárias

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHANNEL_ID`
- `BOT_MODE` (`TESTE` por padrão)
- `PORT` (fornecida pelo Render)
- `PAPER_DB_PATH` (use `/var/data/signals.sqlite3` somente quando houver volume persistente montado)

## Validação

Para executar os testes automatizados localmente:

```bash
python3 -m unittest discover -s tests -v
python3 -m py_compile app/*.py
```

Os testes cobrem normalização de ativos, cálculo de score, bloqueio do SENTINEL e ciclo de vida do paper trading. O teste de candles depende de acesso à fonte pública de mercado.
