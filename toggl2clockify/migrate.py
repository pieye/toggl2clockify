#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Migrate module
Constructs a Clue object and iterates over workspaces to migrate data
"""

__author__ = "Markus Proeller"
__copyright__ = "Copyright 2019, pieye GmbH (www.pieye.org)"
__maintainer__ = "Markus Proeller"
__email__ = "markus.proeller@pieye.org"


import logging
import os
import json
import datetime
import sys
import dateutil


from toggl2clockify.Clue import Clue

logger = logging.getLogger("toggl2clockify")


def query_yes_no(question, default="yes"):
    """Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    """
    valid = {"yes": True, "y": True, "ye": True, "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
        choice = input().lower()
        if default is not None and choice == "":
            return valid[default]
        if choice in valid:
            return valid[choice]
        sys.stdout.write("Please respond with 'yes' or 'no' " "(or 'y' or 'n').\n")


def load_config():
    """
    Loads the config file and returns a tuple of required info
    This function opens the json file then passes its logic to check_config
    """
    f_name = os.path.abspath("config.json")

    try:
        with open(f_name, "r") as file:
            try:
                data = json.load(file)
                
            except json.JSONDecodeError as error:
                logger.error("Error decoding file: %s", str(error))        
    except FileNotFoundError:
        logger.error("File %s not found", f_name)

    return check_config(data, f_name)


def check_config(data, f_name):
    """
    Tries to parse each config item, and then returns a (success, values_tuple)
    """

    if "ClockifyKeys" not in data:
        logger.error("json entry 'ClockifyKeys' missing in file %s", f_name)
        return (False, None)

    c_keys = data["ClockifyKeys"]
    if not isinstance(c_keys, list):
        logger.error("json entry 'ClockifyKeys' must be a list of strings")
        return (False, None)

    if "ClockifyAdmin" not in data:
        logger.error("json entry 'ClockifyAdmin' missing in file %s", f_name)
        return (False, None)

    c_admin = data["ClockifyAdmin"]
    if not isinstance(c_admin, str):
        logger.error("json entry 'ClockifyAdmin' must be a string")
        return (False, None)

    if "TogglKey" not in data:
        logger.error("json entry 'TogglKey' missing in file %s", f_name)
        return (False, None)

    toggl_key = data["TogglKey"]
    if not isinstance(toggl_key, str):
        logger.error("json entry 'TogglKey' must be a string")
        return (False, None)

    if "StartTime" not in data:
        logger.error("json entry 'StartTime' missing in file %s", f_name)
        return (False, None)

    try:
        start_time = dateutil.parser.parse(data["StartTime"])
    except (ValueError, OverflowError):
        logger.error(
            "Could not parse 'StartTime' correctly make sure it is a ISO 8601 time string"
        )
        return (False, None)

    if "EndTime" in data:
        try:
            end_time = dateutil.parser.parse(data["EndTime"])
        except (ValueError, OverflowError):
            logger.error(
                "Could not parse 'EndTime' correctly make sure it is a ISO 8601 time string"
            )
            return (False, None)
    else:
        logger.info(
            "'EndTime' not found in config file importing all entries until now"
        )
        end_time = datetime.datetime.now()

    if "Workspaces" in data:
        workspaces = data["Workspaces"]
        if not isinstance(workspaces, list):
            logger.error("json entry 'Workspaces' must be a list")
            return (False, None)
    else:
        workspaces = None

    if "FallbackUserMail" in data:
        fallback_email = data["FallbackUserMail"]
    else:
        fallback_email = None

    return (
        True,
        [
            c_keys,
            c_admin,
            toggl_key,
            start_time,
            end_time,
            workspaces,
            fallback_email,
        ],
    )


def get_workspaces(clue, workspaces):
    """
    Imports all workspaces if none were provided.
    Returns list of workspace names
    """
    if workspaces is None:
        logger.info("no workspaces specified, importing all toggl workspaces...")
        workspaces = clue.getTogglWorkspaces()
        logger.info("The following workspaces will be imported: %s", str(workspaces))

    return workspaces


def process_phase(idx, name, skip, func):
    """
    Process a single phase in the import process
    """
    total = 7
    logger.info("-------------------------------------------------------------")
    logger.info("Phase %d of %d: %s", idx, total, name)
    logger.info("-------------------------------------------------------------")

    if not skip:
        entry_cnt, ok_cnt, skip_cnt, err_cnt = func()
    else:
        entry_cnt, ok_cnt, skip_cnt, err_cnt = (0, 0, 0, 0)
        logger.info("... skipping phase %d", idx)

    logger.info("-------------------------------------------------------------")
    logger.info(
        "Phase %d of %d (%s) completed (entries=%d, ok=%d, skips=%d, err=%d)",
        idx,
        total,
        name,
        entry_cnt,
        ok_cnt,
        skip_cnt,
        err_cnt,
    )


def import_workspace(workspace, clue, start_time, end_time, args):
    """
    Imports a workspace in 7 steps
    """

    process_phase(
        1,
        "Import clients",
        args.skipClients,
        lambda: clue.syncClients(workspace),
    )

    process_phase(2, "Import tags", args.skipTags, lambda: clue.syncTags(workspace))

    process_phase(
        3, "Import groups", args.skipGroups, lambda: clue.syncGroups(workspace)
    )

    process_phase(
        4, "Import projects", args.skipProjects, lambda: clue.syncProjects(workspace)
    )

    process_phase(5, "Import tasks", args.skipTasks, lambda: clue.syncTasks(workspace))

    time_interval_desc = "Import time entries from %s until %s" % (
        str(start_time),
        str(end_time),
    )

    process_phase(
        6,
        time_interval_desc,
        args.skipEntries,
        lambda: clue.syncEntries(workspace, start_time, until=end_time),
    )

    process_phase(
        7,
        "Archive projects",
        not args.doArchive,
        lambda: clue.syncProjectsArchive(workspace),
    )

    logger.info("Finished importing workspace '%s'", workspace)


def delete_entries(clue, workspaces, users):
    """
    Deletes entries for specified users
    """
    question = "All entries for users: %s in workspaces %s will be deleted.\n"
    question %= (str(users), workspaces)
    question += "This cannot be undone, do you want to proceed?"

    if not query_yes_no(question, default="no"):
        return

    for workspace in workspaces:
        logger.info("Deleting all entries in workspace %s", workspace)
        for user in users:
            clue.clockify.deleteEntriesOfUser(user, workspace)


def wipe_workspace(clue, workspaces):
    """
    Deletes all specified workspaces, including clients/projects
    """
    question = "This will wipe your all of the following clockify workspaces:\n"
    question += "\n".join(workspaces)
    question += "Are you sure?"

    if not query_yes_no(question, default="no"):
        return

    for workspace in workspaces:
        logger.info("Deleting workspace %s", workspace)
        clue.clockify.wipeOutWorkspace(workspace)


def migrate(args):
    """
    Migrates toggl to clockify in 7 stages.
    Alternatively wipes the entire workspace if --wipeAll is used.
    """

    success, vals = load_config()
    if not success:
        return

    # Unpack config into variables
    (
        c_keys,
        c_admin,
        toggl_key,
        start_time,
        end_time,
        workspaces,
        fallback_email,
    ) = vals

    clue = Clue(c_keys, c_admin, toggl_key, fallback_email)

    workspaces = get_workspaces(clue, workspaces)

    # Option to delete specified user's entries and exit
    if args.deleteEntries is not None:
        delete_entries(clue, workspaces, args.deleteEntries)
        return

    # Option to wipe all entries and exit
    if args.wipeAll:
        wipe_workspace(clue, workspaces)
        return

    num_ws = len(workspaces)
    for idx, workspace in enumerate(workspaces):
        logger.info("-------------------------------------------------------------")
        logger.info(
            "Starting to import workspace '%s' (%d of %d)", workspace, idx + 1, num_ws
        )
        logger.info("-------------------------------------------------------------")
        import_workspace(workspace, clue, start_time, end_time, args)
