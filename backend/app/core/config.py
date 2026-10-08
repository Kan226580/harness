import os

import dotenv

dotenv.load_dotenv()

class Config:
    ENV = os.getenv("ENV") if os.getenv("ENV") else "dev"
