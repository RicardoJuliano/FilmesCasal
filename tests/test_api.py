import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))

for _k in ("KV_REST_API_URL", "KV_REST_API_TOKEN", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
    os.environ.pop(_k, None)

from _core import routes, storage  # noqa: E402


class FakeTMDBError(Exception):
    pass


def movie(i):
    return {"tmdb_id": i, "title": f"Filme {i}", "year": 2020, "poster_url": None, "overview": "",
            "genres": ["Comédia"], "runtime": 100, "vote": 7.0, "providers": []}


QUIZ = {"generos_amo": [35], "generos_veto": [27], "humores": ["rir"], "epocas": ["recentes"],
        "duracao_max": 120, "idiomas": ["pt"], "streamings": [], "nota_min": 6.5}


class ApiTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        p = mock.patch.object(storage, "_DB_PATH", Path(self._tmp.name) / "db.json")
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        self.tmdb = SimpleNamespace(
            TMDBError=FakeTMDBError,
            get_options=mock.Mock(return_value={"genres": [{"id": 35, "name": "Comédia"}], "providers": []}),
            seed_movies=mock.Mock(return_value=[movie(1), movie(2)]),
            search=mock.Mock(return_value=[movie(i) for i in range(15)]),
            movie=mock.Mock(side_effect=movie),
        )
        self.rec = SimpleNamespace(recommend=mock.Mock(return_value=[{**movie(9), "match": 90, "reasons": ["x"]}]))
        for name, obj in (("tmdb", self.tmdb), ("recommender", self.rec)):
            p = mock.patch.object(routes, name, obj)
            p.start()
            self.addCleanup(p.stop)

    def call(self, method, path, body=None, auth=None, query=None):
        headers = {}
        if auth:
            headers = {"X-Code": auth["code"], "X-Token": auth["token"]}
        return routes.dispatch(method, path, query or {}, headers, body if body is not None else ({} if method in ("POST", "PUT") else None))

    def couple(self):
        s, a = self.call("POST", "/couple", {"name": "Ana"})
        self.assertEqual(s, 201)
        s, b = self.call("POST", "/couple/join", {"code": a["code"].lower(), "name": "Beto"})
        self.assertEqual(s, 200)
        return a, b

    def test_create_and_join(self):
        a, b = self.couple()
        self.assertEqual(len(a["code"]), 6)
        self.assertFalse(set(a["code"]) & set("01OIL"))
        self.assertEqual(a["code"], b["code"])
        s, info = self.call("GET", "/couple", auth=a)
        self.assertEqual(s, 200)
        self.assertEqual(info["me"], a["member_id"])
        self.assertEqual([m["name"] for m in info["members"]], ["Ana", "Beto"])

    def test_full_couple_409_and_unknown_404(self):
        a, _ = self.couple()
        s, r = self.call("POST", "/couple/join", {"code": a["code"], "name": "Cris"})
        self.assertEqual(s, 409)
        self.assertIn("error", r)
        s, _ = self.call("POST", "/couple/join", {"code": "ZZZZZZ", "name": "Cris"})
        self.assertEqual(s, 404)

    def test_invalid_token_401(self):
        a, _ = self.couple()
        s, r = self.call("GET", "/couple", auth={"code": a["code"], "token": "errado"})
        self.assertEqual(s, 401)
        self.assertIn("error", r)
        s, _ = self.call("GET", "/couple")
        self.assertEqual(s, 401)

    def test_options(self):
        s, r = self.call("GET", "/options")
        self.assertEqual(s, 200)
        self.assertEqual(r["genres"][0]["id"], 35)
        self.tmdb.get_options.side_effect = FakeTMDBError("sem chave")
        s, r = self.call("GET", "/options")
        self.assertEqual(s, 502)

    def test_quiz(self):
        a, _ = self.couple()
        self.assertEqual(self.call("GET", "/quiz", auth=a)[1], {"quiz": None})
        self.assertEqual(self.call("PUT", "/quiz", QUIZ, auth=a), (200, {"ok": True}))
        self.assertEqual(self.call("GET", "/quiz", auth=a)[1]["quiz"]["nota_min"], 6.5)
        s, info = self.call("GET", "/couple", auth=a)
        self.assertTrue(info["members"][0]["quiz_done"])
        self.assertFalse(info["members"][1]["quiz_done"])
        s, _ = self.call("PUT", "/quiz", {**QUIZ, "nota_min": 9}, auth=a)
        self.assertEqual(s, 400)
        s, _ = self.call("PUT", "/quiz", {**QUIZ, "humores": ["xyz"]}, auth=a)
        self.assertEqual(s, 400)

    def test_seed_and_search(self):
        a, _ = self.couple()
        self.assertEqual(len(self.call("GET", "/seed", auth=a)[1]["movies"]), 2)
        s, r = self.call("GET", "/search", auth=a, query={"q": "matrix"})
        self.assertEqual((s, len(r["movies"])), (200, 10))
        self.assertEqual(self.call("GET", "/search", auth=a)[0], 400)

    def test_rating(self):
        a, _ = self.couple()
        self.assertEqual(self.call("POST", "/rating", {"tmdb_id": 5, "rating": 4}, auth=a)[0], 200)
        _, info = self.call("GET", "/couple", auth=a)
        self.assertEqual(info["members"][0]["ratings_count"], 1)
        self.call("POST", "/rating", {"tmdb_id": 5, "rating": 0}, auth=a)
        _, info = self.call("GET", "/couple", auth=a)
        self.assertEqual(info["members"][0]["ratings_count"], 0)
        self.assertEqual(self.call("POST", "/rating", {"tmdb_id": 5, "rating": 7}, auth=a)[0], 400)

    def test_watchlist(self):
        a, b = self.couple()
        self.call("POST", "/rating", {"tmdb_id": 3, "rating": 5}, auth=b)
        self.assertEqual(self.call("POST", "/watchlist", {"tmdb_id": 3, "action": "add"}, auth=a)[0], 200)
        _, r = self.call("GET", "/watchlist", auth=b)
        self.assertEqual(r["items"][0]["status"], "quero_ver")
        self.assertEqual(r["items"][0]["added_by"], a["member_id"])
        self.assertEqual(r["items"][0]["ratings"], {b["member_id"]: 5})
        self.call("POST", "/watchlist", {"tmdb_id": 3, "action": "watched"}, auth=a)
        self.assertEqual(self.call("GET", "/watchlist", auth=a)[1]["items"][0]["status"], "assistido")
        self.call("POST", "/watchlist", {"tmdb_id": 3, "action": "remove"}, auth=a)
        self.assertEqual(self.call("GET", "/watchlist", auth=a)[1]["items"], [])
        self.assertEqual(self.call("POST", "/watchlist", {"tmdb_id": 3, "action": "x"}, auth=a)[0], 400)

    def test_dismiss(self):
        a, _ = self.couple()
        self.call("POST", "/dismiss", {"tmdb_id": 8}, auth=a)
        self.call("POST", "/dismiss", {"tmdb_id": 8}, auth=a)
        self.assertEqual(storage.get_couple(a["code"])["dismissed"], [8])

    def test_recommendations_ready_and_cache(self):
        a, b = self.couple()
        s, r = self.call("GET", "/recommendations", auth=a)
        self.assertEqual((s, r["ready"]), (200, False))
        self.assertEqual(r["waiting_for"], ["Ana", "Beto"])
        self.call("PUT", "/quiz", QUIZ, auth=a)
        _, r = self.call("GET", "/recommendations", auth=a)
        self.assertEqual(r["waiting_for"], ["Beto"])
        self.call("PUT", "/quiz", QUIZ, auth=b)
        _, r = self.call("GET", "/recommendations", auth=a)
        self.assertTrue(r["ready"])
        self.assertEqual(r["movies"][0]["match"], 90)
        # mesmo resultado para o outro membro, vindo do cache
        _, r2 = self.call("GET", "/recommendations", auth=b)
        self.assertEqual(r2, r)
        self.assertEqual(self.rec.recommend.call_count, 1)
        # refresh=1 recalcula
        self.call("GET", "/recommendations", auth=a, query={"refresh": "1"})
        self.assertEqual(self.rec.recommend.call_count, 2)
        # mudança invalida o cache
        self.call("POST", "/rating", {"tmdb_id": 1, "rating": 5}, auth=a)
        self.call("GET", "/recommendations", auth=a)
        self.assertEqual(self.rec.recommend.call_count, 3)
        self.call("POST", "/dismiss", {"tmdb_id": 9}, auth=a)
        self.call("GET", "/recommendations", auth=a)
        self.assertEqual(self.rec.recommend.call_count, 4)

    def test_unknown_route_and_bad_body(self):
        self.assertEqual(self.call("GET", "/nada")[0], 404)
        self.assertEqual(self.call("DELETE", "/couple")[0], 405)
        self.assertEqual(self.call("POST", "/couple", {"name": ""})[0], 400)


if __name__ == "__main__":
    unittest.main()
