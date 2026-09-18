from fastapi import FastAPI


app = FastAPI()


@app.get("/")
def root():

    return {
        "application": "Hello AUGMIS",
        "version": "2.0.0",
        "message": "Application is running on AUGMIS Platform",
    }


@app.get("/health")
def health():

    return {
        "status": "healthy",
        "version": "2.0.0",
    }