import time  # lets us pause between messages
from datetime import datetime, timedelta  # date and time tools

from app.agent import new_chat  # starts one conversation with its own toolbox
from app.booking import IST  # India time zone
from app.db import connect  # lets us read the diary and clean up

RUNS = 1  # how many times each scenario is repeated, raise this to 3 once it works
PAUSE = 4  # seconds to wait between messages, so we stay inside the free limits
MAX_YES = 5  # the robot says yes at most this many times while waiting for a booking
RETRIES = 3  # how many times a rate limited message is tried again
WAIT = 35  # seconds to wait before trying a rate limited message again

TOMORROW = (datetime.now(IST) + timedelta(days=1)).date()  # the date the agent will understand as tomorrow
EXPECTED_START = datetime(TOMORROW.year, TOMORROW.month, TOMORROW.day, 15, 0, tzinfo=IST)  # 3 pm India time tomorrow


def wipe(phone):  # deletes only the rows made with this scenario's fake phone number
    with connect() as conn:  # open the database
        conn.execute("DELETE FROM booking_services WHERE booking_id IN (SELECT id FROM bookings WHERE customer_phone = %s)", (phone,))  # child rows first
        conn.execute("DELETE FROM bookings WHERE customer_phone = %s", (phone,))  # then the bookings


def diary(phone):  # reads every booking made with this phone number, with its services and total
    with connect() as conn:  # open the database
        return conn.execute(
            "SELECT b.status, s.name AS stylist, b.starts_at, "  # what the booking looks like
            "array_agg(bs.service_id ORDER BY bs.service_id) AS services, sum(bs.price) AS total "  # its services and total price
            "FROM bookings b JOIN stylists s ON s.id = b.stylist_id "  # add the stylist's name
            "LEFT JOIN booking_services bs ON bs.booking_id = b.id "  # add the services
            "WHERE b.customer_phone = %s GROUP BY b.id, s.name",  # one row per booking
            (phone,),
        ).fetchall()  # the list of bookings


def confirmed(phone):  # only the bookings that are still confirmed
    return [r for r in diary(phone) if r["status"] == "confirmed"]  # drop cancelled ones


class Caller:  # the robot caller, it wraps one conversation and remembers what happened
    def __init__(self):  # runs when a new call starts
        self.chat, self.session = new_chat()  # a fresh agent conversation
        self.last_reply = ""  # the agent's most recent sentence
        self.error = None  # set if Google refused or failed

    def say(self, text):  # sends one message to the agent, and waits and tries again if Google is rate limiting
        if self.error:  # an earlier message already failed
            return  # stop talking
        self.session.turn += 1  # count the message once, the booking guard depends on this
        for attempt in range(RETRIES + 1):  # the first try plus the retries
            try:  # the Google call can fail, for example when rate limited
                response = self.chat.send_message(text)  # the agent replies, calling tools if it needs them
                self.last_reply = (response.text or "").strip()  # what the caller would hear
                break  # it worked, so stop trying
            except Exception as exc:  # any failure lands here
                message = str(exc)  # the full error text
                if "429" in message and attempt < RETRIES:  # rate limited and we still have retries left
                    print(f"  rate limited, waiting {WAIT}s (retry {attempt + 1} of {RETRIES})")  # tell the user why it is slow
                    time.sleep(WAIT)  # let the per minute allowance recover
                    continue  # try the same message again
                self.error = f"{type(exc).__name__}: {message[:600]}"  # remember it, this is an ERROR not a FAIL
                break  # give up on this message
        time.sleep(PAUSE)  # wait before the next message

    def yes_until(self, done):  # says yes to whatever the agent asks until done() is true
        for _ in range(MAX_YES):  # at most MAX_YES times
            if done() or self.error:  # finished, or something broke
                return  # stop
            self.say("Yes, that is correct.")  # answer the agent's question


def opening(phone, extra):  # the first message, with every detail the agent needs
    return (
        f"Hi, I would like a men's haircut with Arjun tomorrow at 3 pm. My name is Test Caller and my phone number is {phone}. "
        f"{extra}"
    )


def scenario_happy(c, phone):  # a normal booking
    c.say(opening(phone, "No manicure or pedicure and no other services please."))  # all details at once
    c.yes_until(lambda: len(confirmed(phone)) >= 1)  # confirm whatever is asked
    rows = confirmed(phone)  # what the diary shows
    if len(rows) != 1:  # exactly one booking is expected
        return f"expected 1 confirmed booking, found {len(rows)}"  # fail with a reason
    r = rows[0]  # the booking
    if r["stylist"] != "Arjun" or r["starts_at"] != EXPECTED_START:  # the right person and time
        return f"wrong stylist or time: {r['stylist']} {r['starts_at'].astimezone(IST):%d %b %H:%M}"  # fail with a reason
    if r["services"] != ["haircut_men"] or r["total"] != 990:  # the right service and price
        return f"wrong services or total: {r['services']} {r['total']}"  # fail with a reason
    return None  # None means the scenario passed


def scenario_no_yes(c, phone):  # the caller never confirms
    c.say(opening(phone, "No manicure or pedicure and no other services please."))  # all details at once
    c.say("Hmm, let me think about it and call you back.")  # the caller backs out
    n = len(diary(phone))  # how many bookings exist
    return None if n == 0 else f"expected 0 bookings, found {n}"  # nothing may be saved


def scenario_add_manicure(c, phone):  # the caller adds a manicure
    c.say(opening(phone, "Please add a manicure to the visit, and no other services."))  # all details at once
    c.yes_until(lambda: len(confirmed(phone)) >= 1)  # confirm whatever is asked
    rows = confirmed(phone)  # what the diary shows
    if len(rows) != 1:  # exactly one booking is expected
        return f"expected 1 confirmed booking, found {len(rows)}"  # fail with a reason
    r = rows[0]  # the booking
    if r["services"] != ["haircut_men", "manicure"] or r["total"] != 990 + 690:  # both services and the right total
        return f"wrong services or total: {r['services']} {r['total']}"  # fail with a reason
    return None  # passed


def scenario_cancel(c, phone):  # the caller books and then changes their mind
    c.say(opening(phone, "No manicure or pedicure and no other services please."))  # all details at once
    c.yes_until(lambda: len(confirmed(phone)) >= 1)  # confirm whatever is asked
    if len(confirmed(phone)) != 1:  # the booking never happened, so there is nothing to cancel
        return "setup failed, no confirmed booking to cancel"  # fail with a reason
    c.say("Actually I have changed my mind, please cancel everything.")  # the change of mind
    c.yes_until(lambda: len(confirmed(phone)) == 0)  # say yes if the agent asks to confirm the cancellation
    left = len(confirmed(phone))  # confirmed bookings remaining
    return None if left == 0 else f"{left} booking still confirmed after the cancel request"  # none may remain


SCENARIOS = [  # name, function, fake phone number
    ("happy path", scenario_happy, "9999990011"),
    ("no yes, no booking", scenario_no_yes, "9999990012"),
    ("add manicure", scenario_add_manicure, "9999990013"),
    ("change of mind", scenario_cancel, "9999990014"),
]

summary = []  # one line per scenario for the final table
for name, fn, phone in SCENARIOS:  # go through each scenario
    results = []  # PASS, FAIL or ERROR for each run
    for run in range(RUNS):  # repeat the scenario
        print(f"\n=== {name}, run {run + 1} of {RUNS} ===")  # a header so the output is easy to follow
        wipe(phone)  # start with a clean diary for this phone number
        c = Caller()  # a fresh conversation
        reason = fn(c, phone)  # play the script and check the diary
        if c.error:  # Google failed, so the result says nothing about the agent
            results.append("ERROR")  # not counted as a failure
            print(f"  ERROR: {c.error}")  # show why, in full
        elif reason is None:  # everything matched
            results.append("PASS")  # success
            print("  PASS")  # show it
        else:  # something did not match
            results.append("FAIL")  # failure
            print(f"  FAIL: {reason}")  # show why
            print(f"  last agent reply: {c.last_reply[:150]}")  # helps us see what went wrong
        wipe(phone)  # leave nothing behind
    summary.append((name, results))  # remember this scenario's results

print("\n=== SUMMARY ===")  # the final table
for name, results in summary:  # one line per scenario
    print(f"  {name}: {results.count('PASS')} pass, {results.count('FAIL')} fail, {results.count('ERROR')} error")  # the counts