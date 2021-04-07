"""
Cached list for API
"""
import logging
import json


def dump_json(file_name, data):
    """
    dumps a dictionary into file_name
    """
    with open(file_name, "w") as file:
        file.write(json.dumps(data, indent=2))


class CachedList:
    """
    Simple pair for knowing if we need to reload data
    """

    def __init__(self, url, name, multi):
        self.logger = logging.getLogger("toggl2clockify")
        self.data = []
        self.need_resync = True
        self.multi = multi
        self.url = url
        self.name = name

    def file_name(self):
        """
        returns filename for this list
        """
        return "clockify_" + self.name

    def get_data(self, api, args):
        """
        Lazily resyncs data and returns it
        """
        if self.need_resync:
            self.refresh_data(api, args)
            self.need_resync = False
        return self.data

    def refresh_data(self, api, args):
        """
        Call api and store results.
        """
        url = self.url % args
        if self.multi:
            self.data = api.multi_get_request(url, sudo=True)
        else:
            retval = api.request(url, typ="GET", sudo=True)
            self.data = retval.json()

        file_name = self.file_name()
        self.logger.info(
            "finished getting %s, saving results to %s.json", file_name, file_name
        )

        dump_json(f"{file_name}.json", self.data)
