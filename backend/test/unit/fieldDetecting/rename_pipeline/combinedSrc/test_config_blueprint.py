"""Blueprint for unit tests of `config.py` logging/setup behavior.

Required coverage:
- shared handler one-time initialization
- optional file logging when `SANDBOX_LOG_DIR` is set
- logger level based on debug mode
- no duplicate handlers per logger

Edge cases:
- repeated `get_logger` calls
- missing log directory env

Important context:
- Prevents handler leaks and log duplication in long-running services.
"""
