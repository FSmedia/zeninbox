import uvicorn
import sys
import os

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8000))
    print("=" * 60)
    print("   ZENINBOX: Gated + Unroll.me + Cleanfox for Gmail")
    print("=" * 60)
    print(f" Dashboard URL: http://127.0.0.1:{port}")
    print(" Press Ctrl+C to stop.")
    print("=" * 60)
    uvicorn.run("app.main:app", host="127.0.0.1", port=port, reload=True)
