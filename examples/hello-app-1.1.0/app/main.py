from fastapi import FastAPI


app = FastAPI()


@app.get("/")
def root():

    return {
        "application": "Hello AUGMIS",
        "version": "1.1.0",
        "message": "Application is running on AUGMIS Platform",
    }


@app.get("/health")
def health():

    return {
        "status": "healthy",
        "version": "1.1.0",
    }