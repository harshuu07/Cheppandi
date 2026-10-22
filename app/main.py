from fastapi import FastAPI, HTTPException  # FastAPI builds the door, HTTPException sends a clean error answer
import psycopg  # needed to recognise the database's own error type
from app.db import connect  # our phone line to Postgres

app = FastAPI(title="Cheppandi")  # the application object, uvicorn will run this


@app.get("/health")  # a door named /health that answers GET requests
def health():  # runs every time someone knocks on /health
    try:  # we expect the database might be down, so we catch that case
        with connect() as conn:  # open the database
            conn.execute("SELECT 1")  # ask the simplest possible question
    except psycopg.OperationalError:  # the database refused or did not answer in time
        raise HTTPException(status_code=503, detail="database unavailable")  # 503 means a service behind us is down
    return {"status": "ok", "database": "ok"}  # reached only if the database answered
