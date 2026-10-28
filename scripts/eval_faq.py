import json  # reads the questions file
import time  # lets us pause between requests
from pathlib import Path  # builds file paths safely on Windows

from app.faq import MODELS, search  # the search we already built and the two model names

questions = json.loads(Path("data/faq_questions.json").read_text(encoding="utf-8"))  # the test questions

for model in MODELS:  # run the same test for each model
    print(f"\n{model}")  # which model this section is about
    good_scores = []  # best scores of questions the FAQ can answer and we got right
    bad_scores = []  # best scores of questions the FAQ cannot answer
    hits = 0  # how many answerable questions found the right line first
    answerable = 0  # how many questions the FAQ can answer
    for item in questions:  # go through each test question
        top = search(item["q"], model, k=1)[0]  # the single closest FAQ line
        score = top["score"]  # how close it was
        if item["expected"] is None:  # the FAQ has no answer to this one
            bad_scores.append(score)  # remember how high a wrong match can score
            print(f"  {score:.3f}  no answer expected  {item['q']}")  # show it
        else:  # the FAQ can answer this one
            answerable += 1  # count it
            right = top["chunk_text"].startswith(item["expected"])  # did the right line come first
            if right:  # correct match
                hits += 1  # count the hit
                good_scores.append(score)  # remember the score of a correct match
            print(f"  {score:.3f}  {'RIGHT' if right else 'WRONG'}  {item['q']}")  # show the result
        time.sleep(0.7)  # small pause so we stay inside the free limits
    print(f"  right line first: {hits} of {answerable}")  # the hit rate
    if good_scores and bad_scores:  # we have both kinds of scores
        print(f"  lowest correct score: {min(good_scores):.3f}")  # the weakest good match
        print(f"  highest no answer score: {max(bad_scores):.3f}")  # the strongest bad match