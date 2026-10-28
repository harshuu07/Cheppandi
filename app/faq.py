import os  # reads environment variables
import sys  # lets us read the question typed after the command
from google import genai  # Google's Python package for Gemini
from app.db import connect  # our database connection, importing it also loads .env

MODELS = ["gemini-embedding-001", "gemini-embedding-2"]  # the two models we are comparing


_CLIENT = None  # holds one shared connection once it has been created


def _client():  # builds the Google connection once and reuses it, so it is never closed early
    global _CLIENT  # lets this function change the variable above
    if _CLIENT is None:  # the connection has not been created yet
        _CLIENT = genai.Client(api_key=os.environ["GEMINI_API_KEY"])  # the key is read, never printed
    return _CLIENT  # the same connection every time


def embed_question(model, question):  # turns the caller's question into a pin
    result = _client().models.embed_content(model=model, contents=question)  # one text, one vector
    return result.embeddings[0].values  # the list of numbers


def search(question, model, k=3):  # finds the k closest FAQ sentences for one model
    values = embed_question(model, question)  # the question's pin
    literal = "[" + ",".join(str(v) for v in values) + "]"  # the format pgvector reads
    with connect() as conn:  # open the database
        rows = conn.execute(
            "SELECT c.chunk_text, 1 - (e.embedding <=> %s::vector) AS score "  # score is 1 minus the distance
            "FROM faq_embeddings e JOIN faq_chunks c ON c.id = e.chunk_id "  # join each pin to its sentence
            "WHERE e.model = %s "  # only pins made by this model
            "ORDER BY e.embedding <=> %s::vector LIMIT %s",  # closest first, keep only k
            (literal, model, literal, k),
        ).fetchall()  # the list of results
    return rows  # each row has chunk_text and score


if __name__ == "__main__":  # runs only when we start this file directly
    question = " ".join(sys.argv[1:])  # everything typed after the command is the question
    if not question:  # nothing was typed
        raise SystemExit('Usage: python -m app.faq "your question"')  # show how to use it
    for model in MODELS:  # try both models on the same question
        print(model)  # which model gave the results below
        for row in search(question, model):  # the three closest sentences
            print(f"  {row['score']:.3f}  {row['chunk_text'][:70]}")  # score and the start of the sentence