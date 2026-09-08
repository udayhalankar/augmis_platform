
from fastapi import FastAPI


app = FastAPI(
    title="Hello AUGMIS",
    version="1.0.0"
)


@app.get("/")
def home():
    return {
        "application": "Hello AUGMIS",
        "message": "Application is running on AUGMIS Platform"
    }


@app.get("/health")
def health():
    return {
        "status": "healthy"
    }