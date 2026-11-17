"""Tests for movie uploads, SQL queries, processing, and caching."""

import csv
import io

import main
from src import MovieStorage


def test_upload(uploaded_movies):
    assert uploaded_movies == {
        "filename": "sample_movies.csv",
        "rows": 20,
        "columns": 4,
        "column_names": ["title", "release_year", "rating", "genre"],
    }


def test_get_movies(client, uploaded_movies):
    response = client.get("/movies", params={"limit": 2})

    assert response.status_code == 200
    result = response.json()
    assert result["total_rows"] == 20
    assert len(result["data"]) == 2
    assert result["data"][0]["title"] == "Movie A"
    assert result["data"][1]["title"] == "Movie B"


def test_search(client, uploaded_movies):
    response = client.get(
        "/movies/search",
        params={
            "columns": ["title", "rating"],
            "min_rating": 8.5,
            "limit": 2,
        },
    )

    assert response.status_code == 200
    assert response.json() == [
        {"id": 4, "title": "Movie C", "rating": 9},
        {"id": 2, "title": "Movie B", "rating": 8.5},
    ]


def test_upload_replaces_movies(client, uploaded_movies, sample_csv):
    first = client.get("/movies")
    assert first.status_code == 200
    assert main.cache.get(100) == first.json()

    response = client.post(
        "/upload",
        files={"file": ("sample_movies.csv", sample_csv, "text/csv")},
    )

    assert response.status_code == 200
    assert main.cache.get(100) is None
    assert client.get("/movies").json()["total_rows"] == 20


def test_persistence(client, uploaded_movies, monkeypatch):
    reopened_storage = MovieStorage(main.storage.db_path)
    monkeypatch.setattr(main, "storage", reopened_storage)

    response = client.get("/movies", params={"limit": 1})

    assert response.status_code == 200
    assert response.json()["total_rows"] == 20
    assert response.json()["data"][0]["title"] == "Movie A"


def test_process_movies(client):
    csv_data = (
        "title,release_year,rating,genre\n"
        "Movie A,2020,8,Drama\n"
        "Movie A,2020,8,Drama\n"
        "Movie B,2021,,Comedy\n"
        "Movie C,2022,unknown,Action\n"
        "Movie D,2023,9,Drama\n"
    )
    upload = client.post(
        "/upload",
        files={"file": ("movies.csv", csv_data, "text/csv")},
    )
    assert upload.status_code == 200

    response = client.post(
        "/movies/process",
        json={"validation": {"numeric_columns": ["rating"]}},
    )

    assert response.status_code == 200
    result = response.json()
    assert result["validation_rows_removed"] == 1
    assert result["cleaning_report"]["rows_before"] == 4
    assert result["cleaning_report"]["rows_after"] == 2
    assert result["cleaning_report"]["rows_removed"] == 2

    movies = client.get("/movies").json()
    assert movies["total_rows"] == 2
    assert [movie["title"] for movie in movies["data"]] == [
        "Movie A",
        "Movie D",
    ]


def test_invalid_upload_and_health(client):
    response = client.post(
        "/upload",
        files={"file": ("notes.txt", b"not a CSV", "text/plain")},
    )

    assert response.status_code == 400

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert "x-request-id" in health.headers


def test_invalid_search_column(client, uploaded_movies):
    response = client.get(
        "/movies/search",
        params={"columns": "invalid_column"},
    )

    assert response.status_code == 400


def test_empty_database(client):
    response = client.get("/movies")

    assert response.status_code == 200
    assert response.json() == {"data": [], "total_rows": 0}
    assert client.post("/movies/process", json={}).status_code == 400


def test_movies_persist(client, test_storage, uploaded_movies, sample_csv):
    reopened = MovieStorage(test_storage.db_path)
    movies = reopened.get()

    assert reopened.count_movies() == 20
    assert list(movies.columns) == [
        "title",
        "release_year",
        "rating",
        "genre",
    ]

    original = list(csv.DictReader(io.StringIO(sample_csv.decode())))
    assert movies["title"].tolist() == [
        row["title"] for row in original
    ]

    stored = reopened.select_columns(["title"], limit=100)
    response = client.get("/movies", params={"limit": 100})

    assert response.status_code == 200
    expected_ids = list(range(1, 21))
    assert [row["id"] for row in stored] == expected_ids
    assert [row["id"] for row in response.json()["data"]] == expected_ids


def test_cache_and_processing(client, uploaded_movies, processing_body):
    responses = {}

    for limit in [100, 1]:
        response = client.get("/movies", params={"limit": limit})
        assert response.status_code == 200
        responses[limit] = response.json()
        assert main.cache.get(limit) == response.json()

    repeated = client.get("/movies", params={"limit": 100})
    assert repeated.status_code == 200
    assert repeated.json() == responses[100]

    processed = client.post("/movies/process", json=processing_body)

    assert processed.status_code == 200
    assert processed.json() == {
        "validation_rows_removed": 0,
        "cleaning_report": {
            "rows_before": 20,
            "rows_after": 16,
            "rows_removed": 4,
            "columns_before": 4,
            "columns_after": 4,
            "columns_removed": 0,
        },
    }

    assert main.cache.get(100) is None
    assert main.cache.get(1) is None

    response = client.get("/movies", params={"limit": 100})
    assert response.status_code == 200
    result = response.json()

    assert result["total_rows"] == 16
    assert [row["title"] for row in result["data"]] == [
        f"Movie {letter}" for letter in "ABCDEFGHIJKLMNOP"
    ]
    assert [row["id"] for row in result["data"]] == list(range(1, 17))
    assert main.cache.get(100) == result


def test_cache_hit_skips_database(client, uploaded_movies, monkeypatch):
    first = client.get("/movies", params={"limit": 100})
    assert first.status_code == 200

    def fail_if_called(*args, **kwargs):
        raise AssertionError("A cache hit should skip database reads")

    monkeypatch.setattr(main.storage, "select_columns", fail_if_called)
    monkeypatch.setattr(main.storage, "count_movies", fail_if_called)

    second = client.get("/movies", params={"limit": 100})
    assert second.status_code == 200
    assert second.json() == first.json()