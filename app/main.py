from fastapi import FastAPI

app = FastAPI(
    title="Story RAG API",
    version="0.1.0"
)


@app.get("/health")
async def health_check():
    return {"status": "ok"}