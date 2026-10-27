from datetime import date, datetime  # types FastAPI will read from the request

import psycopg  # to recognise the database's own error type
from fastapi import FastAPI, Request  # the door builder and the incoming request object
from fastapi.responses import JSONResponse  # lets us send our own error answers
from pydantic import BaseModel  # describes what a booking request must contain

from app import booking  # the receptionist's brain we already tested
from app.db import connect  # our phone line to Postgres

app = FastAPI(title="Cheppandi")  # the application object, uvicorn runs this

STATUS = {  # which HTTP status code each named booking error becomes
    booking.SlotTaken: 409,  # conflict, that time is already held
    booking.UnknownItem: 404,  # not found, stylist or service or booking
    booking.TierNotAvailable: 422,  # the request cannot be done as asked
    booking.OutsideHours: 422,  # the visit does not fit opening hours
    booking.BadInput: 422,  # empty name, bad phone number, missing timezone
}


class BookingRequest(BaseModel):  # the shape of the JSON a caller must send to book
    idempotency_key: str  # unique ticket for this attempt, makes retries safe
    customer_name: str  # name the caller gave
    customer_phone: str  # phone number the caller gave
    stylist: str  # stylist name such as Priya
    start: datetime  # start time with a timezone, such as 2030-01-15T17:00:00+05:30
    services: list[str]  # service ids such as haircut_men


@app.exception_handler(booking.BookingError)  # catches any named booking error from the brain
async def booking_error_handler(request: Request, exc: booking.BookingError):
    code = STATUS.get(type(exc), 400)  # look up the status code, default 400
    return JSONResponse(status_code=code, content={"error": type(exc).__name__, "detail": str(exc)})  # clear answer


@app.exception_handler(psycopg.OperationalError)  # catches database down or too slow
async def database_down_handler(request: Request, exc: psycopg.OperationalError):
    return JSONResponse(status_code=503, content={"error": "DatabaseUnavailable", "detail": "database unavailable"})  # 503 means a service behind us is down


@app.get("/health")  # is the door alive and the database answering
def health():
    with connect() as conn:  # open the database
        conn.execute("SELECT 1")  # ask the simplest possible question
    return {"status": "ok", "database": "ok"}  # reached only if the database answered


@app.get("/slots")  # list free start times
def slots(stylist: str, services: str, day: date):  # services arrives as a comma separated text
    ids = [s.strip() for s in services.split(",") if s.strip()]  # turn the text into a clean list
    return {"slots": booking.free_slots(stylist, ids, day)}  # free times in India time


@app.post("/bookings", status_code=201)  # create a booking
def create(req: BookingRequest):
    return booking.create_booking(  # the same function the tests proved
        req.idempotency_key, req.customer_name, req.customer_phone, req.stylist, req.start, req.services
    )


@app.post("/bookings/{booking_id}/cancel")  # cancel a booking, safe to call twice
def cancel(booking_id: str):
    return booking.cancel_booking(booking_id)  # the same function the tests proved