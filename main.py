import logging

from src.config import load_settings
from src.etl import run_etl
from src.logging_config import setup_logging


def main() -> None:
    settings = load_settings()
    log_file = setup_logging(
        settings.log_dir,
        settings.log_level,
        settings.run_timestamp,
    )
    logging.getLogger(__name__).info("Logging initialized file=%s", log_file.resolve())
    run_etl(settings)


if __name__ == "__main__":
    main()
