"""
Entry and EntryQuery class
"""

import logging
import dateutil.parser
import pytz


def is_duplicate_entry(source, entries):
    """
    Returns if source exists inside entries
    """
    for entry in entries:
        different = source.diff_entry(entry)
        if not different:  # aka same
            return True
    return False


def time_to_utc(time):
    """
    Converts time from its relevant timezone to UTC
    """
    time = dateutil.parser.parse(time)
    utc = time.astimezone(pytz.UTC).isoformat().split("+")[0]
    return dateutil.parser.parse(utc)


def parse_end(t_entry):
    """
    Converts end_timestamp to utc.
    """
    end = t_entry["end"]
    if end is not None:
        end = time_to_utc(end)

    return end


def get_task_id_from_name(task_name, project_tasks):
    """
    get task_id from task_name
    """
    result = None
    if project_tasks is not None:
        for task in project_tasks:
            if task["name"] == task_name:
                result = task["id"]
    if result is None:
        raise RuntimeError("Task %s not found." % (task_name))
    return result


class Entry:
    """
    Entry class suitable for clockify_apis
    """

    def __init__(self, t_entry):
        self.logger = logging.getLogger("toggl2clockify")
        self.start = time_to_utc(t_entry["start"])
        self.utc_start = self.start
        self.end = parse_end(t_entry)

        self.description = t_entry["description"]
        self.project_name = t_entry["project"]
        self.client_name = t_entry["client"]
        self.billable = t_entry["is_billable"]
        self.tag_names = t_entry["tags"]
        self.task_name = t_entry["task"]
        self.email = None  # set externally
        self.workspace = None  # set externally
        self.timezone = None

        # Set later using API
        self.proj_id = None
        self.workspace_id = None
        self.task_id = None
        self.tag_ids = None
        self.user_id = None
        self.api_dict = None

    def process_ids(self, api):
        """
        Uses clockify api to find proj_id, client_id, workspace_id and task_id
        Constructs api dict
        """
        self.workspace_id = api.get_workspace_id(self.workspace)
        self.user_id = api.get_user_id(self.email)
        if self.project_name is not None:
            self.proj_id = api.get_project_id(
                self.project_name, self.client_name, self.workspace
            )

            if self.task_name is not None:
                proj_tasks = api.get_tasks_from_project_id(self.workspace, self.proj_id)
                self.task_id = get_task_id_from_name(self.task_name, proj_tasks)
                self.logger.info(
                    "Found task %s in project %s", self.task_name, self.project_name
                )
        else:
            self.logger.info("No project in entry %s", self.description)

        self.start = self.start.isoformat() + self.timezone

        if self.end is not None:
            self.end = self.end.isoformat() + self.timezone

        if self.tag_names is not None:
            self.tag_ids = []
            for tag in self.tag_names:
                tag_id = api.get_tag_id(tag, self.workspace)
                self.tag_ids.append(tag_id)

    def to_api_dict(self):
        """
        Converts internal data into Params api dictionary
        """
        params = {
            "start": self.start,
            "billable": self.billable,
            "description": self.description,
        }

        if self.proj_id is not None:
            params["projectId"] = self.proj_id

        if self.task_id is not None:
            params["taskId"] = self.task_id

        if self.end is not None:
            params["end"] = self.end
        else:
            params["end"] = self.start

        if self.tag_ids is not None:
            params["tagIds"] = self.tag_ids

        return params

    def diff_entry(self, other):
        """
        Returns true if this entry is different to the other entry
        """
        this = self.to_api_dict()

        if this["start"] != other["timeInterval"]["start"]:
            # self.logger.info("entry diff @start: %s %s",str(this["start"]),
            #                   str(entry["timeInterval"]["start"]))
            return True

        if "projectId" in this and this["projectId"] != other["projectId"]:
            return True
            # self.logger.info("entry diff @projectID: %s %s",
            # (str(params["projectId"]), str(d['projectId'])))
        if this["description"] != other["description"]:
            return True
            # self.logger.info("entry diff @desc: %s %s",
            # (str(params["description"]), str(d['description'])))
        if this["userId"] != other["userId"]:
            return True
            # self.logger.info("entry diff @userID: %s %s",
            # (str(self.userID), str(d['userId'])))

        # check if tags are identical
        this_tag_ids = this["tagIds"] if "tagIds" in this else []
        other_tag_ids = other["tagIds"] or []

        if set(this_tag_ids) != set(other_tag_ids):
            # self.logger.info("entry diff @tagNames: %s %s",
            # (str(set(tagNames)), str(set(tagNamesRcv))))
            return True
        return False


class EntryQuery:
    """
    A query to ask the API for entries
    """

    def __init__(self, *args):
        """
        1-arg: pass in an Entry
        2-arg: pass in email, workspace
        """
        self.email = None
        self.workspace = None
        self.description = ""
        self.project_name = None
        self.client_name = None
        self.start = None
        self.timezone = ""
        self.api_dict = None
        self.user_id = None

        if len(args) == 2:
            email, workspace = args
            self.email = email
            self.workspace = workspace
        elif len(args) == 1:
            self.parse_time_entry(args[0])
        else:
            raise ValueError("Expected 1 or 2 args, got %s" % str(args))

    def parse_time_entry(self, time_entry):
        """
        Match time_entry's settings
        """
        self.email = time_entry.email
        self.workspace = time_entry.workspace
        self.description = time_entry.description
        self.project_name = time_entry.project_name
        self.client_name = time_entry.client_name
        self.start = time_entry.utc_start
        self.timezone = time_entry.timezone
        self.user_id = time_entry.user_id

    def to_api_dict(self, api):
        """
        Lazily create api dictionary
        """
        if self.api_dict is None:
            params = {"description": self.description}

            if self.start is not None:
                self.start = self.start.isoformat() + self.timezone
                params["start"] = self.start

            if self.project_name is not None:
                proj_id = api.get_project_id(
                    self.project_name, self.client_name, self.workspace
                )
                params["project"] = proj_id

            self.api_dict = params
        return self.api_dict
