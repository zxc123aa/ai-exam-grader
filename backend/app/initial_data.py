import logging

from sqlmodel import Session

from app.core.db import engine, init_db
from app.services.knowledge_point_taxonomy import sync_knowledge_points

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def init() -> None:
    with Session(engine) as session:
        init_db(session)
        created = sync_knowledge_points(session)
        logger.info("Knowledge points synced, %s new nodes", created)


def main() -> None:
    logger.info("Creating initial data")
    init()
    logger.info("Initial data created")


if __name__ == "__main__":
    main()
