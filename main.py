"""
Toggl2Clockify converter.
Sets up logging, parses arguments and then migrates.
"""
import logging

from converter.migrate import migrate
from converter.args import parse


if __name__ == "__main__":
    # Setup logger
    formatter = logging.Formatter(
        fmt="%(asctime)s - %(levelname)s - %(module)s - %(message)s"
    )

    handler = logging.StreamHandler()
    handler.setFormatter(formatter)

    # Clear the file.
    with open("log.txt", "wb") as f:
        f.write(b"")

    fileHandler = logging.FileHandler("log.txt")
    fileHandler.setFormatter(formatter)

    logger = logging.getLogger("toggl2clockify")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    logger.addHandler(fileHandler)

    # Parse the args
    args = parse()

    # Migrate
    migrate(args)
