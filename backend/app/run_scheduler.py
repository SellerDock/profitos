import logging

from app.core.database import SessionLocal
from app.scheduler import run_scheduler
from app.services.bootstrap import assert_single_tenant

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")


if __name__ == "__main__":
    with SessionLocal() as db:
        assert_single_tenant(db)
    run_scheduler()
