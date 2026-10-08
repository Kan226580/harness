from fastapi import FastAPI

app = FastAPI(title="工程标书 AI Harness Agent")

@app.get("/health/live")
def live() -> dict[str, str]:
    return {"status": "ok"}