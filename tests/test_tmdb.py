import os
import unittest
from unittest import mock

from api._core import tmdb

GENRES = {"genres": [{"id": 35, "name": "Comédia"}, {"id": 18, "name": "Drama"}]}
RAW = {"id": 1, "title": "Filme", "release_date": "2015-05-01", "poster_path": "/p.jpg",
       "overview": "x", "genre_ids": [35, 18], "vote_average": 7.84, "original_language": "en"}


def fake_fetch(url, headers):
    fake_fetch.calls.append((url, headers))
    if "/genre/movie/list" in url:
        return GENRES
    if "/search/movie" in url:
        return {"results": [dict(RAW, id=i) for i in range(15)]}
    if "/movie/1?" in url:
        return {**RAW, "genres": GENRES["genres"], "runtime": 101,
                "watch/providers": {"results": {"BR": {"flatrate": [
                    {"provider_id": 8, "provider_name": "Netflix", "logo_path": "/n.png",
                     "display_priority": 1}]}}}}
    if "/watch/providers/movie" in url:
        return {"results": [{"provider_id": 8, "provider_name": "Netflix", "logo_path": "/n.png",
                             "display_priorities": {"BR": 1}}]}
    raise AssertionError(url)


class TmdbTest(unittest.TestCase):
    def setUp(self):
        tmdb._cache.clear()
        fake_fetch.calls = []
        p = mock.patch.dict(os.environ, {"TMDB_API_KEY": "abc"}, clear=False)
        p.start()
        self.addCleanup(p.stop)
        os.environ.pop("TMDB_READ_TOKEN", None)
        f = mock.patch.object(tmdb, "_fetch", fake_fetch)
        f.start()
        self.addCleanup(f.stop)

    def test_search_format_limit_and_cache(self):
        r = tmdb.search("filme")
        self.assertEqual(len(r), 10)
        self.assertEqual(r[0]["poster_url"], "https://image.tmdb.org/t/p/w342/p.jpg")
        self.assertEqual(r[0]["genres"], ["Comédia", "Drama"])
        self.assertEqual((r[0]["year"], r[0]["vote"]), (2015, 7.8))
        url = fake_fetch.calls[-1][0]
        self.assertIn("api_key=abc", url)
        self.assertIn("language=pt-BR", url)
        n = len(fake_fetch.calls)
        tmdb.search("filme")
        self.assertEqual(len(fake_fetch.calls), n)  # cache

    def test_movie_detail_providers(self):
        m = tmdb.movie(1)
        self.assertEqual(m["runtime"], 101)
        self.assertEqual(m["providers"][0]["name"], "Netflix")
        self.assertEqual(m["genres"], ["Comédia", "Drama"])

    def test_bearer_token(self):
        os.environ.pop("TMDB_API_KEY")
        with mock.patch.dict(os.environ, {"TMDB_READ_TOKEN": "tok"}):
            tmdb.search("a")
        url, headers = fake_fetch.calls[-1]
        self.assertEqual(headers["Authorization"], "Bearer tok")
        self.assertNotIn("api_key", url)

    def test_no_credentials(self):
        os.environ.pop("TMDB_API_KEY")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("TMDB_READ_TOKEN", None)
            with self.assertRaises(tmdb.TMDBError):
                tmdb.search("a")

    def test_options(self):
        o = tmdb.get_options()
        self.assertEqual({g["id"] for g in o["genres"]}, {35, 18})
        self.assertEqual(o["providers"][0]["id"], 8)
        self.assertIn("watch_region=BR", fake_fetch.calls[-1][0])

    def test_empty_search(self):
        self.assertEqual(tmdb.search("  "), [])


if __name__ == "__main__":
    unittest.main()
