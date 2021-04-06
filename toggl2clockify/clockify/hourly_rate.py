"""
Hourly rate class
"""


class HourlyRate:
    """
    Class contains rate with amount and currency pair
    """

    def __init__(self, amount, currency="EUR"):
        self.rate = {}
        self.rate["amount"] = amount
        self.rate["currency"] = currency
