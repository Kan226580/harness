import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    ENV = os.environ.get("ENV")
