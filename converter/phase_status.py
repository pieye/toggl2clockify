"""
Small counter class for entries
"""


class PhaseStatus:
    """
    Small class to keep track of current phase's status
    """
    def __init__(self):
        self.num_entries = 0
        self.num_processed = 0
        self.num_queued = 0
        self.num_ok = 0
        self.num_skip = 0
        self.num_err = 0

    def add_ok(self):
        """
        adds one to processed/ok
        """
        self.num_processed += 1
        self.num_ok += 1

    def add_err(self):
        """
        adds one to err/ok
        """
        self.num_err += 1
        self.num_processed += 1

    def add_skip(self):
        """
        adds one to num_skip/processed
        """
        self.num_skip += 1
        self.num_processed += 1

    def get_result(self):
        """
        returns tuple of entries,ok,err,skip
        """
        return (self.num_entries, self.num_ok, self.num_skip, self.num_err)

    def reset(self):
        """
        resets counters back to 0
        """
        self.num_entries = 0
        self.num_processed = 0
        self.num_ok = 0
        self.num_err = 0
        self.num_skip = 0
