from datetime import date, datetime  # date tools for building test times

import pytest  # the test runner

from app import booking  # the code under test
from app.booking import IST  # India time zone
from app.db import connect  # lets tests clean up the database

DAY = date(2030, 1, 15)  # a far future date so tests never touch real bookings


def at(hour, minute=0):  # builds a time on the test day in India time
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=IST)  # timezone aware datetime


def wipe():  # deletes only rows created by tests
    with connect() as conn:  # open the database
        conn.execute("DELETE FROM booking_services WHERE booking_id IN (SELECT id FROM bookings WHERE idempotency_key LIKE 'pytest_%')")  # child rows first
        conn.execute("DELETE FROM bookings WHERE idempotency_key LIKE 'pytest_%'")  # then the bookings


@pytest.fixture(autouse=True)  # runs around every test automatically
def clean():  # keeps tests independent of each other
    wipe()  # start from a clean state
    yield  # the test runs here
    wipe()  # leave nothing behind


def book(key, stylist="Priya", hour=17, minute=0, services=("haircut_men",)):  # shortcut for test bookings
    return booking.create_booking(f"pytest_{key}", "Test Customer", "9999999999", stylist, at(hour, minute), list(services))  # real call


def test_books_and_prices():  # a normal booking
    r = book("a", services=("haircut_women", "pedicure"))  # 60 + 60 minutes
    assert r["total_price"] == 1090 + 790  # stylist level price plus pedicure
    assert r["ends_at"] == at(19)  # 17:00 plus two hours
    assert r["already_existed"] is False  # it is a new booking


def test_double_booking_rejected():  # the diary rule
    book("a")  # Priya 17:00 to 17:30
    with pytest.raises(booking.SlotTaken):  # an overlapping booking must fail
        book("b", minute=15)  # Priya at 17:15
    assert book("c", stylist="Meena")["status"] == "confirmed"  # a different stylist is fine


def test_same_key_does_not_duplicate():  # retries must be safe
    first = book("k1")  # first attempt
    second = book("k1")  # the same attempt again
    assert second["already_existed"] is True  # recognised as a repeat
    assert second["booking_id"] == first["booking_id"]  # same booking returned
    with connect() as conn:  # count the rows
        n = conn.execute("SELECT count(*) AS n FROM bookings WHERE idempotency_key = 'pytest_k1'").fetchone()["n"]  # rows with that key
    assert n == 1  # only one row exists


def test_cancel_frees_slot():  # cancelling makes the time available again
    first = book("a")  # book the slot
    assert booking.cancel_booking(first["booking_id"])["status"] == "cancelled"  # cancel it
    assert booking.cancel_booking(first["booking_id"])["already_cancelled"] is True  # cancelling twice is safe
    assert book("b")["already_existed"] is False  # the same time can be booked again


def test_tier_not_available():  # men's cut has no senior price
    with pytest.raises(booking.TierNotAvailable):  # must refuse instead of guessing a price
        book("a", stylist="Ravi")  # Ravi is senior level


def test_free_slots_excludes_booked():  # availability matches bookings
    book("a")  # Priya 17:00 to 17:30
    slots = booking.free_slots("Priya", ["haircut_men"], DAY)  # her free start times that day
    assert at(17) not in slots  # taken
    assert at(16, 30) in slots  # ends exactly when the booking starts, so allowed
    assert at(17, 30) in slots  # starts exactly when the booking ends, so allowed


def test_outside_hours():  # visits must fit before closing
    with pytest.raises(booking.OutsideHours):  # 20:30 plus 60 minutes passes 21:00
        book("a", hour=20, minute=30, services=("haircut_women",))  # too late