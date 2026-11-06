"""Ishga tushirish: python main.py  (Render'da Procfile uvicorn'ni o'zi ishga tushiradi)."""
import os

import uvicorn

if __name__ == "__main__":
    uvicorn.run("miniapp.app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
