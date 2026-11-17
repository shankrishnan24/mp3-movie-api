# MP3 Movie API

For this project, I built on my MP2 API to work with movie data. I used SQLite to keep the movies saved even after restarting the server. The database and storage modules handle SQL queries to get movies, filter by rating, and choose which columns to return. I reused my data_pipeline code to validate and clean the data. I also added fakeredis to cache GET /movies responses for 90 seconds, with separate entries for different limits. Uploading or processing data clears the cache so it returns the updated movies. The models handle request and response formats, and the middleware logs requests and adds request IDs.
Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Start the API, then open http://127.0.0.1:8000/docs:

```bash
python -m uvicorn main:app --reload
```

Run tests:

```bash
python -m pytest tests -v
```

After uploading fixtures/sample_movies.csv, send POST /movies/process with:

```json
{
  "validation": {
    "required_columns": ["title", "release_year", "rating", "genre"],
    "numeric_columns": ["release_year", "rating"]
  },
  "processing": {
    "remove_duplicates": true,
    "missing": {"enabled": true, "axis": "rows"},
    "outliers": {
      "enabled": true,
      "columns": ["rating"],
      "method": "iqr",
      "threshold": 1.5
    }
  }
}
```

Expected response:

```json
{
  "validation_rows_removed": 0,
  "cleaning_report": {
    "rows_before": 20,
    "rows_after": 16,
    "rows_removed": 4,
    "columns_before": 4,
    "columns_after": 4,
    "columns_removed": 0
  }
}
```

GET /movies?limit=100 then returns 16 records. Repeating that request uses the cache.