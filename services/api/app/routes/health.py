from fastapi import APIRouter

from sqlalchemy import text

from services.api.app.db.session import engine


router = APIRouter(
    tags=["Health"]
)


@router.get("/health")
def health():

    database = "down"

    try:

        with engine.connect() as connection:

            connection.execute(
                text("SELECT 1")
            )

        database = "up"

    except Exception:
        database = "down"

    return {
        "service":
            "AUGMIS SaaS Platform API",

        "status":
            (
                "healthy"
                if database == "up"
                else "degraded"
            ),

        "database":
            database
    }