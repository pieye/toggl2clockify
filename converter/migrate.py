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
import sys

from converter.migrator import Clue
from converter.config import Config

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


def get_workspaces(clue, workspaces):
    """
    Imports all workspaces if none were provided.
    Returns list of workspace names
    """
    if workspaces is None:
        logger.info("no workspaces specified, importing all toggl workspaces...")
        workspaces = clue.get_toggl_workspaces()
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
    logger.info("-------------------------------------------------------------")


def import_workspace(workspace, clue, start_time, end_time, args):
    """
    Imports a workspace in 7 steps
    """

    time_interval_desc = "Import time entries from %s until %s" % (
        str(start_time),
        str(end_time),
    )
    # fmt: off
    process_phase(1, "Import clients", args.skipClients, lambda: clue.sync_clients(workspace))
    process_phase(2, "Import tags", args.skipTags, lambda: clue.sync_tags(workspace))
    process_phase(3, "Import groups", args.skipGroups, lambda: clue.sync_groups(workspace))
    process_phase(4, "Import projects", args.skipProjects, lambda: clue.sync_projects(workspace))
    process_phase(5, "Import tasks", args.skipTasks, lambda: clue.sync_tasks(workspace))
    process_phase(6, time_interval_desc, args.skipEntries,
                  lambda: clue.sync_entries(workspace, start_time, until=end_time))
    process_phase(7, "Archive projects", not args.doArchive,
                  lambda: clue.sync_projects_archive(workspace))
    # fmt: on
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
    question += "\n".join(workspaces) + "\n"
    question += "Are you sure?"

    if not query_yes_no(question, default="no"):
        return

    for workspace in workspaces:
        logger.info("Deleting workspace %s", workspace)
        clue.clockify.wipeout_workspace(workspace)


def migrate(args):
    """
    Migrates toggl to clockify in 7 stages.
    Alternatively wipes the entire workspace if --wipeAll is used.
    """

    config = Config()

    clue = Clue(
        config.clockify_keys,
        config.clockify_admin,
        config.toggl_key,
        config.fallback_email,
    )

    # Load workspaces if none were provided.
    workspaces = get_workspaces(clue, config.workspaces)

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
        import_workspace(workspace, clue, config.start_time, config.end_time, args)
