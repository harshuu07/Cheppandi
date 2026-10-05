from datetime import date, datetime, time, timedelta, timezone  # date and time tools

import psycopg  # needed to catch the database's own error types

from app.db import connect  # our connection helper

IST = timezone(timedelta(hours=5, minutes=30))  # India time, a fixed offset because India has no daylight saving
OPEN_HOUR = 11  # salon opens at 11:00, same as data/faq.md
CLOSE_HOUR = 21  # salon closes at 21:00
STEP_MINUTES = 30  # we offer start times every 30 minutes


class BookingError(Exception):  # parent class so callers can catch every booking problem at once
    pass  # no extra behaviour needed


class SlotTaken(BookingError):  # the stylist is already busy at that time
    pass  # the class name carries the meaning


class UnknownItem(BookingError):  # a stylist, service or booking does not exist
    pass  # the class name carries the meaning


class TierNotAvailable(BookingError):  # this stylist level has no price for the service
    pass  # the class name carries the meaning


class OutsideHours(BookingError):  # the visit would not fit inside opening hours
    pass  # the class name carries the meaning


class BadInput(BookingError):  # empty name, bad phone number or missing timezone
    pass  # the class name carries the meaning


def _stylist(cur, name):  # finds one stylist by name
    cur.execute("SELECT id, name, tier FROM stylists WHERE lower(name) = lower(%s)", (name,))  # ignores capital letters
    row = cur.fetchone()  # first match, or None
    if row is None:  # nobody has that name
        raise UnknownItem(f"No stylist named {name}")  # tell the caller clearly
    return row  # a dictionary with id, name and tier


def _services(cur, service_ids):  # loads the requested services in the order given
    if not service_ids:  # a booking needs at least one service
        raise BadInput("Choose at least one service")  # stop early with a clear message
    cur.execute("SELECT id, name, minutes, flat_price FROM services WHERE id = ANY(%s)", (list(service_ids),))  # one query for all ids
    found = {r["id"]: r for r in cur.fetchall()}  # index the rows by service id
    missing = [s for s in service_ids if s not in found]  # ids the database does not know
    if missing:  # at least one unknown id
        raise UnknownItem(f"Unknown service: {', '.join(missing)}")  # name the unknown ones
    return [found[s] for s in service_ids]  # keep the caller's order


def _price(cur, service, tier):  # price of one service for one stylist level
    if service["flat_price"] is not None:  # some services cost the same for every level
        return service["flat_price"]  # use that single price
    cur.execute("SELECT tier, price FROM service_prices WHERE service_id = %s", (service["id"],))  # prices by level
    table = {r["tier"]: r["price"] for r in cur.fetchall()}  # level to price lookup
    if tier not in table:  # this level does not offer the service
        raise TierNotAvailable(
            f"{service['name']} is not offered at the {tier} level. Available levels: {', '.join(table)}"
        )  # the message lists what we can offer instead
    return table[tier]  # the price for this level


def _hours(day: date):  # opening and closing moments for one date
    opens = datetime.combine(day, time(OPEN_HOUR), tzinfo=IST)  # 11:00 India time
    closes = datetime.combine(day, time(CLOSE_HOUR), tzinfo=IST)  # 21:00 India time
    return opens, closes  # both as timezone aware datetimes


def _summary(cur, booking_id):  # builds the full picture of one booking
    cur.execute(
        "SELECT b.id, b.status, b.customer_name, b.customer_phone, b.starts_at, b.ends_at, s.name AS stylist "
        "FROM bookings b JOIN stylists s ON s.id = b.stylist_id WHERE b.id = %s",
        (booking_id,),
    )  # booking plus the stylist's name
    b = cur.fetchone()  # the booking row
    cur.execute(
        "SELECT sv.name, bs.price FROM booking_services bs JOIN services sv ON sv.id = bs.service_id "
        "WHERE bs.booking_id = %s",
        (booking_id,),
    )  # the services with the price frozen at booking time
    items = cur.fetchall()  # list of {name, price}
    return {  # the dictionary the agent will read
        "booking_id": str(b["id"]),  # id as plain text
        "status": b["status"],  # confirmed or cancelled
        "customer_name": b["customer_name"],  # as the caller gave it
        "customer_phone": b["customer_phone"],  # digits only
        "stylist": b["stylist"],  # stylist name
        "starts_at": b["starts_at"].astimezone(IST),  # shown in India time
        "ends_at": b["ends_at"].astimezone(IST),  # shown in India time
        "services": items,  # services and prices
        "total_price": sum(i["price"] for i in items),  # total in rupees
    }


def free_slots(stylist_name, service_ids, day: date):  # list start times that are still free
    service_ids = list(dict.fromkeys(service_ids))  # remove repeated ids but keep order
    with connect() as conn:  # open the database, close it when done
        cur = conn.cursor()  # a cursor runs the SQL
        stylist = _stylist(cur, stylist_name)  # who the caller wants
        services = _services(cur, service_ids)  # what they want done
        need = timedelta(minutes=sum(s["minutes"] for s in services))  # total visit length
        opens, closes = _hours(day)  # that day's opening hours
        cur.execute(
            "SELECT starts_at, ends_at FROM bookings "
            "WHERE stylist_id = %s AND status = 'confirmed' AND starts_at < %s AND ends_at > %s",
            (stylist["id"], closes, opens),
        )  # only this stylist's confirmed bookings that touch that day
        busy = cur.fetchall()  # their busy periods
    now = datetime.now(IST)  # never offer a time that has already passed
    slots = []  # start times we will return
    start = opens  # begin at opening time
    while start + need <= closes:  # keep going while the whole visit fits before closing
        end = start + need  # when this visit would finish
        clash = any(start < b["ends_at"] and end > b["starts_at"] for b in busy)  # overlap test
        if not clash and start > now:  # free and in the future
            slots.append(start)  # offer it
        start += timedelta(minutes=STEP_MINUTES)  # try the next half hour
    return slots  # all free start times


def create_booking(idempotency_key, customer_name, customer_phone, stylist_name, start, service_ids):  # books a visit
    name = customer_name.strip()  # remove stray spaces
    phone = "".join(ch for ch in customer_phone if ch.isdigit())  # keep digits only
    if not name:  # nothing left after trimming
        raise BadInput("Name is required")  # refuse
    if len(phone) != 10:  # this demo uses 10 digit Indian mobile numbers
        raise BadInput("Phone number must have 10 digits")  # refuse
    if start.tzinfo is None:  # a time without a timezone is ambiguous
        raise BadInput("Start time must include a timezone")  # refuse
    service_ids = list(dict.fromkeys(service_ids))  # remove repeated ids
    try:  # the database may reject an overlap, which we translate below
        with connect() as conn:  # open the database
            with conn.transaction():  # everything inside is saved together or not at all
                cur = conn.cursor()  # a cursor runs the SQL
                stylist = _stylist(cur, stylist_name)  # find the stylist
                services = _services(cur, service_ids)  # find the services
                prices = {s["id"]: _price(cur, s, stylist["tier"]) for s in services}  # price each one for this level
                end = start + timedelta(minutes=sum(s["minutes"] for s in services))  # when the visit ends
                opens, closes = _hours(start.astimezone(IST).date())  # hours for that India date
                if start < opens or end > closes:  # outside opening hours
                    raise OutsideHours(f"We are open {OPEN_HOUR}:00 to {CLOSE_HOUR}:00")  # refuse
                cur.execute(
                    "INSERT INTO bookings (idempotency_key, customer_name, customer_phone, stylist_id, starts_at, ends_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (idempotency_key) DO NOTHING RETURNING id",
                    (idempotency_key, name, phone, stylist["id"], start, end),
                )  # a repeated key inserts nothing instead of failing
                row = cur.fetchone()  # the new id, or None if the key was already used
                if row is None:  # this attempt was seen before
                    cur.execute("SELECT id FROM bookings WHERE idempotency_key = %s", (idempotency_key,))  # find the original
                    return {**_summary(cur, cur.fetchone()["id"]), "already_existed": True}  # return it unchanged
                for s in services:  # save each service with its frozen price
                    cur.execute(
                        "INSERT INTO booking_services (booking_id, service_id, price) VALUES (%s, %s, %s)",
                        (row["id"], s["id"], prices[s["id"]]),
                    )
                return {**_summary(cur, row["id"]), "already_existed": False}  # the confirmed booking
    except psycopg.errors.ExclusionViolation as exc:  # the database refused an overlap
        raise SlotTaken("That stylist is already booked at that time") from exc  # a clear error for the agent


def cancel_booking(booking_id):  # cancels a booking, safe to call twice
    try:  # a malformed id raises a database error we translate below
        with connect() as conn:  # open the database
            with conn.transaction():  # save the change safely
                cur = conn.cursor()  # a cursor runs the SQL
                cur.execute(
                    "UPDATE bookings SET status = 'cancelled' WHERE id = %s AND status = 'confirmed' RETURNING id",
                    (booking_id,),
                )  # only a confirmed booking changes
                changed = cur.fetchone()  # None if nothing changed
                cur.execute("SELECT id FROM bookings WHERE id = %s", (booking_id,))  # does it exist at all
                if cur.fetchone() is None:  # no such booking
                    raise UnknownItem("No such booking")  # refuse
                result = _summary(cur, booking_id)  # current state of the booking
                result["already_cancelled"] = changed is None  # true when it was cancelled earlier
                return result  # report what happened
    except psycopg.errors.InvalidTextRepresentation as exc:  # the id was not a valid UUID
        raise UnknownItem("No such booking") from exc  # same clear error