# Filmes a Dois

App para casais: cada pessoa responde um questionário rápido e dá nota a alguns filmes, e os dois recebem as **mesmas recomendações**, calculadas a partir dos gostos de ambos. Também tem lista "Quero ver" / "Assistidos" com a nota de cada um.

Frontend em HTML/CSS/JS puro (sem build) na pasta `public/`. Backend em Python (só biblioteca padrão) na pasta `api/`. Dados de filmes vêm do TMDB.

## Rodar localmente

Requisitos: Python 3.12+ e uma chave do [TMDB](https://www.themoviedb.org/settings/api).

1. Copie `.env.example` para `.env` e preencha `TMDB_API_KEY` (v3) ou `TMDB_READ_TOKEN` (v4).
2. Rode:

   ```
   python dev.py
   ```

3. Abra http://localhost:8000.

Sem as variáveis do Redis, os dados ficam no arquivo local `data/dev-db.json`.

Para testar como casal na mesma máquina, use uma janela anônima para o segundo membro e abra o link de convite (`/?convite=CODIGO`).

## Publicar na Vercel

1. Suba o projeto para um repositório Git e importe-o na Vercel (sem framework e sem build; o `vercel.json` já direciona `/api/*` para a função Python).
2. Em **Settings → Environment Variables**, defina `TMDB_API_KEY` (ou `TMDB_READ_TOKEN`).
3. Crie um banco **Upstash Redis** em **Storage / Marketplace** e conecte-o ao projeto. A Vercel injeta `KV_REST_API_URL` e `KV_REST_API_TOKEN` (também são aceitas `UPSTASH_REDIS_REST_URL` e `UPSTASH_REDIS_REST_TOKEN`).
4. Faça o deploy. Depois, crie o casal e mande o link de convite ao seu par.

## Como funciona

- Sem login: ao criar ou entrar num casal, o navegador guarda `code`, `member_id` e `token` no `localStorage` e os envia nos headers `X-Code` e `X-Token`.
- Fluxo: boas-vindas → questionário → notas (mínimo de 5) → recomendações. Se o par ainda não respondeu, o app mostra "Esperando…" e confere a cada 10 segundos.
- Nas recomendações, cada filme tem **Quero ver**, **Já vi** (escolha rápida de 1 a 5 estrelas; a nota tira o filme das sugestões e ajusta as próximas) e **Não curti**.
- Filme visto por só um dos dois continua nas recomendações com o selo "<nome> já viu ★N" (quem já viu pode usar **Mudar nota**); ele só some quando os dois já viram.
- Cada casal tem no máximo 2 membros.
