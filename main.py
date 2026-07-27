from src.config import load_settings
from src.etl import run_etl


def main() -> None:
    settings = load_settings()
    run_etl(settings)


if __name__ == "__main__":
    main()
