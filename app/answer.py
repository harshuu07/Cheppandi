import sys  # reads the question typed after the command

from google.genai import types  # settings objects for the chat call

from app.faq import _client, search  # the shared Google connection and our FAQ search

EMBED_MODEL = "gemini-embedding-001"  # which embedding model finds the FAQ lines
CHAT_MODEL = "gemini-3.5-flash-lite"  # which chat model writes the spoken answer
FLOOR = 0.55  # below this score even the best line is unrelated, so we skip the chat model
FALLBACK = "I'm sorry, I'm not sure about that. Can I help you with a booking instead?"  # said when we cannot answer

RULES = (  # the instructions the chat model must follow
    "You are the phone receptionist at Kathara, a hair salon. "
    "Answer the caller's question using ONLY the numbered facts provided. "
    "Never add prices, times or policies that are not in the facts. "
    "If the facts do not answer the question, reply with exactly: NOT_SURE "
    "Speak in one or two short sentences, with no lists and no special symbols."
)


def answer(question):  # returns the spoken answer and the FAQ lines that were used
    rows = search(question, EMBED_MODEL, k=3)  # the three closest FAQ lines
    if rows[0]["score"] < FLOOR:  # even the best line is unrelated
        return FALLBACK, rows  # do not bother the chat model
    facts = "\n".join(f"{i + 1}. {r['chunk_text']}" for i, r in enumerate(rows))  # number the lines
    prompt = f"Facts:\n{facts}\n\nCaller's question: {question}"  # facts first, then the question
    response = _client().models.generate_content(  # ask the chat model to write the answer
        model=CHAT_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(system_instruction=RULES, temperature=0),  # temperature 0 keeps answers steady
    )
    text = (response.text or "").strip()  # the reply, or empty if nothing came back
    if not text or "NOT_SURE" in text:  # the model says the facts do not cover it
        return FALLBACK, rows  # use the safe fallback sentence
    return text, rows  # the grounded answer


if __name__ == "__main__":  # runs only when we start this file directly
    question = " ".join(sys.argv[1:])  # everything typed after the command is the question
    if not question:  # nothing was typed
        raise SystemExit('Usage: python -m app.answer "your question"')  # show how to use it
    reply, rows = answer(question)  # get the answer
    print(f"\nAgent says: {reply}\n")  # what the caller would hear
    for r in rows:  # show which lines were used, so we can check the answer against them
        print(f"  {r['score']:.3f}  {r['chunk_text'][:70]}")