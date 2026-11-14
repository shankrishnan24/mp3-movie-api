"""Test fixtures using a temporary SQLite database."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from src import MovieStorage


@pytest.fixture
def client(tmp_path, monkeypatch):
    storage = MovieStorage(tmp_path / "movies.db")
    monkeypatch.setattr(main, "storage", storage)

    with TestClient(main.app) as test_client:
        yield test_client


@pytest.fixture
def sample_csv():
    path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "sample_movies.csv"
    )
    return path.read_bytes()


@pytest.fixture
def uploaded_movies(client, sample_csv):
    response = client.post(
        "/upload",
        files={"file": ("sample_movies.csv", sample_csv, "text/csv")},
    )
    assert response.status_code == 200
    return response.json()