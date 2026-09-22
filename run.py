"""Convenience entrypoint: `python run.py`. For production use
`uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4` directly."""
import uvicorn

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
