"""Store and query movies using SQLite."""

import logging
import sqlite3

import pandas as pd

from .database import get_connection, initialize_database

logger = logging.getLogger(__name__)
MOVIE_COLUMNS = ["title", "release_year", "rating", "genre"]


class MovieStorage:
    def __init__(self, db_path="data/movies.db"):
        self.db_path = db_path
        initialize_database(self.db_path)

    def save(self, df):
        """Replace all movie rows in one transaction."""
        movies = df[MOVIE_COLUMNS].astype(object)
        movies = movies.where(pd.notna(movies), None)
        rows = list(movies.itertuples(index=False, name=None))

        connection = get_connection(self.db_path)
        try:
            connection.execute("BEGIN")
            connection.execute("DELETE FROM movies")
            connection.executemany(
                """
                INSERT INTO movies (title, release_year, rating, genre)
                VALUES (?, ?, ?, ?)
                """,
                rows,
            )
            connection.commit()
            logger.debug("Stored movies in SQLite: rows=%s", len(rows))
        except sqlite3.Error:
            connection.rollback()
            logger.exception("Failed to save movies")
            raise
        finally:
            connection.close()

    def get(self):
        """Return movie data ordered by id."""
        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                """
                SELECT title, release_year, rating, genre
                FROM movies
                ORDER BY id
                """
            ).fetchall()

            return pd.DataFrame(
                [tuple(row) for row in rows],
                columns=MOVIE_COLUMNS,
            )
        finally:
            connection.close()

    def _validate_columns(self, columns):
        """Allow only supported movie columns."""
        if not columns:
            logger.error("Select at least one column")
            raise ValueError("Select at least one column")

        for column in columns:
            if column not in MOVIE_COLUMNS:
                logger.error("Unsupported column: %s", column)
                raise ValueError(f"Unsupported column: {column}")

    def select_columns(self, columns, limit=5):
        """Return id and selected columns, ordered by id."""
        self._validate_columns(columns)
        selected_columns = ", ".join(["id"] + columns)

        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                f"""
                SELECT {selected_columns}
                FROM movies
                ORDER BY id
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

            results = [dict(row) for row in rows]
            logger.debug(
                "Selected movies: columns=%s, rows=%s",
                columns,
                len(results),
            )
            return results
        finally:
            connection.close()

    def count_movies(self):
        """Count stored movies using SQL."""
        connection = get_connection(self.db_path)
        try:
            row = connection.execute(
                "SELECT COUNT(*) FROM movies"
            ).fetchone()
            return row[0]
        finally:
            connection.close()

    def query_movies(self, columns, min_rating, limit):
        """Filter and sort movies using SQL."""
        self._validate_columns(columns)
        selected_columns = ", ".join(["id"] + columns)

        connection = get_connection(self.db_path)
        try:
            rows = connection.execute(
                f"""
                SELECT {selected_columns}
                FROM movies
                WHERE rating >= ?
                ORDER BY rating DESC, id ASC
                LIMIT ?
                """,
                (min_rating, limit),
            ).fetchall()

            results = [dict(row) for row in rows]
            logger.debug(
                "Queried movies: columns=%s, rows=%s",
                columns,
                len(results),
            )
            return results
        finally:
            connection.close()