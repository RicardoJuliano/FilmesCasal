import unittest
from unittest import mock

from api._core import recommender as rec
from api._core import tmdb

COM, DRA, ACT, HOR, ROM = 35, 18, 28, 27, 10749
NAMES = {12: "Aventura", 878: "Ficção científica", 9648: "Mistério", COM: "Comédia", DRA: "Drama", ACT: "Ação", HOR: "Terror", ROM: "Romance"}


def mv(i, gids, year=2015, vote=7.5, lang="en", runtime=100, providers=()):
    return {"tmdb_id": i, "title": f"F{i}", "year": year, "poster_url": "http://p/x.jpg",
            "overview": "o", "genres": [NAMES[g] for g in gids], "runtime": runtime, "vote": vote,
            "providers": [{"id": p, "name": f"P{p}", "logo_url": None} for p in providers],
            "genre_ids": list(gids), "language": lang, "vote_count": 1000}


def quiz(**kw):
    q = {"generos_amo": [], "generos_veto": [], "humores": [], "epocas": [], "duracao_max": None,
         "idiomas": [], "streamings": [], "nota_min": 6.0}
    q.update(kw)
    return q


def couple(qa, qb, ratings_a=None, ratings_b=None, **extra):
    return {"code": "ABC123", "created_at": "x", "watchlist": extra.get("watchlist", {}),
            "dismissed": extra.get("dismissed", []),
            "members": {"a": {"name": "Pessoa B", "token": "t", "quiz": qa, "ratings": ratings_a or {}},
                        "b": {"name": "Pessoa C", "token": "t", "quiz": qb, "ratings": ratings_b or {}}}}


class Base(unittest.TestCase):
    catalog = []
    recs = {}

    def run_rec(self, c, limit=20):
        cat = {m["tmdb_id"]: m for m in self.catalog}
        with mock.patch.object(tmdb, "discover", lambda params=None, page=1: list(self.catalog)), \
                mock.patch.object(tmdb, "recommendations", lambda i: list(self.recs.get(i, []))), \
                mock.patch.object(tmdb, "movie", lambda i: dict(cat[i])):
            return rec.recommend(c, limit)


class RecommenderTest(Base):
    def setUp(self):
        self.catalog = [mv(1, [COM]), mv(2, [HOR]), mv(3, [DRA]), mv(4, [ACT]),
                        mv(5, [COM, DRA]), mv(6, [ACT, HOR])]
        self.recs = {}

    def ids(self, out):
        return [m["tmdb_id"] for m in out]

    def test_vetos_union(self):
        c = couple(quiz(generos_amo=[COM], generos_veto=[DRA]), quiz(generos_amo=[COM], generos_veto=[ACT]))
        ids = self.ids(self.run_rec(c))
        self.assertNotIn(3, ids)
        self.assertNotIn(5, ids)
        self.assertNotIn(4, ids)
        self.assertNotIn(6, ids)
        self.assertIn(1, ids)

    def test_horror_excluded_without_medo(self):
        c = couple(quiz(generos_amo=[COM]), quiz(generos_amo=[DRA]))
        self.assertNotIn(2, self.ids(self.run_rec(c)))
        c = couple(quiz(generos_amo=[COM], humores=["medo"]), quiz(generos_amo=[DRA]))
        self.assertIn(2, self.ids(self.run_rec(c)))

    def test_shared_genre_beats_single_lover(self):
        c = couple(quiz(generos_amo=[COM, ACT]), quiz(generos_amo=[COM]))
        out = self.run_rec(c)
        pos = {m["tmdb_id"]: i for i, m in enumerate(out)}
        self.assertLess(pos[1], pos[4])  # comédia (os dois) antes de ação (só Pessoa B)
        self.assertTrue(any("Os dois amam comédia" in r for r in out[0]["reasons"]))

    def test_filters(self):
        # duração é rígida; nota_min, época e idioma só ordenam/pontuam
        self.catalog = [mv(1, [COM], year=1970), mv(2, [COM], year=2015), mv(3, [COM], runtime=200),
                        mv(4, [COM], vote=6.2), mv(5, [COM], lang="pt")]
        c = couple(quiz(generos_amo=[COM], epocas=["recentes"], duracao_max=120, nota_min=7.0,
                        idiomas=["en"]), quiz(generos_amo=[COM], duracao_max=150, nota_min=6.0))
        ids = self.ids(self.run_rec(c))
        self.assertNotIn(3, ids)  # 200 min > 120
        self.assertEqual(ids[0], 2)  # recente + inglês, bate tudo
        self.assertEqual(ids[-1], 4)  # abaixo da nota mínima fica por último

    def test_empty_means_any(self):
        # só a Pessoa B pediu português; Pessoa A deixou vazio → ninguém é filtrado, pt só ganha bônus
        self.catalog = [mv(1, [COM], lang="en"), mv(2, [COM], lang="pt"), mv(3, [COM], lang="en", year=1960)]
        c = couple(quiz(generos_amo=[COM], epocas=["recentes"]),
                   quiz(generos_amo=[COM], idiomas=["pt"]))
        out = self.run_rec(c)
        self.assertEqual(sorted(m["tmdb_id"] for m in out), [1, 2, 3])
        self.assertEqual(out[0]["tmdb_id"], 2)  # pt e recente
        self.assertTrue(any("Em português, como Pessoa C gosta" in r for r in out[0]["reasons"]))
        self.assertTrue(any("como Pessoa B gosta" in r for r in out[0]["reasons"]))
        self.assertEqual(out[-1]["tmdb_id"], 3)

    def test_real_couple_never_empty(self):
        # reproduz um perfil divergente que antes voltava vazio
        pessoa_a = quiz(generos_amo=[28, 878, 35, 9648, 27], humores=["rir", "pensar", "aventura"],
                       epocas=["recentes", "2000_2010"], nota_min=7.0)
        pessoa_b = quiz(generos_amo=[12, 35, 18, 10749, 14], humores=["romance", "rir", "pensar"],
                   idiomas=["pt"], nota_min=7.0)
        r_pessoa_a = {str(i): n for i, n in {496243: 4, 1368337: 5, 969681: 5, 597: 4, 1726: 5, 1423191: 2,
                     1339713: 4, 14836: 5, 70160: 4, 27205: 5, 155: 5, 1220564: 3, 533535: 5}.items()}
        r_pessoa_b = {str(i): n for i, n in {496243: 4, 453: 4, 1368337: 5, 969681: 4, 597: 3, 13: 4, 1726: 5,
                 1423191: 1, 14836: 5, 1339713: 3, 70160: 3, 862: 5, 27205: 4}.items()}
        c = {"code": "DIV001", "created_at": "x", "watchlist": {}, "dismissed": [],
             "members": {"r": {"name": "Pessoa A", "token": "t", "quiz": pessoa_a, "ratings": r_pessoa_a},
                         "a": {"name": "Pessoa B", "token": "t", "quiz": pessoa_b, "ratings": r_pessoa_b}}}
        gl = [COM, DRA, ACT, 12, 878, 9648, ROM]
        # 30 filmes em inglês, anos variados, só 8 com nota >= 7
        cat = [mv(1000 + i, [gl[i % len(gl)]], year=1990 + i, vote=8.0 if i < 8 else 6.0 + (i % 10) / 10)
               for i in range(30)]
        cat.append(mv(496243, [COM], vote=8.5))  # já avaliado: nunca volta
        by_id = {m["tmdb_id"]: m for m in cat}

        def fake_discover(params=None, page=1):
            floor = float((params or {}).get("vote_average.gte", 0))
            return [m for m in cat if m["vote"] >= floor]

        with mock.patch.object(tmdb, "discover", fake_discover), \
                mock.patch.object(tmdb, "recommendations", lambda i: []), \
                mock.patch.object(tmdb, "movie", lambda i: dict(by_id.get(i) or mv(i, [COM]))):
            out = rec.recommend(c, 20)
        self.assertGreaterEqual(len(out), 10)
        ids = [m["tmdb_id"] for m in out]
        self.assertNotIn(496243, ids)
        self.assertTrue(all(m["vote"] >= 6.0 for m in out))
        self.assertTrue(all(2 <= len(m["reasons"]) <= 3 for m in out))
        self.assertTrue({1000 + i for i in range(8)} <= set(ids))  # os que atendem a nota entram todos

    def test_excludes_rated_watchlist_dismissed(self):
        c = couple(quiz(generos_amo=[COM]), quiz(generos_amo=[COM]), {"1": 3}, {"1": 4},
                   watchlist={"5": {}}, dismissed=[3])
        ids = self.ids(self.run_rec(c))
        for x in (1, 5, 3):
            self.assertNotIn(x, ids)

    def test_same_result_any_member_and_deterministic(self):
        qa, qb = quiz(generos_amo=[COM]), quiz(generos_amo=[DRA])
        c1 = couple(qa, qb)
        c2 = {**c1, "members": {"x": c1["members"]["b"], "y": c1["members"]["a"]}}
        self.assertEqual(self.run_rec(c1), self.run_rec(c2))
        self.assertEqual(self.run_rec(c1), self.run_rec(c1))

    def test_missing_quiz(self):
        out = self.run_rec(couple(None, None))
        self.assertTrue(out)
        out = self.run_rec(couple(quiz(generos_amo=[COM]), None))
        self.assertEqual(out[0]["tmdb_id"], 1)
        for m in out:
            self.assertTrue(0 <= m["match"] <= 100)
            self.assertGreaterEqual(len(m["reasons"]), 2)

    def test_seeds_and_dislikes(self):
        self.catalog.append(mv(9, [ACT], vote=7.0))
        self.recs = {3: [self.catalog[-1]]}
        c = couple(quiz(generos_amo=[COM]), quiz(generos_amo=[COM]), {"3": 5})
        out = self.run_rec(c)
        m9 = next(m for m in out if m["tmdb_id"] == 9)
        self.assertTrue(any("Parecido com F3" in r for r in m9["reasons"]))
        c = couple(quiz(generos_amo=[COM]), quiz(generos_amo=[COM]), {"4": 1})
        base = couple(quiz(generos_amo=[COM]), quiz(generos_amo=[COM]))
        pen = {m["tmdb_id"]: m["match"] for m in self.run_rec(c)}
        nor = {m["tmdb_id"]: m["match"] for m in self.run_rec(base)}
        self.assertLess(pen[9], nor[9])  # ação penalizada por nota 1

    def test_streaming_intersection_first(self):
        self.catalog = [mv(1, [COM], providers=[8]), mv(2, [COM], providers=[8, 9]),
                        mv(3, [COM], providers=[9]), mv(4, [COM], providers=[])]
        c = couple(quiz(generos_amo=[COM], streamings=[8, 9]), quiz(generos_amo=[COM], streamings=[9]))
        ids = self.ids(self.run_rec(c, limit=3))
        self.assertEqual(ids, [2, 3, 1])  # interseção (9) antes da união (8)
        self.assertEqual(self.ids(self.run_rec(c)), [2, 3, 1, 4])  # sem streaming só se faltar filme

    def test_seen_by_one_stays_with_seen_by(self):
        qa, qb = quiz(generos_amo=[COM]), quiz(generos_amo=[COM])
        c = couple(qa, qb, {"1": 5})  # só Pessoa B viu o 1
        out = self.run_rec(c)
        m1 = next(m for m in out if m["tmdb_id"] == 1)
        self.assertEqual(m1["seen_by"], [{"member_id": "a", "name": "Pessoa B", "rating": 5}])
        self.assertIn("Pessoa B já viu e deu 5★", m1["reasons"])
        for m in out:
            if m["tmdb_id"] != 1:
                self.assertEqual(m["seen_by"], [])

    def test_seen_by_both_excluded(self):
        qa, qb = quiz(generos_amo=[COM]), quiz(generos_amo=[COM])
        out = self.run_rec(couple(qa, qb, {"1": 5}, {"1": 3}))
        self.assertNotIn(1, self.ids(out))

    def test_single_member_couple_excludes_rated(self):
        c = couple(quiz(generos_amo=[COM]), None, {"1": 5})
        del c["members"]["b"]
        self.assertNotIn(1, self.ids(self.run_rec(c)))

    def test_low_rating_by_one_lowers_score(self):
        qa, qb = quiz(generos_amo=[COM]), quiz(generos_amo=[COM])
        score = lambda c: next(m for m in self.run_rec(c) if m["tmdb_id"] == 1)["match"]
        neutral = score(couple(qa, qb))
        liked = score(couple(qa, qb, {"1": 5}))
        hated = score(couple(qa, qb, {"1": 1}))
        self.assertEqual(neutral, liked)
        self.assertLess(hated, neutral - 20)

    def test_seen_by_same_list_for_both_members(self):
        qa, qb = quiz(generos_amo=[COM]), quiz(generos_amo=[DRA])
        c1 = couple(qa, qb, {"1": 5, "3": 2}, {"5": 4})
        c2 = {**c1, "members": {"b": c1["members"]["b"], "a": c1["members"]["a"]}}
        r1 = self.run_rec(c1)
        self.assertEqual(r1, self.run_rec(c2))
        self.assertTrue(all("seen_by" in m for m in r1))


if __name__ == "__main__":
    unittest.main()
