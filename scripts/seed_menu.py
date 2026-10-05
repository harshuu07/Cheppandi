import json  # reads the menu file
import os  # reads values from environment variables
from pathlib import Path  # builds file paths safely on Windows

import psycopg  # the PostgreSQL driver
from dotenv import load_dotenv  # loads .env into environment variables

load_dotenv()  # reads DB_PORT and DB_PASSWORD from the .env file

# connection details, with the password taken from .env so it never sits in code
DSN = (
    f"host=localhost port={os.environ['DB_PORT']} dbname=cheppandi "
    f"user=cheppandi password={os.environ['DB_PASSWORD']}"
)

# read the sample menu file as text and turn it into Python dictionaries
menu = json.loads(Path("data/menu.json").read_text(encoding="utf-8"))

with psycopg.connect(DSN) as conn:  # opens the connection and commits if no error happens
    with conn.cursor() as cur:  # a cursor is what actually runs SQL
        for s in menu["stylists"]:  # go through each stylist in the menu
            cur.execute(
                "INSERT INTO stylists (name, tier) VALUES (%s, %s) "
                "ON CONFLICT (name) DO UPDATE SET tier = EXCLUDED.tier",  # safe to run again
                (s["name"], s["tier"]),  # values go in separately to prevent SQL injection
            )
        for svc in menu["services"]:  # go through each service
            cur.execute(
                "INSERT INTO services (id, name, minutes, flat_price, price_source) "
                "VALUES (%s, %s, %s, %s, %s) "
                "ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, "
                "minutes = EXCLUDED.minutes, flat_price = EXCLUDED.flat_price, "
                "price_source = EXCLUDED.price_source",  # update if it already exists
                (svc["id"], svc["name"], svc["minutes"], svc.get("price"), svc["price_source"]),
            )
            for tier, price in svc.get("prices", {}).items():  # tier prices, if this service has any
                cur.execute(
                    "INSERT INTO service_prices (service_id, tier, price) VALUES (%s, %s, %s) "
                    "ON CONFLICT (service_id, tier) DO UPDATE SET price = EXCLUDED.price",
                    (svc["id"], tier, price),
                )

print("Menu loaded")  # confirms the script reached the end without errors