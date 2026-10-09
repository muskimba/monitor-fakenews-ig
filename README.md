# monitor-fakenews-ig

Monitora perfis de notícias do Instagram que costumam publicar desinformação, analisa cada
postagem com o Claude no **contexto da campanha** (Lula, PT, eleição 2026) e organiza tudo
numa **planilha Google**: as fake news identificadas, os posts que as espalham, os desmentidos
e as respostas prontas para publicar.

O programa roda **localmente** (Agendador de Tarefas do Windows). O que fica online é só a
planilha, que é ao mesmo tempo o banco de dados e a tela de trabalho da equipe.

## Como funciona

```
Agendador do Windows (a cada 3h, 7h–23h)
        │
        ▼
 coletar ──► Instagram (instaloader, conta secundária logada)
        │        posts novos de cada perfil ativo
        ▼
 Claude analisa cada post (legenda + imagem)
   • humor no contexto da campanha (posicionamento, depreciativo, intensidade, alvos)
   • alegações factuais do post
   • a qual NOTÍCIA (fake news) o post pertence: uma já catalogada ou uma nova
        │
        ▼
 Planilha Google (online) ──► equipe valida, escreve desmentidos, aprova respostas
```

### A notícia é o centro

Uma **notícia** é a fake news em si (a narrativa, a alegação), não a postagem. Vários perfis
publicam a mesma notícia, cada um com sua postagem. O desmentido e as respostas pertencem à
notícia, então **uma resposta serve para todas as postagens dela, de qualquer perfil**.

A cada post, o Claude consulta o **catálogo de notícias**: se o post repete uma narrativa já
catalogada (mesmo com outras palavras, outra imagem, outro perfil), liga o post a ela; senão,
cria uma notícia nova (`N0001`, `N0002`…). Se ele separar por engano duas notícias que são a
mesma, junte com `mesclar-noticias`.

## A planilha: 1 arquivo, 6 abas

```
 perfis [P001] ─1:N─► postagens [shortcode]
                            │ 1:N
                            ▼
                      ocorrencias [shortcode:N0001]      (postagem X espalha notícia Y)
                            │ N:1
                            ▼
                      noticias [N0001] ──1:1──► desmentidos [noticia_id]
                                       ──1:N──► respostas [N0001-R1]
```

| Aba | O que guarda | Quem preenche |
|---|---|---|
| `perfis` | perfis monitorados (`P001`…), `ativo` sim/não, `ultima_coleta`, `status_ultima_coleta` | equipe cadastra `perfil`/`ativo`; robô completa id, link e status |
| `noticias` | catálogo de fake news (`N0001`…): título, alegação, palavras-chave, **qtd_postagens, qtd_perfis, perfis, primeira e última aparição** (recalculados a cada coleta) | Claude cria e agrupa; equipe valida |
| `postagens` | uma linha por post: link, legenda, **análise de humor**, alegações | robô; equipe valida |
| `ocorrencias` | ligação postagem ↔ notícia (N:N), `confianca`, `resposta_usada_id` | robô; equipe valida e anota a resposta publicada |
| `desmentidos` | um por notícia: `veredito`, `explicacao`, `fontes` (os links ficam só aqui) | equipe (ou rascunho do Claude, sempre revisado) |
| `respostas` | respostas prontas por notícia (`N0001-R1`…): curta, completa, comentário | Claude rascunha; equipe aprova |

Para responder um post: na aba `ocorrencias` pegue o `noticia_id`, filtre a aba `respostas`
por ele e use uma resposta `aprovada`; depois anote o `resposta_usada_id` e marque `respondida`.

## Análise de humor: contexto da campanha

| Coluna (aba `postagens`) | Significado |
|---|---|
| `relevante_campanha` | o post trata de Lula, PT, governo Lula ou da eleição de 2026 |
| `posicionamento` | `favoravel` / `neutro` / `desfavoravel` / `nao_se_aplica`, em relação a esses alvos |
| `depreciativo` | deprecia algum alvo da campanha (atacar outras pessoas não conta) |
| `intensidade` | 0 (nenhuma) a 3 (ofensa direta, apelido pejorativo, ataque a eleitores) |
| `alvos` | quais alvos da campanha foram depreciados |
| `tom`, `justificativa` | tom do post e o trecho que levou à classificação |

Os alvos, exemplos de termos pejorativos e a escala de intensidade ficam em
[contexto_campanha.md](contexto_campanha.md), que entra inteiro no prompt. **Para mudar os
critérios, edite esse arquivo**, sem mexer no código.

Regra principal: noticiário desfavorável, com fonte e em tom informativo, é `desfavoravel`,
mas **não** `depreciativo`.

## Validação humana

Tudo que o robô grava entra como `pendente`. Uma pessoa muda pela lista suspensa da coluna
`validacao_humana` (e preenche `validado_por`, `validado_em`, `obs_validacao`).

| Aba | Opções | Efeito |
|---|---|---|
| `noticias` | pendente, fake_confirmada, parcialmente_falsa, nao_e_fake, inconclusiva, duplicada | `fake_confirmada`/`parcialmente_falsa` + desmentido → `gerar-respostas` rascunha; `duplicada` sai do catálogo |
| `postagens` | pendente, analise_correta, analise_incorreta | revisão da análise de humor |
| `ocorrencias` | pendente, confirmada, descartada, respondida | o post espalha mesmo a notícia? já respondemos? (`descartada` não conta nos totais) |
| `respostas` | pendente, aprovada, reprovada | só use as `aprovada`; se todas forem `reprovada`, `gerar-respostas` rascunha de novo |

## Desmentidos e respostas: regras

- **Veredito honesto.** Use `falso` só quando as fontes sustentam; acusação sem prova é
  "não comprovado". Forçar "falso" tira a credibilidade da resposta.
- **Respostas nunca têm link** (comentário com link é penalizado/filtrado). Quando ajuda,
  citam a fonte pelo nome ("segundo a Polícia Federal", "como noticiou a CNN Brasil"), e não
  em todas: em geral só a completa. Há uma trava no código que remove qualquer link.
- As respostas usam **só** o que está no desmentido: nada inventado, sem atacar quem compartilhou.
- O Claude nunca decide sozinho o que é verdade: veredito e desmentido são validados pela equipe.

## Comandos

```powershell
.venv\Scripts\python -m monitor init-planilha                   # cria/ajusta abas, cabeçalhos e listas suspensas
.venv\Scripts\python -m monitor coletar                         # ciclo completo (é o que o agendador roda)
.venv\Scripts\python -m monitor gerar-respostas                 # rascunha respostas p/ notícias falsas com desmentido
.venv\Scripts\python -m monitor mesclar-noticias N0007 N0002    # junta a N0007 (duplicada) na N0002
.venv\Scripts\python -m monitor testar-perfil vejamais --limite 3   # testa coleta+análise sem gravar na planilha
.venv\Scripts\python -m monitor testar-analise "legenda de exemplo" # testa só a análise
```

## Instalação (novo colaborador)

Requer Windows, Python 3.10+ e o Google Cloud SDK (`gcloud`).

```powershell
git clone <url-deste-repositorio>
cd monitor-fakenews-ig
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Depois preencha o `.env` (nunca suba esse arquivo; ele já está no `.gitignore`):

1. **Planilha** — `PLANILHA_ID` é o trecho da URL da planilha entre `/d/` e `/edit`.
   Peça acesso à planilha da equipe ou crie uma vazia e rode `init-planilha`.
2. **Acesso à planilha, sem arquivo de chave** — a planilha é compartilhada como Editor com
   uma *service account*. Peça à pessoa responsável pelo projeto GCP o papel
   `Service Account Token Creator` nessa SA para a sua conta Google, faça
   `gcloud auth application-default login` e ponha o e-mail da SA em `GOOGLE_IMPERSONATE_SA`.
   O código usa seu login para gerar tokens temporários da SA.
3. **Instagram** — só para quem roda a coleta. Use uma **conta secundária**, nunca a pessoal:
   `.venv\Scripts\instaloader -l USUARIO` (você digita a senha) e preencha `IG_USER`.
4. **Claude** — chave da API Anthropic em `ANTHROPIC_API_KEY`.

## Agendamento (Agendador de Tarefas do Windows)

A cada 3 horas, das 7h às 23h, enquanto o PC estiver ligado e o usuário logado (troque o
caminho pela pasta do projeto):

```powershell
schtasks /Create /TN "MonitorFakeNewsIG" /SC DAILY /ST 07:00 /RI 180 /DU 16:00 /TR "powershell -NoProfile -ExecutionPolicy Bypass -File \"C:\caminho\monitor-fakenews-ig\scripts\rodar_coleta.ps1\""
```

Logs em `logs\coleta-AAAA-MM.log`. Para remover: `schtasks /Delete /TN "MonitorFakeNewsIG"`.

## Estrutura do código

| Arquivo | Responsabilidade |
|---|---|
| `monitor/__main__.py` | comandos da linha de comando |
| `monitor/pipeline.py` | fluxo do `coletar` e do `gerar-respostas` |
| `monitor/analise.py` | prompts e chamadas ao Claude (humor, agrupamento em notícias, respostas, trava de links) |
| `monitor/planilha.py` | estrutura das 6 abas, leitura/escrita, totais por notícia, mescla, acesso via service account |
| `monitor/instagram.py` | coleta com instaloader |
| `monitor/teste_perfil.py` | teste de um perfil sem planilha |
| `contexto_campanha.md` | alvos e critérios da análise de humor (editável) |
| `scripts/rodar_coleta.ps1` | o que o Agendador do Windows chama |
| `tests/` | testes automatizados (`.venv\Scripts\python -m pytest -q tests`) |

## Situação atual

- **Funcionando e testado:** planilha com as 6 abas, gravação, agrupamento em notícias, totais,
  validações, trava de links, acesso via service account sem chave; testes automatizados passando.
- **Testado parcialmente:** a análise e os desmentidos do primeiro teste (3 posts reais) foram
  feitos manualmente pelo Claude Code, pois a chave da API ainda não estava configurada.
- **Falta:** chave da API no `.env`, sessão do Instagram de uma conta secundária e o agendamento.
- **Em discussão:** opção `nao_comprovada` na validação de notícias (incluída no
  `gerar-respostas`) e um comando `gerar-desmentidos` (pesquisa na web + rascunho de veredito).

## Riscos e limitações

- **Scraping viola os termos do Instagram**: a conta de coleta pode ser bloqueada. Por isso:
  conta secundária, poucos perfis, poucas execuções por dia, no máximo 12 posts por perfil e
  pausas aleatórias. Sem login, o Instagram bloqueia já na primeira tentativa.
- Sessão expirada → `coletar` sai com código 2 e loga `Sessão do Instagram inválida`; rode
  `instaloader -l USUARIO` de novo.
- Só a 1ª imagem do carrossel / capa do vídeo é analisada (áudio e resto do vídeo, não).
- Erros transitórios da API do Claude não gravam o post: ele é tentado na próxima execução.
  Recusas do modelo ficam na coluna `erro`.
- O agrupamento automático às vezes erra: use `mesclar-noticias` e marque ocorrências `descartada`.
- O catálogo inteiro vai em cada análise (em cache). Com milhares de notícias o custo sobe;
  aí vale limitar o catálogo (ex.: últimos 90 dias), ainda não implementado.

## Custo do Claude

Modelo padrão `claude-opus-5-5` (US$ 4 / US$ 20 por milhão de tokens de entrada/saída),
esforço `medium`. Estimativa grosseira: **US$ 0,02–0,05 por post**. Ex.: 5 perfis × 10
posts/dia ≈ US$ 30–75/mês. Para baratear: `CLAUDE_EFFORT=low` ou
`CLAUDE_MODEL=claude-sonnet-5-5` (metade do preço).
