from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

app = FastAPI(title="KINO BOT Mini App")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

HTML_FILE = Path(__file__).parent / "static" / "index.html"


@app.get("/")
async def home():
    return FileResponse(HTML_FILE)


@app.get("/health")
async def health():
    return {"status": "ok"}
