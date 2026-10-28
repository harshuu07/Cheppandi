import os  # reads environment variables
import time  # lets us pause between requests
from pathlib import Path  # builds file paths safely on Windows

import psycopg  # the PostgreSQL driver
from dotenv import load_dotenv  # loads the .env file
from google import genai  # Google's Python package for Gemini

load_dotenv(override=True)  # values in .env replace any old shell variables
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])  # the connection to Google, the key is never printed

DSN = (  # database connection details, the password comes from .env
    f"host=127.0.0.1 port={os.environ['DB_PORT']} dbname=cheppandi "
    f"user=cheppandi password={os.environ['DB_PASSWORD']}"
)
MODELS = ["gemini-embedding-001", "gemini-embedding-2"]  # the two models we are comparing
SOURCE = "faq.md"  # the label stored next to each chunk


def read_chunks():  # one non empty line is one chunk, the title line is skipped
    lines = Path("data/faq.md").read_text(encoding="utf-8").splitlines()  # read the file line by line
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#")]  # drop blanks and the title


def embed(model, text):  # ask Google for one vector, retry a few times if we are rate limited
    for attempt in range(4):  # up to four tries
        try:  # the call can fail while we are over the free limit
            result = client.models.embed_content(model=model, contents=text)  # one text, one vector
            return result.embeddings[0].values  # the list of numbers
        except Exception as exc:  # any failure lands here
            if attempt == 3:  # the last try also failed
                raise  # give up and show the real error
            print(f"  retry after {type(exc).__name__}")  # tell the user we are waiting
            time.sleep(5 * (attempt + 1))  # wait longer after each failure


chunks = read_chunks()  # the policy lines from faq.md
print(f"{len(chunks)} chunks found")  # how many pieces we will store

with psycopg.connect(DSN) as conn:  # open the database, commit if nothing fails
    with conn.cursor() as cur:  # a cursor runs the SQL
        for text in chunks:  # go through each chunk
            cur.execute(
                "INSERT INTO faq_chunks (source, chunk_text) VALUES (%s, %s) "
                "ON CONFLICT (source, chunk_text) DO NOTHING",  # a repeated line is skipped
                (SOURCE, text),
            )
            cur.execute("SELECT id FROM faq_chunks WHERE source = %s AND chunk_text = %s", (SOURCE, text))  # find its id
            chunk_id = cur.fetchone()[0]  # the id of this chunk
            for model in MODELS:  # make one vector per model
                values = embed(model, text)  # the pin location from this model
                literal = "[" + ",".join(str(v) for v in values) + "]"  # the format pgvector reads
                cur.execute(
                    "INSERT INTO faq_embeddings (chunk_id, model, embedding) VALUES (%s, %s, %s::vector) "
                    "ON CONFLICT (chunk_id, model) DO UPDATE SET embedding = EXCLUDED.embedding",  # replace if it exists
                    (chunk_id, model, literal),
                )
            print(f"stored: {text[:50]}")  # progress, first 50 characters

print("done")  # reached only if everything worked