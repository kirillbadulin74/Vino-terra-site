from __future__ import annotations

import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv


load_dotenv(Path(__file__).resolve().parent / ".env")


if __name__ == "__main__":
    uvicorn.run(
        "src.web_api:app",
        host=os.getenv("API_HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8080")),
        reload=os.getenv("API_RELOAD", "0") == "1",
    )
