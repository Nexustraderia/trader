# NEXUS IA TRADER — Relatório de transferência

**Data da transferência:** 25 de setembro de 2026, horário de Brasília (UTC−3)  
**Autor:** Manus AI  
**Repositório:** [Nexustraderia/trader](https://github.com/Nexustraderia/trader)

## 1. Resumo executivo

O NEXUS IA TRADER é um bot de análise técnica para sinais de opções binárias em modo de paper trading. O sistema consulta exclusivamente dados da IQ Option, analisa múltiplos períodos de tempo e publica sinais em um canal privado do Telegram. Ele não envia ordens reais para a IQ Option.

A operação automática atualmente ativa é executada pelo GitHub Actions a cada cinco minutos. O fluxo descobre ativos abertos na IQ Option, incluindo OTC quando a própria IQ Option os disponibiliza, coleta candles M1, M5, M15 e H1, aplica a estratégia de confluência e publica somente sinais que atingem confiança mínima de 80/100. Após a expiração M5, outro ciclo consulta os candles da IQ Option, calcula WIN, LOSS ou VOID e publica o resultado no Telegram.

O primeiro obstáculo relevante foi a conectividade do Render com o endpoint de autenticação da IQ Option. O Render iniciava, mas sofria timeouts no login/WebSocket. O mesmo cliente funcionou no GitHub Actions, que possui uma rota de rede diferente. Por isso, o scanner automático foi deslocado para o GitHub Actions, enquanto o Render permanece como API/dashboard e serviço auxiliar.

## 2. Componentes e hospedagem

| Componente | Local atual | Função |
|---|---|---|
| Código principal | GitHub: `Nexustraderia/trader`, branch `main` | Fonte do backend, scanner e workflows |
| Serviço web | Render, serviço `nexus-ia-trader`, plano Free | Flask, endpoints de saúde, comandos e dashboard/API |
| URL conhecida do Render | `https://trader-f4z2.onrender.com` | Produção do backend Render |
| Dashboard visual | Projeto WebDev `nexus-ia-trader-dashboard` | Interface pública de acompanhamento |
| URL conhecida do dashboard | `https://3000-i5oasotoeaoc4g8jzbszd-7b0e5a83.us1.manus.computer` | Preview/serviço temporário do dashboard |
| Scanner automático | GitHub Actions | Execução periódica de análise e liquidação |
| Banco do Render | PostgreSQL Render, serviço `bancodedadostrader` | Persistência do backend Render, conforme `render.yaml` |
| Estado do scanner Actions | `runtime_state.json` versionado no GitHub | Pending, settled, preço de entrada/saída e resultados |
| Mensageria | Telegram Bot API | Sinais e resultados |

O dashboard WebDev é uma interface estática de observabilidade. O scanner ativo não depende do dashboard para executar. Fechar a página não interrompe o GitHub Actions.

## 3. Telegram atual

O bot em uso no GitHub Actions é **`@Nexusbotnovo_bot`**. O canal configurado é **`@NexusTraderIA`**. O bot novo foi adicionado ao canal com permissão de publicação e o teste direto de envio foi confirmado com sucesso.

O token do Telegram não deve ser colocado neste documento. O secret utilizado pelo GitHub Actions chama-se `TELEGRAM_BOT_TOKEN`. O canal é configurado no workflow como `TELEGRAM_CHANNEL_ID: "@NexusTraderIA"`.

O token do bot foi exposto durante a conversa de configuração. O próximo agente deve recomendar a revogação imediata no BotFather e a criação de um novo token. Depois, deve atualizar o secret `TELEGRAM_BOT_TOKEN` no repositório. Nunca imprimir o valor do token em logs, commits, prompts ou relatórios.

O link de afiliado atualmente usado nos sinais é:

`https://affiliate.iqoption.net/redir/?aff=232843&aff_model=revenue&afftrack=`

Ele está embutido em `app/main.py` e `tools/github_scanner.py`. Se o link for alterado, deve ser atualizado nos dois pontos ou centralizado em uma variável segura/configuração única.

## 4. Secrets e credenciais

Os valores não devem ser reproduzidos neste relatório. Devem ser lidos somente pelos ambientes autorizados.

### GitHub Actions

O workflow `.github/workflows/iq-option-scanner.yml` usa estes secrets:

- `IQ_OPTION_EMAIL`: e-mail da conta de teste da IQ Option.
- `IQ_OPTION_PASSWORD`: senha da conta de teste da IQ Option.
- `TELEGRAM_BOT_TOKEN`: token do `@Nexusbotnovo_bot`.

O GitHub CLI desta sessão conseguiu disparar workflows, mas uma consulta posterior de listagem de secrets retornou HTTP 403. Portanto, não presumir que uma credencial local tenha permissão para listar ou editar secrets. Se for necessário atualizar um secret, usar uma credencial GitHub com permissão apropriada ou solicitar autorização ao usuário.

### Render

O `render.yaml` declara estas variáveis:

- `BOT_MODE=TESTE`.
- `TELEGRAM_CHANNEL_ID=@NexusTraderIA`.
- `TELEGRAM_BOT_TOKEN`, valor secreto no painel do Render.
- `IQ_OPTION_EMAIL`, valor secreto no painel do Render.
- `IQ_OPTION_PASSWORD`, valor secreto no painel do Render.
- `DATABASE_URL`, fornecida pelo PostgreSQL Render `bancodedadostrader`.

Existe uma diferença importante entre a documentação antiga e a implementação atual: o README dizia que as credenciais IQ Option deveriam estar somente no Render, mas o scanner GitHub Actions agora precisa delas como secrets do GitHub. Não remover esses secrets enquanto o GitHub Actions for o executor automático.

### Regras de segurança

Não inserir senha, token do Telegram, token GitHub ou credencial IQ Option em arquivos versionados. Não repetir valores secretos na resposta ao usuário. Usar somente nomes de secrets e indicar o local de armazenamento. Os tokens enviados anteriormente no chat devem ser considerados comprometidos e rotacionados.

## 5. Arquivos principais

| Arquivo | Responsabilidade |
|---|---|
| `app/main.py` | Flask, comandos Telegram, endpoints `/health`, loops do Render e publicação antiga do bot |
| `app/iq_ws.py` | Cliente WebSocket somente leitura para login e candles IQ Option |
| `app/iq_data.py` | Catálogo IQ Option, ativos normais/OTC, normalização e candles |
| `app/market_data.py` | Adaptador que impõe política IQ Option only |
| `app/signal_engine.py` | Indicadores e estratégia de confluência M1/M5/M15/H1 |
| `app/paper_journal.py` | Paper trading do serviço Flask/Render e liquidação com SQLite/PostgreSQL |
| `tools/github_scanner.py` | Scanner ativo no GitHub Actions, persistência JSON, envio de sinais e resultados |
| `runtime_state.json` | Estado persistido pelo workflow: sinais pendentes e liquidados |
| `.github/workflows/iq-option-scanner.yml` | Agendamento e execução do scanner a cada 5 minutos |
| `.github/workflows/telegram-probe.yml` | Diagnóstico manual do bot Telegram |
| `.github/workflows/telegram-send-test.yml` | Teste manual de publicação no canal |
| `render.yaml` | Configuração declarativa do serviço Render |
| `requirements.txt` | Flask, requests, WebSocket e fork da `iqoptionapi` |

## 6. Fluxo operacional atual

### 6.1 Geração do sinal

1. O GitHub Actions inicia conforme o cron `*/5 * * * *` ou manualmente por `workflow_dispatch`.
2. O workflow instala Python 3.12 e as dependências de `requirements.txt`.
3. `tools/github_scanner.py` autentica na IQ Option usando o cliente WebSocket.
4. `available_signal_assets()` testa os ativos e mantém somente aqueles que retornam candles da IQ Option.
5. Os ativos OTC entram somente quando estão abertos e retornam candles da própria IQ Option.
6. Para cada ativo, o scanner coleta 80 candles de M1, M5, M15 e H1.
7. Candles antigos são rejeitados por verificações de frescor.
8. `analyze_with_confirmation()` aplica a direção e a confirmação da estratégia.
9. O sinal só é elegível quando `confluence_ok` é verdadeiro, `rsi_entry_ok` não bloqueia a entrada e a confiança é pelo menos 80.
10. O scanner envia a mensagem para `@NexusTraderIA`, com o botão de afiliado da IQ Option.
11. O scanner grava símbolo, direção, confiança, horário, preço de entrada e expiração em `runtime_state.json`.

### 6.2 Liquidação

1. Cada execução começa lendo `runtime_state.json`.
2. Sinais cujo `expires_at` ainda não chegou permanecem pendentes.
3. Para sinais vencidos, o scanner consulta candles M5 históricos da IQ Option.
4. O preço de entrada é comparado ao preço de saída.
5. `CALL` vence quando o preço de saída é maior; `PUT` vence quando é menor.
6. Preços iguais produzem `VOID`.
7. O resultado é enviado ao Telegram.
8. O arquivo JSON é atualizado e commitado pelo próprio workflow.

Os timestamps são mantidos em UTC para sincronização e exibidos nas mensagens como **UTC−3, horário de Brasília**.

## 7. Formato atual das mensagens

As mensagens públicas de sinal no scanner GitHub não exibem mais confiança, decisões individuais M1/M5/M15/H1, motivos técnicos, fonte de dados ou a frase “Modo TESTE”. O formato atual contém ativo, direção, horário de entrada, expiração M5 e a chamada:

```text
Sinais Exclusivos para a IQ OPTION
100% sem martingale.
Não tem conta na IQ OPTION?
Clique no botão abaixo e cadastre-se.
```

A mensagem possui o botão `CADASTRE-SE NA IQ OPTION` com o link de afiliado configurado.

Atenção: `app/main.py` contém uma implementação de publicação própria do Render. A alteração do novo texto foi aplicada ao scanner ativo em `tools/github_scanner.py`. Se o fluxo Render voltar a publicar sinais, será necessário alinhar `app/main.py` ao mesmo formato.

## 8. Estratégia e política de dados

A política obrigatória é **IQ Option exclusivamente**. Não reintroduzir Twelve Data, Yahoo Finance, Alpha Vantage ou qualquer outro fallback. Se o login, catálogo ou candle IQ Option falhar, o comportamento correto é não gerar sinal.

A análise usa quatro períodos:

- **M1:** gatilho e bloqueio da direção.
- **M5:** direção operacional e expiração padrão.
- **M15:** confirmação intermediária.
- **H1:** contexto maior.

O score/confiança é uma métrica interna do motor. Ele não deve ser interpretado como probabilidade estatística de vitória. A amostra deve ser avaliada pelos resultados liquidados, não pela confiança nominal.

## 9. Assertividade conhecida

No último cálculo verificável do arquivo `runtime_state.json`, havia:

- 18 sinais liquidados;
- 8 WIN;
- 10 LOSS;
- 0 VOID;
- 4 sinais pendentes;
- Assertividade resolvida de **44,44%**.

A separação registrada era:

- OTC: 6 sinais, 3 WIN, **50,00%**;
- Ativos normais: 12 sinais, 5 WIN, **41,67%**.

Essa amostra ainda é pequena. O próximo marco solicitado pelo usuário é aguardar **100 sinais liquidados** antes de fazer uma alteração importante na estratégia. Ao atingir 100 sinais, calcular total, WIN, LOSS, VOID, assertividade geral, OTC versus normal, CALL versus PUT, ativo, faixa de confiança e sequência temporal.

## 10. Limitações e riscos atuais

O cron do GitHub Actions é de cinco minutos. Não tentar mudar para dois minutos usando cron do GitHub Actions, pois isso não é suportado de forma confiável. Um intervalo menor exigiria um processo contínuo em outro ambiente.

O estado do scanner é commitado no mesmo repositório pelo workflow. Isso funciona para a operação atual, mas pode gerar conflitos se uma execução agendada e uma execução manual ocorrerem simultaneamente. A configuração de concorrência reduz esse risco, mas não substitui um banco persistente. Se o projeto crescer, migrar `runtime_state.json` para PostgreSQL ou outro armazenamento persistente.

O GitHub Actions pode atrasar workflows agendados. Como a liquidação depende do vencimento individual, o código deve manter sinais pendentes até que o horário de expiração tenha passado. Não liquidar antecipadamente.

O plano Free do Render pode adormecer. O GitHub Actions é o executor principal do scanner e não depende do Render permanecer acordado.

## 11. Validação e comandos úteis

Validação local:

```bash
python3 -m py_compile app/*.py tools/github_scanner.py
python3 -m unittest discover -s tests -v
```

Verificar workflows:

```bash
gh workflow list --repo Nexustraderia/trader
gh run list --repo Nexustraderia/trader --workflow=iq-option-scanner.yml --limit 10
```

Executar manualmente o scanner:

```bash
gh workflow run iq-option-scanner.yml --repo Nexustraderia/trader
```

Ler logs de uma execução:

```bash
gh run view RUN_ID --repo Nexustraderia/trader --log
```

Consultar o estado local sem mostrar credenciais:

```bash
python3 -c 'import json; d=json.load(open("runtime_state.json")); print({"pending": len(d.get("pending", [])), "settled": len(d.get("settled", []))})'
```

Nunca colocar tokens diretamente nesses comandos. Usar secrets do GitHub ou variáveis de ambiente protegidas.

## 12. Prompt para o próximo agente

> Você é o agente responsável por continuar o projeto **NEXUS IA TRADER** no repositório `https://github.com/Nexustraderia/trader`, branch `main`.
>
> O projeto é um bot de análise para opções binárias em **paper trading**. Ele deve usar **exclusivamente dados da IQ Option**. É proibido adicionar fallback para Twelve Data, Yahoo Finance, Alpha Vantage ou qualquer fonte externa de candles. Se a IQ Option falhar, não gerar sinal.
>
> O scanner automático ativo é `.github/workflows/iq-option-scanner.yml`. Ele executa a cada cinco minutos no GitHub Actions, instala Python 3.12, usa `tools/github_scanner.py`, consulta a IQ Option, inclui OTC somente quando a IQ Option retorna o ativo aberto e publica no canal Telegram `@NexusTraderIA` através do bot `@Nexusbotnovo_bot`.
>
> Os secrets necessários no GitHub Actions são `IQ_OPTION_EMAIL`, `IQ_OPTION_PASSWORD` e `TELEGRAM_BOT_TOKEN`. Não peça nem imprima os valores no chat. Não copie credenciais para arquivos. O token Telegram anteriormente foi exposto e deve ser revogado no BotFather e substituído no secret antes de qualquer operação sensível.
>
> O serviço Render continua configurado por `render.yaml` como `nexus-ia-trader`, plano Free, com URL de produção conhecida `https://trader-f4z2.onrender.com`. O Render usa `BOT_MODE=TESTE`, `TELEGRAM_CHANNEL_ID=@NexusTraderIA`, secrets IQ Option/Telegram e PostgreSQL `bancodedadostrader`. O scanner automático principal, porém, é o GitHub Actions porque o Render apresentou timeout na conexão IQ Option.
>
> O cliente IQ Option está em `app/iq_ws.py`; o adaptador está em `app/iq_data.py`; a política de fonte está em `app/market_data.py`; a estratégia está em `app/signal_engine.py`. A análise usa M1, M5, M15 e H1. A confiança mínima do scanner é 80. O padrão é M5 de expiração.
>
> `tools/github_scanner.py` mantém os sinais pendentes e liquidados em `runtime_state.json`. Cada sinal possui símbolo, direção, confiança, `entry_at`, `expires_at`, preço de entrada, preço de saída e resultado. Um resultado só pode ser calculado depois da expiração individual. `CALL` vence com saída maior, `PUT` vence com saída menor e igualdade é `VOID`. Os preços devem vir da IQ Option.
>
> As mensagens de sinal devem permanecer simples. Não adicionar de volta confiança, motivos técnicos, linhas M1/M5/M15/H1, fonte ou a frase “Modo TESTE” sem autorização expressa do usuário. O texto atual termina com “Sinais Exclusivos para a IQ OPTION”, “100% sem martingale”, instrução de cadastro e botão de afiliado. O link de afiliado já está no código; não inventar outro.
>
> O usuário decidiu aguardar 100 sinais liquidados antes de mudar a estratégia. Ao atingir esse número, apresentar relatório com assertividade geral, WIN/LOSS/VOID, OTC versus normal, CALL versus PUT, ativo, confiança e período. Não prometer que confiança técnica equivale a probabilidade de vitória.
>
> Antes de modificar o comportamento, ler `README.md`, `render.yaml`, `.github/workflows/iq-option-scanner.yml`, `tools/github_scanner.py`, `app/iq_ws.py`, `app/iq_data.py`, `app/market_data.py` e `app/signal_engine.py`. Validar com `py_compile`, testes disponíveis e um workflow manual quando necessário. Não apagar `runtime_state.json`, não sobrescrever histórico e não fazer push forçado.
>
> Sempre reportar ao usuário em português claro, informando o que foi verificado, o que mudou e qualquer limitação real. Nunca expor tokens, senhas ou valores de secrets.

## 13. Próximas ações recomendadas

A prioridade imediata é deixar o scanner acumular sinais até 100 liquidações. Durante esse período, não reduzir filtros para aumentar volume. O próximo agente deve somente corrigir falhas de execução, persistência, duplicação, timezone ou entrega Telegram que sejam comprovadas pelos logs.

Ao atingir 100 sinais, gerar um relatório estatístico e decidir, com base nos dados, se determinados ativos, faixas de confiança ou direções devem ser ajustados. Qualquer alteração de estratégia deve ser versionada em commit separado e acompanhada de nova amostra.

## Referências

[1]: https://github.com/Nexustraderia/trader "Repositório GitHub do NEXUS IA TRADER"
[2]: https://core.telegram.org/bots/api "Telegram Bot API"
[3]: https://docs.github.com/en/actions "GitHub Actions documentation"
[4]: https://render.com/docs "Render documentation"
[5]: https://iqoption.com "IQ Option"
