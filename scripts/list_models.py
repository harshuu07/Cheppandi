import os  # reads environment variables
from dotenv import load_dotenv  # loads the .env file
from google import genai  # Google's Python package for Gemini

load_dotenv(override=True)  # values in .env replace any old shell variables

key = os.environ.get("GEMINI_API_KEY")  # read the key without ever printing it
if not key:  # nothing was found under that name
    raise SystemExit("GEMINI_API_KEY is missing from .env")  # stop with a clear message

client = genai.Client(api_key=key)  # the connection to Google using our key

try:  # the call can fail if the key is wrong or the network is down
    names = [m.name for m in client.models.list()]  # ask Google for every model this key can see
except Exception as exc:  # any failure lands here
    raise SystemExit(f"Call failed: {type(exc).__name__}: {str(exc)[:200]}")  # short error, no key printed

print(f"Key works. Models visible: {len(names)}")  # proves Google accepted the key
for n in names:  # go through every model name
    if "flash" in n.lower():  # keep only the fast Flash chat models
        print(n)  # show it