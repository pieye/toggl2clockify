"""
Config class
Parses json config into concrete types.
"""

import os
import json
import datetime
import logging

import dateutil

# pylint: disable=R0902
class Config:
    """
    Config class, safely converts from json to concrete types
    """

    def __init__(self):
        """
        Loads config from "config.json" and places into internal variables
        """
        self.logger = logging.getLogger("toggl2clockify")

        self.f_name = os.path.abspath("config.json")
        data = self.load_config()
        self.clockify_keys = self.parse_list(data, "ClockifyKeys")
        self.clockify_admin = self.parse_item(data, "ClockifyAdmin")
        self.toggl_key = self.parse_item(data, "TogglKey")
        self.start_time = self.parse_time(data, "StartTime")
        self.end_time = self.parse_time(data, "EndTime", datetime.datetime.now())
        self.workspaces = self.parse_list(data, "Workspaces", True)
        self.fallback_email = self.parse_item(data, "FallbackUserMail", True)

    def parse_list(self, data, key, missing_allowed=False):
        """
        Parses a list of strings, ensuring they are all strings
        """

        try:
            result = data[key]
        except KeyError as error:
            if missing_allowed:
                return None
            msg = "json entry '%s' missing in file %s"
            msg %= (key, self.f_name)
            raise KeyError(msg) from error

        if not isinstance(result, list):
            raise ValueError("json entry '%s' must be a list of strings" % result)

        for item in result:
            if not isinstance(item, str):
                raise ValueError("entry '%s' is not a string" % str(item))

        return result

    def parse_item(self, data, key, missing_allowed=False):
        """
        Parses a string value
        """
        if key not in data:
            if missing_allowed:
                return None
            raise KeyError("json entry '%s' missing in file %s" % (key, self.f_name))

        result = data[key]
        if not isinstance(result, str):
            raise ValueError("entry '%s' is not a string" % str(result))
        return result

    def parse_time(self, data, key, default=None):
        """
        Parses an ISO 8601 time string
        """

        try:
            result = data[key]
        except KeyError as error:
            if default is None:
                raise KeyError(
                    "json entry '%s' missing in file %s" % (key, self.f_name)
                ) from error

            self.logger.info(
                "json entry '%s' not in file, default to %s", key, str(default)
            )
            return default

        try:
            result = dateutil.parser.parse(result)
        except (ValueError, OverflowError) as error:
            raise ValueError(
                "Could not parse '%s' correctly, make sure it is a ISO 8601 time string"
                % result
            ) from error

        return result

    def load_config(self):
        """
        Loads the config file and returns a tuple of required info
        This function opens the json file then passes its logic to check_config
        """

        try:
            with open(self.f_name, "r") as file:
                try:
                    data = json.load(file)

                except json.JSONDecodeError as error:
                    self.logger.error("Error decoding file: %s", str(error))
                    raise
        except FileNotFoundError:
            self.logger.error("File %s not found", self.f_name)
            raise

        return data
