# Contrato — Filmes a Dois

App para um casal receber as MESMAS recomendações de filmes, calculadas a partir dos questionários e notas dos dois.
Idioma da interface: português do Brasil. Região de streaming: BR.

## Stack e arquivos (dono de cada arquivo)
| Caminho | Dono |
|---|---|
| `public/index.html`, `public/styles.css`, `public/app.js`, `public/*` | Sabiá (frontend) |
| `README.md` | Sabiá |
| `api/index.py`, `api/_core/__init__.py`, `api/_core/storage.py`, `api/_core/routes.py`, `dev.py`, `vercel.json`, `requirements.txt`, `.env.example`, `.gitignore`, `tests/test_api.py` | Jaguar (backend: API, armazenamento, servidor local, deploy) |
| `api/_core/tmdb.py`, `api/_core/recommender.py`, `tests/test_tmdb.py`, `tests/test_recommender.py` | Tucano (cliente TMDB + algoritmo do casal) |
| `CONTRATO.md` | Orquestrador (ninguém mais edita) |

## Contrato interno do backend (Jaguar ↔ Tucano)
Estado do casal guardado pelo Jaguar (chave `couple:<CODE>`), passado ao Tucano como dict:
```
Couple = { code: str, created_at: str,
           members: { <member_id>: { name, token, quiz: Quiz|null, ratings: { "<tmdb_id>": int 1-5 } } },
           watchlist: { "<tmdb_id>": WatchItem }, dismissed: [int] }
```
`api/_core/tmdb.py` (Tucano) expõe, todas retornando dicts no formato `Movie` (ou listas deles) e levantando `TMDBError(msg)` em falha:
- `get_options() -> {"genres": [...], "providers": [...]}`
- `seed_movies() -> [Movie]`
- `search(q: str) -> [Movie]`
- `movie(tmdb_id: int) -> Movie`
`api/_core/recommender.py` (Tucano) expõe:
- `recommend(couple: dict, limit: int = 20) -> [RecMovie]` — função pura em relação ao armazenamento (só chama `tmdb`); o Jaguar cuida do cache.
O Jaguar importa só esses nomes; não edita os arquivos do Tucano. Até o Tucano terminar, o Jaguar pode testar com mocks em `tests/test_api.py`.

- Hospedagem: Vercel. Frontend estático em `public/` (HTML/CSS/JS puro, sem build, sem Node). Backend: UMA função Python `api/index.py` (classe `handler(BaseHTTPRequestHandler)`), com `vercel.json` reescrevendo `/api/(.*)` para ela.
- Backend só com biblioteca padrão do Python 3.12+ (urllib, json). Sem dependências externas.
- Variáveis de ambiente: `TMDB_API_KEY` (v3) ou `TMDB_READ_TOKEN` (v4 bearer); `KV_REST_API_URL` + `KV_REST_API_TOKEN` (Upstash Redis via Vercel; aceitar também `UPSTASH_REDIS_REST_URL`/`UPSTASH_REDIS_REST_TOKEN`). Sem as do Redis → armazenamento em arquivo `data/dev-db.json` (modo local).
- Local: `python dev.py` serve `public/` e `/api/*` em http://localhost:8000 usando o mesmo handler.

## Identidade (sem login)
- Um casal tem `code` (6 caracteres, ex. `K7P2QX`). Cada membro tem `member_id` e `token` secreto.
- O frontend guarda `{code, member_id, token, name}` no localStorage e envia em TODA requisição autenticada os headers `X-Code` e `X-Token`.
- Link de convite: `/?convite=CODE`. Máximo 2 membros por casal.
- Erros: status HTTP adequado + corpo `{"error": "mensagem em português"}`. 401 = token inválido; 404 = casal não existe; 409 = casal cheio.

## Tipos
```
Member  = { id: str, name: str, quiz_done: bool, ratings_count: int }
Movie   = { tmdb_id: int, title: str, year: int|null, poster_url: str|null, overview: str,
            genres: [str], runtime: int|null, vote: float, providers: [{name: str, logo_url: str}] }
RecMovie = Movie + { match: int (0-100), reasons: [str],    // reasons em pt-BR, curtas, ex. "Os dois amam comédia"
            seen_by: [{ member_id: str, name: str, rating: int 1-5 }] }  // quem já viu (avaliou); [] se ninguém
WatchItem = Movie + { status: "quero_ver"|"assistido", added_by: str (member_id),
                      ratings: { <member_id>: int 1-5 } }
Quiz = {
  generos_amo:   [int],        // ids de gênero TMDB (máx 5)
  generos_veto:  [int],        // ids que a pessoa não aguenta
  humores:       [str],        // de: "rir","chorar","tensao","pensar","aventura","romance","medo"
  epocas:        [str],        // de: "classicos" (<1980), "80_90", "2000_2010", "recentes" (>=2011)
  duracao_max:   int|null,     // minutos; null = tanto faz
  idiomas:       [str],        // de: "pt","en","es","outros"; vazio = qualquer
  streamings:    [int],        // ids de provedor TMDB (BR) que a pessoa assina; vazio = qualquer
  nota_min:      float         // 5.0 a 8.0, nota TMDB mínima
}
```

## Rotas
| Método e rota | Auth | Corpo / query | Resposta |
|---|---|---|---|
| `POST /api/couple` | não | `{name}` | `{code, member_id, token}` |
| `POST /api/couple/join` | não | `{code, name}` | `{code, member_id, token}` |
| `GET /api/couple` | sim | — | `{code, me: member_id, members: [Member]}` |
| `GET /api/options` | não | — | `{genres: [{id, name}], providers: [{id, name, logo_url}]}` (gêneros pt-BR e principais streamings BR) |
| `GET /api/quiz` | sim | — | `{quiz: Quiz|null}` (o meu) |
| `PUT /api/quiz` | sim | `Quiz` | `{ok: true}` (marca `quiz_done`) |
| `GET /api/seed` | sim | — | `{movies: [Movie]}` ~20 filmes populares e variados para dar nota no onboarding |
| `GET /api/search?q=` | sim | — | `{movies: [Movie]}` (até 10) |
| `POST /api/rating` | sim | `{tmdb_id, rating}` rating 1-5, ou `0` = "não vi" (remove) | `{ok: true}` |
| `GET /api/recommendations?refresh=0\|1` | sim | — | `{ready: bool, waiting_for: [name], movies: [RecMovie]}` (até 20; `ready=false` enquanto algum membro não fez o quiz) |
| `GET /api/watchlist` | sim | — | `{items: [WatchItem]}` |
| `POST /api/watchlist` | sim | `{tmdb_id, action: "add"\|"remove"\|"watched"}` | `{ok: true}` |
| `POST /api/dismiss` | sim | `{tmdb_id}` | `{ok: true}` (o casal não quer; some das recomendações) |

## Regras do algoritmo (backend)
- Recomendações são do CASAL: mesmo resultado para os dois membros (cachear por casal; recalcular quando quiz/notas/lista mudarem ou `refresh=1`).
- Vetos: união dos `generos_veto` dos dois → filme com qualquer gênero vetado é excluído. Humor "medo" ausente nos dois → excluir Terror.
- Peso de gênero = combinação justa dos dois (ex.: mínimo ou média harmônica) — um gênero que só um ama vale menos que um que os dois amam.
- Streamings: se os dois informaram, priorizar interseção, depois união; vazio = qualquer.
- Duração: menor `duracao_max` não nulo. Nota mínima: maior `nota_min`. Épocas/idiomas: união.
- Filmes avaliados com 4–5 por qualquer um viram sementes (TMDB `/movie/{id}/recommendations`); nota 1–2 de qualquer um penaliza similares.
- Excluir: filmes avaliados por TODOS os membros, já na lista, dispensados. Filme avaliado por só um membro CONTINUA elegível (para verem juntos), vem com `seen_by` preenchido e uma reason tipo "Pessoa A já viu e deu 5★"; nota 1–2 de quem viu reduz o score desse filme.
- `match` 0-100 e 2-3 `reasons` explicando a combinação para o casal.
