import hashlib  # makes a short fingerprint for the idempotency key
import json  # turns results into plain data
import uuid  # makes a short unique id for each call
from datetime import date, datetime, timedelta  # date and time types

import psycopg  # to recognise the database's own error type

from app import booking  # the receptionist's brain we already tested
from app.answer import FALLBACK, answer  # the grounded FAQ answering
from app.booking import IST  # India time zone
from app.db import connect  # our phone line to Postgres


class ConfirmationNeeded(booking.BookingError):  # raised when a booking is saved too early
    pass  # the class name carries the meaning


class Session:  # the notepad for one phone call, shared by the conversation loop and the tools
    def __init__(self):  # runs when a new call starts
        self.id = uuid.uuid4().hex[:8]  # short id for this call
        self.turn = 0  # how many messages the caller has sent so far
        self.proposal = None  # the booking waiting for the caller's yes
        self.confirmed = {}  # every booking saved in this call, looked up by its fingerprint
        self.last_booking_id = None  # the most recent confirmed booking that is still active


def _plain(result):  # turns datetimes and ids into plain text so the model can read the result
    return json.loads(json.dumps(result, default=lambda o: o.isoformat() if isinstance(o, (datetime, date)) else str(o)))


def _parse_day(day):  # turns "2030-02-20" into a date, or raises a clear error
    try:  # the text may not be a valid date
        return date.fromisoformat(day)  # the standard year month day format
    except ValueError:  # the model sent something else
        raise booking.BadInput("Day must look like 2030-02-20")  # tell it how to fix the call


def _parse_start(day, time_text):  # builds a start time in India time from two pieces of text
    d = _parse_day(day)  # the date part
    try:  # the time text may be malformed
        hh, mm = time_text.split(":")  # "17:30" becomes "17" and "30"
        return datetime(d.year, d.month, d.day, int(hh), int(mm), tzinfo=IST)  # a timezone aware start time
    except ValueError:  # wrong shape or impossible time
        raise booking.BadInput("Time must look like 17:30")  # tell it how to fix the call


def _fingerprint(phone, stylist, start, service_ids):  # a hashable summary of a booking, used to recognise repeats
    return (phone, stylist.lower(), start.isoformat(), tuple(sorted(service_ids)))  # the same visit always gives the same tuple


def _safe(name, args, fn):  # runs a tool, turns every failure into an answer the model can read, and prints a trace line
    try:  # normal path
        result = _plain(fn())  # run the tool and clean up the result
    except booking.BookingError as exc:  # a named booking problem such as SlotTaken
        result = {"error": type(exc).__name__, "detail": str(exc)}  # the model can act on the name
    except psycopg.OperationalError:  # database down or too slow
        result = {"error": "DatabaseUnavailable", "detail": "database unavailable"}  # clear signal
    except Exception as exc:  # anything unexpected, such as a Google error
        result = {"error": "ToolFailed", "detail": f"{type(exc).__name__}: {str(exc)[:100]}"}  # visible, not silent
    print(f"  [tool] {name}({args}) -> {json.dumps(result)[:160]}")  # trace line so we can watch every call
    return result  # handed back to the model


def make_tools(session):  # builds the toolbox for one call, tied to that call's notepad
    def get_menu() -> dict:
        """Returns the salon's stylists with their levels, and every service with its duration in minutes and price. Some services have one flat price and some have a price per stylist level."""
        def run():  # the real work, wrapped by _safe below
            with connect() as conn:  # open the database
                stylists = conn.execute("SELECT name, tier FROM stylists ORDER BY id").fetchall()  # who works here
                services = conn.execute("SELECT id, name, minutes, flat_price FROM services ORDER BY id").fetchall()  # what is offered
                prices = conn.execute("SELECT service_id, tier, price FROM service_prices").fetchall()  # prices by level
            by_service = {}  # service id to its price per level
            for p in prices:  # group the level prices
                by_service.setdefault(p["service_id"], {})[p["tier"]] = p["price"]  # one entry per level
            return {
                "stylists": stylists,  # names and levels
                "services": [  # each service with its details
                    {"id": s["id"], "name": s["name"], "minutes": s["minutes"],
                     "flat_price": s["flat_price"], "price_by_stylist_level": by_service.get(s["id"], {})}
                    for s in services
                ],
            }
        return _safe("get_menu", "", run)

    def find_free_slots(stylist: str, service_ids: list[str], day: str) -> dict:
        """Lists the free start times for one stylist on one day for the given service ids. The day must look like 2030-02-20. Times are in India time as HH:MM."""
        def run():  # the real work, wrapped by _safe below
            slots = booking.free_slots(stylist, service_ids, _parse_day(day))  # free start times from the tested brain
            return {"slots": [s.astimezone(IST).strftime("%H:%M") for s in slots]}  # plain HH:MM text
        return _safe("find_free_slots", f"{stylist}, {service_ids}, {day}", run)

    def propose_booking(customer_name: str, customer_phone: str, stylist: str, day: str, time: str, service_ids: list[str]) -> dict:
        """Checks a booking and prepares it WITHOUT saving it. Call it once you have the name, a confirmed 10 digit phone number, the stylist, the day as 2030-02-20, the time as 17:30 in India time, and the service ids. Then read the returned summary to the caller, including the total price, and wait for their clear yes. Call it again if anything changes. If the result says already_confirmed, the booking is already saved, so tell the caller it is booked."""
        def run():  # the real work, wrapped by _safe below
            name = customer_name.strip()  # remove stray spaces
            digits = "".join(ch for ch in customer_phone if ch.isdigit())  # phone digits only
            if not name:  # nothing left after trimming
                raise booking.BadInput("Name is required")  # refuse
            if len(digits) != 10:  # this demo uses 10 digit Indian mobile numbers
                raise booking.BadInput("Phone number must have 10 digits")  # refuse
            ids = list(dict.fromkeys(service_ids))  # remove repeated ids but keep order
            start = _parse_start(day, time)  # the start time as a real datetime
            with connect() as conn:  # open the database
                cur = conn.cursor()  # a cursor runs the SQL
                st = booking._stylist(cur, stylist)  # find the stylist, raises if unknown
                svcs = booking._services(cur, ids)  # find the services, raises if unknown
                prices = {s["id"]: booking._price(cur, s, st["tier"]) for s in svcs}  # price for this stylist level
            end = start + timedelta(minutes=sum(s["minutes"] for s in svcs))  # when the visit would finish
            opens, closes = booking._hours(start.date())  # that day's opening hours
            if start < opens or end > closes:  # outside opening hours
                raise booking.OutsideHours(f"We are open {booking.OPEN_HOUR}:00 to {booking.CLOSE_HOUR}:00")  # refuse
            fp = _fingerprint(digits, st["name"], start, ids)  # a summary of this exact booking
            if fp in session.confirmed:  # this exact booking was already saved in this call
                return {
                    **session.confirmed[fp],  # the saved booking, with all its details
                    "status": "already_confirmed",  # replaces the old status
                    "already_confirmed": True,  # an easy flag to check
                    "next_step": "This booking is already saved. Tell the caller it is booked. Do not book it again.",
                }
            if start not in booking.free_slots(st["name"], ids, start.date()):  # the stylist must really be free
                raise booking.SlotTaken("That stylist is not free at that time")  # refuse
            session.proposal = {  # remember the booking, and which turn it was proposed in
                "turn": session.turn, "name": name, "phone": digits,
                "stylist": st["name"], "start": start, "service_ids": ids,
            }
            return {
                "status": "awaiting_confirmation",  # nothing has been saved yet
                "customer_name": name,
                "phone": digits,
                "stylist": st["name"],
                "day": start.strftime("%A %d %B %Y"),  # for example Wednesday 04 November 2026
                "start": start.strftime("%H:%M"),
                "end": end.strftime("%H:%M"),
                "services": [{"name": s["name"], "price": prices[s["id"]]} for s in svcs],
                "total_price": sum(prices.values()),  # the figure the caller must hear
                "next_step": "Read this back to the caller and ask for a clear yes. Do not call confirm_booking until the caller has replied.",
            }
        return _safe("propose_booking", f"{customer_name}, {stylist}, {day} {time}, {service_ids}", run)

    def confirm_booking() -> dict:
        """Saves the booking that propose_booking prepared. Call it only after the caller has heard the read back and replied with a clear yes. It refuses if the caller has not replied since the read back. If it returns already_confirmed, the booking was saved earlier, so tell the caller it is booked."""
        def run():  # the real work, wrapped by _safe below
            p = session.proposal  # the booking waiting for confirmation
            if p is None:  # nothing is waiting
                if session.confirmed:  # but a booking was already saved in this call
                    last = list(session.confirmed.values())[-1]  # the most recent saved booking
                    return {**last, "already_confirmed": True}  # report it again, save nothing
                raise ConfirmationNeeded("There is no booking waiting. Call propose_booking first.")  # refuse
            if session.turn <= p["turn"]:  # the caller has not spoken since the proposal
                raise ConfirmationNeeded("The caller has not replied since the read back. Read the booking back and wait for a clear yes.")  # refuse
            raw = f"{session.id}|{p['turn']}|{p['phone']}|{p['stylist'].lower()}|{p['start'].isoformat()}|{sorted(p['service_ids'])}"  # defines this attempt, including the turn
            key = hashlib.sha256(raw.encode()).hexdigest()[:32]  # the same attempt gives the same ticket, so retries are safe
            result = booking.create_booking(key, p["name"], p["phone"], p["stylist"], p["start"], p["service_ids"])  # the tested brain
            session.confirmed[_fingerprint(p["phone"], p["stylist"], p["start"], p["service_ids"])] = result  # remember it
            session.last_booking_id = result["booking_id"]  # remember it for a later cancel
            session.proposal = None  # nothing is waiting any more
            return result
        return _safe("confirm_booking", "", run)

    def cancel_appointment(booking_id: str) -> dict:
        """Cancels an existing booking using the booking id that was returned when it was booked."""
        def run():  # the real work, wrapped by _safe below
            result = booking.cancel_booking(booking_id)  # the tested brain
            for fp in [k for k, v in session.confirmed.items() if v["booking_id"] == result["booking_id"]]:  # find the matching entries
                del session.confirmed[fp]  # forget them, so the same visit can be booked again
            if session.last_booking_id == result["booking_id"]:  # it was the most recent one
                session.last_booking_id = None  # nothing active is left to remember
            return result
        return _safe("cancel_appointment", booking_id, run)

    def answer_policy_question(question: str) -> dict:
        """Answers questions about salon hours, booking, cancellation, late arrival, payment and colour treatments, using only the salon's written policies. If grounded is false, the policies do not cover the question."""
        def run():  # the real work, wrapped by _safe below
            reply, _rows = answer(question)  # the grounded answering we built earlier
            return {"answer": reply, "grounded": reply != FALLBACK}  # grounded false means "we do not know"
        return _safe("answer_policy_question", question, run)

    return {  # a dictionary so we can pick tools by name
        "get_menu": get_menu,
        "find_free_slots": find_free_slots,
        "propose_booking": propose_booking,
        "confirm_booking": confirm_booking,
        "cancel_appointment": cancel_appointment,
        "answer_policy_question": answer_policy_question,
    }