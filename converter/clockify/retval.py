"""
Return value class
"""

from enum import Enum


class RetVal(Enum):
    """
    ClockifyAPI return value type
    """

    OK = 0
    ERR = 1
    EXISTS = 2
    FORBIDDEN = 3
