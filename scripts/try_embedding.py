import math  # for the square root used in the similarity formula
import os  # reads environment variables
from dotenv import load_dotenv  # loads the .env file
from google import genai  # Google's Python package for Gemini

load_dotenv(override=True)  # values in .env replace any old shell variables
client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])  # the connection to Google, the key is never printed

DOCS = [  # two lines from our FAQ file
    "Payment: cash, UPI and cards accepted.",  # the line that should match
    "Cancellation: please cancel or reschedule at least 3 hours before your slot.",  # an unrelated line
]
QUESTION = "Can I pay by card?"  # a caller's question, worded differently from the FAQ


def cosine(a, b):  # similarity score between two vectors, higher means closer in meaning
    dot = sum(x * y for x, y in zip(a, b))  # multiply matching numbers and add them up
    na = math.sqrt(sum(x * x for x in a))  # length of the first vector
    nb = math.sqrt(sum(x * x for x in b))  # length of the second vector
    return dot / (na * nb)  # divide so only the direction matters, not the size


def embed_one(model, text):  # one request per text, so we always get exactly one vector back
    result = client.models.embed_content(model=model, contents=text)  # ask Google for the vector
    print(f"  sent 1 text, got {len(result.embeddings)} vector(s)")  # shows if the model behaves as expected
    return result.embeddings[0].values  # the list of numbers


for model in ["gemini-embedding-001", "gemini-embedding-2"]:  # the two models we want to compare
    print(model)  # which model we are testing now
    try:  # a model may reject our request, so we catch that and keep going
        d0 = embed_one(model, DOCS[0])  # vector for the payment line
        d1 = embed_one(model, DOCS[1])  # vector for the cancellation line
        q = embed_one(model, QUESTION)  # vector for the question
    except Exception as exc:  # any failure lands here
        print(f"  failed: {type(exc).__name__}: {str(exc)[:200]}")  # short error, no key printed
        continue  # move on to the next model
    pay = cosine(q, d0)  # closeness to the payment line
    cancel = cosine(q, d1)  # closeness to the cancellation line
    print(f"  vector length {len(q)}, payment line {pay:.3f}, cancellation line {cancel:.3f}, right line wins: {pay > cancel}")  # the result