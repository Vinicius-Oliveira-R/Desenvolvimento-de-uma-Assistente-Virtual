# Revisão da conversa do paciente: confirmações, estilo e retomada

Base examinada: `7d42a46` (main). Os problemas foram reproduzidos nessa base antes das
correções, pela rota `/api/assistant/chat` e com o contexto devolvido pela API.
Esta revisão não altera o schema do banco e não exige migração. Ela altera o contrato
entre frontend e backend: os dois devem ser publicados juntos (ver "Publicação").

## Problemas confirmados na base

| Situação | Comportamento em `7d42a46` |
|---|---|
| Vaga escolhida + "pode repetir?" / "quero entender" | marcava a consulta |
| Pedido de troca da clínica + "pode repetir?" | aceitava a troca |
| Pedido da clínica ou cancelamento + "não sei" | abandonava a pergunta e iniciava busca de Clínica Geral |
| Cancelamento pendente + "como assim?" | descartava a pergunta pendente |
| "dois", "opção dois", "primeira" | não eram reconhecidos |
| "3" com duas vagas | repetia a lista sem explicar |
| "segunda" com duas vagas | virava segunda-feira sem perguntar |
| "mudar minha consulta de sexta para segunda à tarde" | era lido como "listar consultas" |
| Estilo | alternava IDOSO/PADRAO a cada mensagem; rótulo e probabilidade na resposta |
| Atualizar a página | voltava à saudação com uma confirmação pendente na sessão |
| Login com HTTP 429 | "sistema de agendamento indisponível" |

## Mudanças e evidências

| Requisito | Implementação | Testes |
|---|---|---|
| 1. Confirmações | `replies.LeitorDeRespostas`: só a frase inteira de concordância autoriza; perguntas e dúvidas reapresentam a etapa. `AcaoPendente.pergunta` explicita a última pergunta; só as de confirmação gravam. Botões nomeados com `proposta` por pergunta (`orchestrator._com_proposta`) e validação por pergunta (`BOTOES_POR_PERGUNTA`). Revalidação antes de gravar e respostas idempotentes para clique duplo (`dialogue._ja_registrada`, `rescheduling.confirmar_troca`). A confirmação vale para o horário exibido: se a clínica mudou a consulta depois da pergunta, nada é gravado e a pergunta é refeita com os dados atuais. | `test_conversa_confirmacao.py`, `test_conversa_remarcacao.py`, `test_conversa_revisao.py` |
| 1. Resultado incerto | Front-end distingue "sem conexão" (nada mudou) de "resposta não chegou" e, se havia confirmação pendente, orienta a conferir *Minhas consultas*. | `test_chat_interface.py` |
| 2. Estilo | `communication_style.PoliticaDeEstilo`: pedido explícito > pedido de ajuda > idade do cadastro (limiar `ASSISTENTE_IDADE_PASSO_A_PASSO`, padrão 60) > classificador com histerese. `core/idade.py` calcula anos completos. A resposta da API não traz perfil, probabilidade ou heurísticas; a evidência do classificador viaja cifrada no contexto (`CofreDeEvidencia`). Uma dúvida reapresenta as mesmas opções; as páginas seguintes usam o novo estilo. | `test_conversa_estilo.py`, `test_chat_interface.py`, `test_fluxo_integrado.py` |
| 3. Escolhas e mensagens | Número, extenso, ordinal e referência a horário; esclarecimento de ambiguidade; opção inexistente explicada com as opções reais. Resultados distintos: `sem_profissional`, `sem_horarios` e aviso `horario_reservado`; aviso `fora_do_periodo` antes da escolha. Remarcação mostra atual e proposto; cancelamento identifica a consulta. | `test_conversa_escolhas.py`, `test_conversa_mensagens.py` |
| 4. Retomada e tela | `POST /api/assistant/retomar`; *Novo agendamento* via POST; abertura com três botões; botões antigos desativados na tela e recusados no backend; rótulo do campo, região de anúncio (`role="status"`), menu recolhível no celular. | `test_conversa_retomada.py`, `test_chat_interface.py`, `test_fluxo_integrado.py` |
| 5. Login 429 | `retry_after.py` lê segundos ou data HTTP; prazo arredondado para cima com singular/plural; sem prazo válido, mensagem de espera genérica. Sem novas tentativas automáticas. | `test_login_tentativas.py`, `tests/test_retry_after.py`, `test_fluxo_integrado.py` |

## Decisões que merecem validação

- **Abertura com três botões para quem começa passo a passo.** O pedido lista as três
  opções na abertura e também "até duas opções" para quem tem 60 anos ou mais. A abertura
  segue a lista explícita; o limite de duas vale para as vagas e para cada pergunta do fluxo.
- **Cadastro sem data válida começa passo a passo**, mantendo a escolha inclusiva já
  documentada no TCC (custo assimétrico do erro). A mensagem inicial tem até três unidades.
- **O classificador não decide o primeiro estilo.** Ele acumula evidência a partir de
  mensagens com quatro ou mais palavras; cada mensagem move no máximo metade da evidência e
  a troca exige cruzar 0,25 ou 0,75, o que pede ao menos três mensagens longas coerentes.
  O rótulo IDOSO do corpus sintético é lido só como evidência a favor do passo a passo.
- **"Mostre mais horários"** amplia a quantidade por vez (mantendo as opções já vistas);
  "mais horários" continua trazendo a próxima página.
- **"Marcar consulta" sem clínico geral cadastrado** pergunta a especialidade, desde que
  exista algum profissional ativo.
- **Pergunta de remédio no meio de um agendamento** explica o limite e mantém a etapa aberta.

## Publicação

1. Não há migração de banco. A variável opcional `ASSISTENTE_IDADE_PASSO_A_PASSO` tem padrão 60.
2. Publicar backend e frontend da mesma revisão: o frontend novo usa `/assistant/retomar`,
   `opcoes` e `estilo`; o frontend antigo lia `perfil`, que deixou de existir.
3. Conversas em andamento no momento da troca de versão continuam válidas (campos antigos do
   contexto são ignorados), mas botões só existem a partir da nova versão.

## Revisão independente

Uma segunda revisão do código, feita sobre o diff e com sondas próprias, apontou oito
problemas antes da abertura da PR: esclarecimento numa etapa de confirmação que mantinha o
horário anterior pendente; cancelamento não vinculado ao horário exibido; frases com verbo
("sim, pode remarcar", "não sei se quero cancelar") que trocavam de assunto; dúvida que
encolhia a lista; aviso de fora do período perdido após vaga ocupada; evidência do
classificador legível no contexto; lista de recusados sem limite; hora citada exibida fora de
contexto. Todos foram corrigidos e têm regressões em `test_conversa_revisao.py` ou nos
arquivos do tema.

## Limitações

- Os testes usam dados fictícios e banco descartável; não comprovam usabilidade real,
  acessibilidade completa nem compreensão por pessoas idosas.
- A leitura de respostas é determinística e baseada em listas de frases; formas não previstas
  caem na reapresentação da etapa, nunca em gravação.
- A verificação visual em 320 e 360 px, a navegação por teclado e o anúncio do leitor de
  tela foram implementados e testados na marcação HTML, mas não num navegador real.
