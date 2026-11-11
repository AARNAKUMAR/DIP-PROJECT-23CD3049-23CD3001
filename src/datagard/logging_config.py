"""One-time application logging configuration."""

import logging


def configure_logging(level: str) -> None:
    """Configure the root logger without adding duplicate handlers."""

    resolved_level = getattr(logging, level.upper(), None)
    if not isinstance(resolved_level, int):
        raise ValueError(f"Unsupported log level: {level}")

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=resolved_level,
            format="%(asctime)s %(levelname)s %(name)s %(message)s",
        )
    else:
        root_logger.setLevel(resolved_level)
