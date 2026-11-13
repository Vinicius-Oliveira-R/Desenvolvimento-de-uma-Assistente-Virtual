# Correções da auditoria de correspondência com a monografia

Base examinada: `01193e795d6e8c92a496b0042263a9dad76d95b1`.
A implementação e seus testes evoluem juntos nesta PR. Isso não certifica produção,
acessibilidade, adequação clínica, LGPD ou ausência de vulnerabilidades.

## Mudanças e critérios

| Achado | Correção implementada | Evidência automatizada |
|---|---|---|
| C01 | `/assistant/chat` valida usuário ativo; rotas legadas de leitura exigem autenticação; a escrita legada retorna 410 sem reservar | Autorização em todas as rotas do assistente |
| C02 | Comando administrativo sem senha padrão; criação inicial não promove contas; redefinição é explícita e revoga tokens | Criação, conflito, redefinição e versão de token |
| C03 | Treino/inferência sob prazo configurável, fallback PADRAO e máximo de uma tarefa pendente por processo | Exceções, NaN, fora de faixa, timeout e limite de threads |
| C04 | Verificação transacional de interseções e constraints/triggers do banco; lotes são atômicos | Interseção parcial, inclusão, adjacência, repetição e SQL direto |
| C05 | Critério de aceite explícito: média de F1 macro nos cinco folds >= 0,80 | `test_ml_profile.py` e relatório JSON de `ml.train` |
| C06 | Perfil simplificado pagina até duas vagas e uma instrução, contando cada opção como unidade; preferência explícita | Paginação e contador de unidades |
| C07 | CPF com dígitos verificadores, nascimento válido, edição autorizada de e-mail/telefone, ativação de usuários/médicos | Entradas inválidas, edição por proprietário/equipe e rejeição de acesso alheio |
| C08 | Segredo obrigatório, HS256, expiração entre 1 e 480 minutos, bcrypt >=12, limite persistente de login | Configuração inválida, expiração, usuário inativo, 429 e janela de tentativas |

A remarcação pelo chat seleciona origem e destino e usa transferência atômica, sem
cancelar a consulta antiga antes da confirmação. IDs enviados no contexto são
reconferidos no banco quanto à titularidade, estado e disponibilidade.

## Publicação (não executar testes no Neon)

1. Fazer backup e ensaiar a migração em uma cópia de homologação.
2. Configurar `DATABASE_URL` e `SECRET_KEY` (chave aleatória exclusiva, >=32 caracteres).
   Não reutilizar os valores de CI e não colar credenciais em logs/issues.
3. Executar `python -m app.backend.migrate --check` na raiz. A pré-verificação recusa
   sobreposições preexistentes, datas inválidas e e-mails duplicados sem considerar caixa.
4. Executar `python -m app.backend.migrate --apply` com a role proprietária do schema.
   A migração é aditiva, idempotente e transacional no PostgreSQL. Instala `btree_gist`,
   campos `ativo`, `token_version`, a tabela de contadores e a exclusion constraint.
   Não apaga, cancela nem corrige registros existentes automaticamente.
5. Publicar backend e frontend da revisão validada. Tokens anteriores sem versão deixam
   de ser aceitos: será necessário novo login. Não apagar usuários, consultas ou sessões
   para resolver isso.
6. Se a senha padrão antiga tiver sido usada, redefini-la usando o comando abaixo;
   remover o texto do arquivo não revoga uma credencial que já foi cadastrada.

`python -m app.backend.create_gestor` cria somente o primeiro gestor.
`python -m app.backend.create_gestor --redefinir` redefine um gestor ativo existente,
com entrada oculta e confirmação explícita do destino. Não há promoção silenciosa.
O `seed.py` é exclusivamente demonstrativo e não deve ser executado em produção.

Os campos de ativação não apagam consultas antigas. Desativar o usuário invalida seus
tokens; desativar um médico impede novas vagas/reservas e preserva seu histórico.
A verificação do CRM é cadastral; não há consulta automatizada ao conselho profissional.

## Testes e resultados reproduzíveis

O workflow `backend-audit.yml` utiliza SQLite temporário e PostgreSQL 16 em container.
Não recebe segredo do Neon. O teste PostgreSQL recria tabelas: `TEST_POSTGRES_URL`
NUNCA deve apontar para produção. O workflow do frontend valida os templates e sessões.

```bash
python -m pytest app/backend/tests -q
python -m app.backend.ml.train --output evidence/classifier.json
cd app/frontend
python manage.py test assistant --settings=setup.test_settings
```

O JSON registra commit, dependências, hash e distribuição do corpus, parâmetros do
Random Forest, folds, previsões fora do treino, matriz de confusão, acurácia e F1.
O corpus sintético não demonstra identificação de idade real nem benefício para pacientes.
Não se inventa p95: o requisito de desempenho exige ensaio de carga específico.

## Definições que devem orientar a monografia

As cinco features são `taxa_erros`, `complexidade`, `hesitacao`, `vagueza` e `informalidade`.
A primeira mede desvios de escrita por regras, não taxa de fallback do reconhecedor.
O PLN de intenção usa spaCy com Matcher/EntityRuler; Random Forest seleciona estilo.
A fórmula de Flesch é `248.835 - 1.015*(palavras/frases) - 84.6*(silabas/palavras)`;
as sílabas são aproximadas por grupos vocálicos. O modelo usa 200 árvores, folhas com
mínimo 2 amostras, pesos balanceados e semente 42. A avaliação é estratificada em cinco folds.
A suavização usa peso `min(1, palavras/8)`, início 1.0 e limiar 0.5. Em falha do ML, o
perfil automático é PADRAO; o paciente pode pedir `modo simples`, `modo padrão` ou
`modo automático` sem que isso modifique sua agenda.

No estilo simplificado, cada item numerado conta como uma unidade. Cabeçalhos sem
pontuação terminal não contam como sentença; abreviações Dr./Dra. também não.
Listas longas de consultas são resumidas em duas entradas com acesso explícito à lista
completa em Meus Agendamentos. Nada é reservado ao listar opções.

## Limites operacionais

O prazo de inferência limita a espera HTTP, mas não mata código nativo: uma tarefa
que não termine mantém o processo em fallback, sem criar threads ilimitadas.
O rate limit é persistido por HMAC de conta e origem, não e-mail/IP em texto simples;
não confia em cabeçalhos de proxy arbitrários. Configure proxies confiáveis no Uvicorn
conforme a implantação e dimensione os limites sem remover a proteção.
As alterações na PR não redefinem segredos do Render, não removem credenciais do
histórico Git e não executam migrações ou alterações no Neon automaticamente.
