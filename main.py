"""Upload, retrieve, search, and process movies."""

import io
import logging
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, File, HTTPException, Query, UploadFile

from data_pipeline import (
    create_cleaning_report,
    process_data,
    validate_dataframe,
)
from src import (
    HealthResponse,
    MovieDataResponse,
    MovieProcessingReport,
    MovieStorage,
    MovieUploadInfo,
    ProcessConfig,
    log_requests,
    setup_logging,
)
from src.storage import MOVIE_COLUMNS

setup_logging(verbose=True)
logger = logging.getLogger(__name__)

app = FastAPI(title="Movie API", version="1.0.0")
app.middleware("http")(log_requests)

from src import MovieCache

storage = MovieStorage()
cache = MovieCache()

@app.get("/health", response_model=HealthResponse)
def health_check():
    """Check that the API is running."""
    return HealthResponse(status="ok", version="1.0.0")


@app.post("/upload", response_model=MovieUploadInfo)
async def upload_movies(file: UploadFile = File(...)):
    """Upload a CSV and replace the current movie collection."""
    filename = file.filename or ""

    if Path(filename).suffix.lower() != ".csv":
        logger.warning("Unsupported file format: %s", filename)
        raise HTTPException(
            status_code=400,
            detail="Unsupported file format. Upload a CSV file.",
        )

    contents = await file.read()

    try:
        df = pd.read_csv(io.BytesIO(contents))
    except (
        pd.errors.EmptyDataError,
        pd.errors.ParserError,
        UnicodeDecodeError,
    ) as error:
        logger.warning("CSV parsing failed: %s", filename)
        raise HTTPException(
            status_code=400,
            detail="Could not read the CSV. Check its format and encoding.",
        ) from error

    if len(df.columns) != len(MOVIE_COLUMNS) or set(
        df.columns
    ) != set(MOVIE_COLUMNS):
        logger.warning("Invalid movie columns: %s", list(df.columns))
        raise HTTPException(
            status_code=400,
            detail=f"CSV must contain exactly these columns: {MOVIE_COLUMNS}",
        )

    if df.empty:
        logger.warning("Uploaded CSV has no data rows: %s", filename)
        raise HTTPException(
            status_code=400,
            detail="CSV must contain at least one data row.",
        )

    df = df[MOVIE_COLUMNS]
    storage.save(df)
    cache.invalidate()

    logger.info(
        "Uploaded movies: filename=%s, rows=%s",
        filename,
        len(df),
    )

    return MovieUploadInfo(
        filename=filename,
        rows=len(df),
        columns=len(df.columns),
        column_names=list(df.columns),
    )


@app.get("/movies", response_model=MovieDataResponse)
def get_movies(limit: int = Query(default=100, ge=1)):
    cached = cache.get(limit)
    if cached is not None:
        logger.info("Returning cached movies: limit=%s", limit)
        return cached

    data = storage.select_columns(MOVIE_COLUMNS, limit)
    total_rows = storage.count_movies()
    response = MovieDataResponse(data=data, total_rows=total_rows)

    cache.set(limit, response.model_dump())
    logger.info("Retrieved movies: returned_rows=%s", len(data))
    return response

@app.get("/movies/search", response_model=list[dict])
def query_movies(
    columns: list[str] = Query(default=["title"]),
    min_rating: float = Query(default=0, ge=0, le=10),
    limit: int = Query(default=100, ge=1),
):
    """Search movies by minimum rating and selected columns."""
    try:
        results = storage.query_movies(columns, min_rating, limit)
    except ValueError as error:
        logger.warning("Invalid movie search: %s", error)
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    logger.info(
        "Queried movies: columns=%s, min_rating=%s, returned_rows=%s",
        columns,
        min_rating,
        len(results),
    )

    return results


@app.post("/movies/process", response_model=MovieProcessingReport)
def process_movies(config: ProcessConfig):
    """Validate and clean the stored movie collection."""
    df = storage.get()

    if df.empty:
        raise HTTPException(
            status_code=400,
            detail="No movies stored. Upload a CSV first.",
        )

    settings = config.model_dump()
    validation = settings["validation"]

    try:
        for column in validation["numeric_columns"]:
            if column not in df.columns:
                raise ValueError(f"Numeric column missing: {column}")

        validated = validate_dataframe(
            df,
            required_columns=validation["required_columns"],
            numeric_columns=validation["numeric_columns"],
        )

        validation_rows_removed = len(df) - len(validated)
        before_processing = validated.copy(deep=True)

        logger.info(
            "Validated movies: rows_removed=%s",
            validation_rows_removed,
        )

        processed = process_data(validated, settings)
        report = create_cleaning_report(before_processing, processed)

        missing_columns = [
            column for column in MOVIE_COLUMNS
            if column not in processed.columns
        ]
        if missing_columns:
            raise ValueError(
                f"Processing removed required movie columns: {missing_columns}"
            )

    except ValueError as error:
        logger.warning("Movie processing failed: %s", error)
        raise HTTPException(
            status_code=400,
            detail=str(error),
        ) from error

    storage.save(processed)
    cache.invalidate()

    logger.info(
        "Processed movies: validation_removed=%s, rows_before=%s, rows_after=%s",
        validation_rows_removed,
        len(before_processing),
        len(processed),
    )

    return MovieProcessingReport(
        validation_rows_removed=validation_rows_removed,
        cleaning_report=report,
    )