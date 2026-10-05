import os  # reads environment variables
import psycopg  # the PostgreSQL driver
from psycopg.rows import dict_row  # makes rows come back as dictionaries
from dotenv import load_dotenv  # loads the .env file

load_dotenv()  # puts DB_PORT and DB_PASSWORD from .env into the environment


def connect() -> psycopg.Connection:  # opens one database connection
    return psycopg.connect(  # asks psycopg to connect
        host="localhost",  # the database runs on this computer, inside Docker
        port=int(os.environ["DB_PORT"]),  # the free port we saved in .env
        dbname="cheppandi",  # database name from docker-compose.yml
        user="cheppandi",  # login name from docker-compose.yml
        password=os.environ["DB_PASSWORD"],  # password stays in .env, never in code
        row_factory=dict_row,  # rows become {"column": value} dictionaries
    )