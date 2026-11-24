"""Recomendações do casal (determinísticas para o mesmo estado)."""
import math
import time
from concurrent.futures import ThreadPoolExecutor, wait

try:
    from . import tmdb
except ImportError:  # execução fora do pacote
    import tmdb

HORROR = 27
HUMOR_GENRES = {
    "rir": [35], "chorar": [18, 10749], "tensao": [53, 80, 9648],
    "pensar": [9648, 878, 99, 36], "aventura": [12, 28, 14],
    "romance": [10749], "medo": [HORROR],
}
EPOCHS = {"classicos": (0, 1979), "80_90": (1980, 1999),
          "2000_2010": (2000, 2010), "recentes": (2011, 9999)}
BUDGET = 7.0          # segundos no total
ENRICH = 45           # detalhes consultados (runtime + streamings)
MAX_SEEDS = 5
MAX_DISLIKED = 4
MAX_PARTIAL = 12


def _run_all(jobs, deadline, workers=10):
    """Roda (fn, args) em paralelo; falhas/timeouts viram None. Levanta se tudo falhar."""
    if not jobs:
        return []
    ex = ThreadPoolExecutor(max_workers=workers)
    futs = [ex.submit(fn, *args) for fn, args in jobs]
    wait(futs, timeout=max(0.1, deadline - time.monotonic()))
    ex.shutdown(wait=False, cancel_futures=True)
    out, first_err = [], None
    for f in futs:
        if f.done() and not f.cancelled() and f.exception() is None:
            out.append(f.result())
        else:
            if f.done() and not f.cancelled() and first_err is None:
                first_err = f.exception()
            out.append(None)
    if all(r is None for r in out):
        if isinstance(first_err, tmdb.TMDBError):
            raise first_err
        raise tmdb.TMDBError("O TMDB demorou demais para responder.")
    return out


def _quiz(q):
    if not isinstance(q, dict):
        return None
    return {
        "amo": [int(x) for x in q.get("generos_amo") or []],
        "veto": [int(x) for x in q.get("generos_veto") or []],
        "humores": list(q.get("humores") or []),
        "epocas": [e for e in q.get("epocas") or [] if e in EPOCHS],
        "duracao": q.get("duracao_max") or None,
        "idiomas": list(q.get("idiomas") or []),
        "streamings": {int(x) for x in q.get("streamings") or []},
        "nota_min": float(q.get("nota_min") or 6.0),
    }


def _affinity(qz):
    aff = {}
    for h in qz["humores"]:
        for g in HUMOR_GENRES.get(h, []):
            aff[g] = 0.5
    for g in qz["amo"]:
        aff[g] = 1.0
    return aff


def _couple_weights(affs):
    if not affs:
        return {}
    gids = sorted(set().union(*affs))
    out = {}
    for g in gids:
        vals = [a.get(g, 0.0) for a in affs]
        if len(vals) == 1:
            out[g] = vals[0]
        else:
            out[g] = 0.7 * min(vals) + 0.3 * (sum(vals) / len(vals))  # um só ama vale bem menos
    return out


def _lang_ok(lang, idiomas):
    if not idiomas:
        return True
    lang = lang or ""
    return lang in idiomas or ("outros" in idiomas and lang not in ("pt", "en", "es"))


def _epoch_ok(year, epocas):
    if not epocas:
        return True
    if year is None:
        return False
    return any(EPOCHS[e][0] <= year <= EPOCHS[e][1] for e in epocas)


def _clamp(x):
    return max(0.0, min(1.0, x))


def recommend(couple, limit=20):
    deadline = time.monotonic() + BUDGET
    members = sorted((couple.get("members") or {}).items())
    ratings = {}  # tmdb_id -> [(member_id, nome, nota)]
    for mid_, m in members:
        for k, v in (m.get("ratings") or {}).items():
            ratings.setdefault(int(k), []).append((mid_, m.get("name") or "Alguém", int(v)))
    qms = [(m.get("name") or "Alguém", _quiz(m.get("quiz"))) for _, m in members]
    qms = [(n, q) for n, q in qms if q]

    # só sai quem todos já avaliaram; visto por um só continua (para verem juntos)
    seen_all = {i for i, rs in ratings.items() if len(rs) >= len(members)}
    partial = sorted(i for i in ratings if i not in seen_all)
    excluded = seen_all | {int(k) for k in (couple.get("watchlist") or {})} \
        | {int(x) for x in couple.get("dismissed") or []}
    partial = [i for i in partial if i not in excluded]

    def seen_by(i):
        return [{"member_id": a, "name": n, "rating": r} for a, n, r in sorted(ratings.get(i, ()))] \
            if i in partial_set else []

    partial_set = set(partial)

    def seen_pen(i):  # quem viu e não gostou (1-2) derruba bastante
        return 0.35 if any(r["rating"] <= 2 for r in seen_by(i)) else 0.0

    # ---- regras combinadas do casal
    vetos = set().union(*[set(q["veto"]) for _, q in qms]) if qms else set()
    if qms and not any(HORROR in q["amo"] or "medo" in q["humores"] for _, q in qms):
        vetos.add(HORROR)
    weights = _couple_weights([_affinity(q) for _, q in qms])
    nota_min = max([q["nota_min"] for _, q in qms], default=6.0)
    durs = [q["duracao"] for _, q in qms if q["duracao"]]
    duracao = min(durs) if durs else None
    # época/idioma são só preferências (bônus); lista vazia = "qualquer", nunca filtra
    epocas = sorted(set().union(*[set(q["epocas"]) for _, q in qms])) if qms else []
    pref_epoca = [(n, q["epocas"]) for n, q in qms if q["epocas"]]
    pref_lang = [(n, q["idiomas"]) for n, q in qms if q["idiomas"]]
    floor = min(nota_min, 6.0)
    stream_sets = [q["streamings"] for _, q in qms if q["streamings"]]
    union_s = set().union(*stream_sets) if stream_sets else set()
    inter_s = set.intersection(*stream_sets) if stream_sets else set()

    liked = {}  # id -> melhor nota 4-5
    disliked = []
    for mid in sorted(ratings):
        best = max(r for _, _, r in ratings[mid])
        worst = min(r for _, _, r in ratings[mid])
        if best >= 4:
            liked[mid] = best
        if worst <= 2:
            disliked.append(mid)
    seeds = sorted(liked, key=lambda i: (-liked[i], i))[:MAX_SEEDS]
    disliked = disliked[:MAX_DISLIKED]

    # ---- coleta de candidatos (1ª leva paralela)
    base = {"vote_average.gte": nota_min, "vote_count.gte": 300}
    if vetos:
        base["without_genres"] = "|".join(str(g) for g in sorted(vetos))
    if duracao:
        base["with_runtime.lte"] = duracao
    if union_s:
        base.update({"with_watch_providers": "|".join(str(p) for p in sorted(union_s)),
                     "watch_region": tmdb.REGION, "with_watch_monetization_types": "flatrate"})
    top = [g for g, w in sorted(weights.items(), key=lambda kv: (-kv[1], kv[0])) if w > 0][:4]
    dj = [({**base, "with_genres": str(g)}, 1) for g in top]
    if len(top) >= 2:
        dj.append(({**base, "with_genres": f"{top[0]},{top[1]}"}, 1))
    dj += [(dict(base), 1), (dict(base), 2)]
    for e in epocas:
        lo, hi = EPOCHS[e]
        p = {**base, "primary_release_date.gte": f"{max(lo, 1900)}-01-01",
             "primary_release_date.lte": f"{min(hi, 2100)}-12-31"}
        if top:
            p["with_genres"] = str(top[0])
        dj.append((p, 1))
    for lg in sorted({x for _, ls in pref_lang for x in ls if x in ("pt", "en", "es")}):
        dj.append(({**base, "with_original_language": lg}, 1))

    jobs = [(tmdb.discover, d) for d in dj]
    jobs += [(tmdb.recommendations, (s,)) for s in seeds]
    jobs += [(tmdb.movie, (i,)) for i in seeds + disliked]
    part_ids = partial[:MAX_PARTIAL]
    jobs += [(tmdb.movie, (i,)) for i in part_ids]
    res = _run_all(jobs, deadline)
    nd, ns = len(dj), len(seeds)

    cands, seed_hits = {}, {}
    for r in res[:nd]:
        for m in r or []:
            cands.setdefault(m["tmdb_id"], m)
    for s, r in zip(seeds, res[nd:nd + ns]):
        for m in r or []:
            cands.setdefault(m["tmdb_id"], m)
            seed_hits.setdefault(m["tmdb_id"], set()).add(s)
    nin = len(seeds) + len(disliked)
    info = {i: r for i, r in zip(seeds + disliked, res[nd + ns:nd + ns + nin]) if r}
    for i, r in zip(part_ids, res[nd + ns + nin:]):
        if r:  # detalhe completo do filme visto por um só entra no pool
            cands[i] = r
    dis_genres = [(i, set(info[i]["genre_ids"])) for i in disliked if i in info]

    def passes(m):  # só o que é rígido: excluídos, vetos, duração
        gids = set(m.get("genre_ids") or [])
        if m["tmdb_id"] in excluded or gids & vetos or not m.get("poster_url"):
            return False
        if m["vote"] < floor:
            return False
        return not (duracao and m.get("runtime") and m["runtime"] > duracao)

    def level(m):  # 0 = atende nota_min; cada 0.5 abaixo = 1 etapa de relaxamento
        return 0 if m["vote"] >= nota_min else math.ceil((nota_min - m["vote"]) / 0.5)

    def bonus(m):
        lang = ep = 0.0
        if pref_lang:
            lang = sum(_lang_ok(m.get("language"), ls) for _, ls in pref_lang) / len(pref_lang)
        if pref_epoca:
            ep = sum(_epoch_ok(m["year"], es) for _, es in pref_epoca) / len(pref_epoca)
        return 0.08 * lang + 0.08 * ep

    def gscore(m):
        ws = sorted((weights.get(g, 0.0) for g in m.get("genre_ids") or []), reverse=True)
        ws += [0.0, 0.0]
        return _clamp((ws[0] + 0.5 * ws[1]) / 1.5)

    def pre(m):
        s = 0.6 * gscore(m) + 0.25 * _clamp((m["vote"] - 5) / 3) \
            + 0.15 * _clamp(0.6 * len(seed_hits.get(m["tmdb_id"], ()))) - seen_pen(m["tmdb_id"])
        return s

    # relaxamento: poucos candidatos → amplia (nota até 6.0, depois gêneros populares sem filtro de gosto)
    if sum(1 for m in cands.values() if passes(m) and level(m) == 0) < 2 * limit:
        rb = {"vote_average.gte": floor, "vote_count.gte": 200}
        if vetos:
            rb["without_genres"] = base.get("without_genres")
        if duracao:
            rb["with_runtime.lte"] = duracao
        rj = [({**rb, "with_genres": str(g)}, p) for g in top for p in (1, 2)]
        rj += [(dict(rb), p) for p in (1, 2, 3)]
        try:
            for r in _run_all([(tmdb.discover, d) for d in rj], deadline + 1.0):
                for m in r or []:
                    cands.setdefault(m["tmdb_id"], m)
        except tmdb.TMDBError:
            pass

    pool = sorted((m for m in cands.values() if passes(m)),
                  key=lambda m: (level(m), -pre(m) - bonus(m), m["tmdb_id"]))
    pool = pool[:ENRICH]

    # ---- enriquece com runtime e streamings (2ª leva)
    try:
        det = _run_all([(tmdb.movie, (m["tmdb_id"],)) for m in pool], deadline + 1.0)
    except tmdb.TMDBError:
        det = [None] * len(pool)
    final = []
    for m, d in zip(pool, det):
        if d:
            m = {**m, "runtime": d["runtime"], "providers": d["providers"],
                 "genres": d["genres"] or m["genres"], "genre_ids": d["genre_ids"] or m["genre_ids"],
                 "overview": d["overview"] or m["overview"]}
        if passes(m):
            final.append(m)

    def tier(m):
        if not stream_sets:
            return None
        pids = {p["id"] for p in m["providers"] if "id" in p}
        if pids & inter_s:
            return 2
        return 1 if pids & union_s else 0

    scored = []
    for m in final:
        t = tier(m)
        gids = set(m["genre_ids"])
        pen = max((len(gids & d) / len(gids | d) for i, d in dis_genres
                   if i != m["tmdb_id"] and gids | d), default=0.0)
        hits = len(seed_hits.get(m["tmdb_id"], ()))
        if t is None:
            sc = 0.6 * gscore(m) + 0.25 * _clamp((m["vote"] - 5) / 3) + 0.15 * _clamp(0.6 * hits)
        else:
            sc = 0.5 * gscore(m) + 0.2 * _clamp((m["vote"] - 5) / 3) + 0.15 * _clamp(0.6 * hits) \
                + 0.15 * (1.0 if t == 2 else 0.5 if t == 1 else 0.0)
        sc = _clamp(sc + bonus(m) - 0.3 * pen - seen_pen(m["tmdb_id"]) - 0.04 * level(m))
        scored.append((sc, t, m))
    scored.sort(key=lambda x: (level(x[2]), -x[0], x[2]["tmdb_id"]))
    if stream_sets:  # sem streaming do casal só entra se faltar filme
        good = [x for x in scored if x[1]]
        scored = good + [x for x in scored if not x[1]][:max(0, limit - len(good))]
    scored = scored[:limit]
    scored.sort(key=lambda x: (-x[0], x[2]["tmdb_id"]))  # exibe por match; etapas já definiram quem entra
    prefs = (pref_lang, pref_epoca)

    names_of = lambda pred: [n for n, q in qms if pred(q)]
    out = []
    for sc, t, m in scored:
        out.append({**{k: m[k] for k in ("tmdb_id", "title", "year", "poster_url", "overview",
                                          "genres", "runtime", "vote", "providers")},
                    "match": int(round(sc * 100)), "seen_by": seen_by(m["tmdb_id"]),
                    "reasons": _reasons(m, t, weights, qms, names_of, seed_hits, info, ratings,
                                        duracao, union_s, inter_s, prefs, seen_by(m["tmdb_id"]))})
    return out


LANG_LABEL = {"pt": "Em português", "en": "Em inglês", "es": "Em espanhol"}
EPOCH_LABEL = {"classicos": "Um clássico", "80_90": "Dos anos 80/90",
               "2000_2010": "Dos anos 2000", "recentes": "Lançamento recente"}


def _reasons(m, t, weights, qms, names_of, seed_hits, info, ratings, duracao, union_s, inter_s, prefs, seen_list):
    rs = []
    pref_lang, pref_epoca = prefs
    for sb in seen_list:
        rs.append(f"{sb['name']} já viu e deu {sb['rating']}★")
    gname = dict(zip(m["genre_ids"], m["genres"]))
    for g in sorted(m["genre_ids"], key=lambda g: (-weights.get(g, 0), g)):
        if weights.get(g, 0) <= 0:
            continue
        amo = names_of(lambda q: g in q["amo"])
        nome = gname.get(g, "").lower()
        if len(qms) >= 2 and len(amo) == len(qms):
            rs.append(f"Os dois amam {nome}")
        elif amo:
            rs.append(f"{amo[0]} ama {nome}")
        else:
            rs.append(f"Combina com o clima que vocês querem ({nome})")
        break
    for s in sorted(seed_hits.get(m["tmdb_id"], ())):
        if s in info:
            quem = [n for _, n, r in ratings[s] if r >= 4]
            rs.append(f"Parecido com {info[s]['title']}, que {quem[0]} curtiu")
            break
    for n, ls in pref_lang:
        if _lang_ok(m.get("language"), ls):
            rs.append(f"{LANG_LABEL.get(m.get('language'), 'No idioma original')}, como {n} gosta")
            break
    for n, es in pref_epoca:
        hit = next((e for e in es if _epoch_ok(m["year"], [e])), None)
        if hit:
            rs.append(f"{EPOCH_LABEL[hit]}, como {n} gosta")
            break
    if t and m["providers"]:
        prov = next((p["name"] for p in m["providers"] if p.get("id") in (inter_s if t == 2 else union_s)),
                    m["providers"][0]["name"])
        if t == 2:
            rs.append(f"Está no {prov}, que os dois assinam")
        else:
            rs.append(f"Está no {prov}, que vocês têm em casa")
    if duracao and m.get("runtime"):
        rs.append(f"Cabe na noite de vocês ({m['runtime']} min)")
    rs.append(f"Bem avaliado: nota {m['vote']:.1f} no TMDB")
    rs.append("Uma boa escolha para assistirem juntos")
    return rs[:3]
