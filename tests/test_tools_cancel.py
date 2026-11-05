import pytest  # the test runner

from app.db import connect  # lets the test check and clean the database
from app.tools import Session, make_tools  # the call state and the toolbox

PHONE = "9999990002"  # a fake number used only by this file
DAY = "2030-06-15"  # a far future date so the test never touches real bookings


def wipe():  # deletes only the rows this file created
    with connect() as conn:  # open the database
        conn.execute("DELETE FROM booking_services WHERE booking_id IN (SELECT id FROM bookings WHERE customer_phone = %s)", (PHONE,))  # child rows first
        conn.execute("DELETE FROM bookings WHERE customer_phone = %s", (PHONE,))  # then the bookings


def active_count():  # how many bookings are still confirmed for the test phone number
    with connect() as conn:  # open the database
        return conn.execute("SELECT count(*) AS n FROM bookings WHERE customer_phone = %s AND status = 'confirmed'", (PHONE,)).fetchone()["n"]  # the number of rows


@pytest.fixture(autouse=True)  # runs around every test automatically
def clean():  # keeps tests independent of each other
    wipe()  # start from a clean state
    yield  # the test runs here
    wipe()  # leave nothing behind


def test_cancel_then_rebook_the_same_visit():  # book, cancel, then book exactly the same visit again
    session = Session()  # a fresh call
    tools = make_tools(session)  # the toolbox for this call
    args = ("Rebook Test", PHONE, "Meena", DAY, "12:00", ["haircut_men"])  # the same details every time
    session.turn = 1  # the caller asks for the booking
    tools["propose_booking"](*args)  # the agent prepares it
    session.turn = 2  # the caller says yes
    first = tools["confirm_booking"]()  # the first booking is saved
    assert first["status"] == "confirmed"  # it worked
    session.turn = 3  # the caller changes their mind
    assert tools["cancel_appointment"](first["booking_id"])["status"] == "cancelled"  # the booking is cancelled
    assert active_count() == 0  # nothing is confirmed any more
    session.turn = 4  # the caller changes their mind again
    proposal = tools["propose_booking"](*args)  # the same visit is proposed again
    assert proposal["status"] == "awaiting_confirmation"  # it is a new proposal, not already_confirmed
    session.turn = 5  # the caller says yes
    second = tools["confirm_booking"]()  # the second booking is saved
    assert second["status"] == "confirmed"  # a real new booking, not the cancelled one handed back
    assert second["booking_id"] != first["booking_id"]  # a different row
    assert active_count() == 1  # exactly one confirmed booking exists