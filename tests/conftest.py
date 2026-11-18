import os


# Keep unit tests isolated from any developer-configured PostgreSQL database.
os.environ["DATABASE_URL"] = ""
