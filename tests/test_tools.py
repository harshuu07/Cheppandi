from datetime import datetime  # date tools for building test times

import pytest  # the test runner

from app import booking  # the booking brain
from app.booking import IST  # India time zone
from app.db import connect  # lets tests check and clean the database
from app.tools import Session, make_tools  # the call state and the toolbox

PHONE = "9999990001"  # a fake number used only by these tests
DAY = "2030-05-15"  # a far future date so tests never touch real bookings


def wipe():  # deletes only the rows these tests created
    with connect() as conn:  # open the database
        conn.execute("DELETE FROM booking_services WHERE booking_id IN (SELECT id FROM bookings WHERE customer_phone = %s)", (PHONE,))  # child rows first
        conn.execute("DELETE FROM bookings WHERE customer_phone = %s", (PHONE,))  # then the bookings


def count():  # how many bookings exist for the test phone number
    with connect() as conn:  # open the database
        return conn.execute("SELECT count(*) AS n FROM bookings WHERE customer_phone = %s", (PHONE,)).fetchone()["n"]  # the number of rows


@pytest.fixture(autouse=True)  # runs around every test automatically
def clean():  # keeps tests independent of each other
    wipe()  # start from a clean state
    yield  # the test runs here
    wipe()  # leave nothing behind


def setup():  # a fresh call with its own toolbox
    session = Session()  # new call state
    return session, make_tools(session)  # the state and the tools tied to it


def propose(tools, service_ids=("haircut_men",)):  # shortcut for proposing the standard test booking
    return tools["propose_booking"]("Guard Test", PHONE, "Meena", DAY, "12:00", list(service_ids))  # saves nothing


def test_confirm_without_proposal_is_refused():  # nothing was proposed, so nothing can be saved
    session, tools = setup()  # a fresh call
    session.turn = 1  # the caller has spoken once
    assert tools["confirm_booking"]()["error"] == "ConfirmationNeeded"  # refused
    assert count() == 0  # nothing was saved


def test_confirm_in_same_turn_is_refused():  # the model proposes and confirms without waiting for the caller
    session, tools = setup()  # a fresh call
    session.turn = 1  # the caller has spoken once
    assert propose(tools)["status"] == "awaiting_confirmation"  # the proposal works
    assert count() == 0  # a proposal saves nothing
    assert tools["confirm_booking"]()["error"] == "ConfirmationNeeded"  # no reply from the caller yet, so refused
    assert count() == 0  # still nothing saved


def test_confirm_after_caller_reply_saves():  # the normal path
    session, tools = setup()  # a fresh call
    session.turn = 1  # the caller asks for the booking
    propose(tools)  # the agent prepares it
    session.turn = 2  # the caller replies with yes
    result = tools["confirm_booking"]()  # now it may save
    assert result["status"] == "confirmed"  # the booking is real
    assert session.last_booking_id == result["booking_id"]  # remembered for a later cancel
    assert count() == 1  # exactly one row exists


def test_second_confirm_is_refused():  # confirming twice must not book twice
    session, tools = setup()  # a fresh call
    session.turn = 1  # the caller asks for the booking
    propose(tools)  # the agent prepares it
    session.turn = 2  # the caller replies with yes
    tools["confirm_booking"]()  # the first confirm saves it
    session.turn = 3  # the caller says something else
    assert tools["confirm_booking"]()["error"] == "ConfirmationNeeded"  # nothing is waiting any more
    assert count() == 1  # still exactly one row


def test_changed_details_replace_the_proposal():  # the caller adds a manicure before saying yes
    session, tools = setup()  # a fresh call
    session.turn = 1  # the caller asks for the booking
    propose(tools)  # first proposal
    session.turn = 2  # the caller adds a service
    result = propose(tools, ("haircut_men", "manicure"))  # a new proposal replaces the old one
    assert result["total_price"] == 810 + 690  # Meena's men's cut plus the manicure
    assert session.proposal["service_ids"] == ["haircut_men", "manicure"]  # the waiting booking has both services
    assert session.proposal["turn"] == 2  # the clock restarts, so a fresh reply is needed
    assert tools["confirm_booking"]()["error"] == "ConfirmationNeeded"  # the caller has not replied to the new read back
    assert count() == 0  # nothing saved


def test_proposing_a_taken_slot_is_refused():  # a proposal must not offer a time that is gone
    session, tools = setup()  # a fresh call
    session.turn = 1  # the caller asks for the booking
    start = datetime(2030, 5, 15, 12, 0, tzinfo=IST)  # the same time the proposal will ask for
    booking.create_booking("pytest_tools_taken", "Someone Else", PHONE, "Meena", start, ["haircut_men"])  # book it directly
    assert propose(tools)["error"] == "SlotTaken"  # the proposal is refused
    assert session.proposal is None  # nothing is waiting