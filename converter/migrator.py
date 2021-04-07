#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Main logic for linking clockify and toggl
"""

__author__ = "Markus Proeller"
__copyright__ = "Copyright 2019, pieye GmbH (www.pieye.org)"
__maintainer__ = "Markus Proeller"
__email__ = "markus.proeller@pieye.org"


import datetime
import logging
import sys

import converter.toggl_api as toggl_api
import converter.clockify.api as clockify_api
from converter.clockify.membership import MemberShips
from converter.clockify.retval import RetVal
from converter.clockify.entry import Entry
from converter.clockify.project import Project


class Clue:
    """
    Clockify to toggl translation api.
    """

    def __init__(self, clockify_key, clockify_admin, toggl_key, fallback_email):
        self.logger = logging.getLogger("toggl2clockify")

        self.logger.info("testing toggl API key %s", toggl_key)
        try:
            self.toggl = toggl_api.TogglAPI(toggl_key)
            self.logger.info("...ok, togglKey resolved to email %s", self.toggl.email)
        except Exception as error:
            self.logger.error(
                "something went wrong with your toggl key, msg=%s", str(error)
            )
            raise

        self.clockify = clockify_api.ClockifyAPI(
            clockify_key, clockify_admin, fallback_email
        )

        self._num_skip = 0
        self._num_ok = 0
        self._num_err = 0
        self._num_entries = 0
        self._workspace = None
        self._skip_inv_toggl_users = False

    def sync_tags(self, workspace):
        """
        Synchronize tags from toggl to clockify
        """
        tags = self.toggl.get_tags(workspace)
        num_tags = len(tags)
        num_ok = 0
        num_skips = 0
        num_err = 0
        idx = 0
        for tag in tags:
            self.logger.info(
                "adding tag %s (%d of %d tags)", tag["name"], idx + 1, num_tags
            )

            retval = self.clockify.add_tag(tag["name"], workspace)
            if retval == RetVal.EXISTS:
                self.logger.info("tag %s already exists, skip...", tag["name"])
                num_skips += 1
            elif retval == RetVal.OK:
                num_ok += 1
            else:
                num_err += 1
            idx += 1

        return num_tags, num_ok, num_skips, num_err

    def sync_groups(self, workspace):
        """
        Synchronize groups from toggl to clockify
        """
        groups = self.toggl.get_groups(workspace)
        if groups is None:
            groups = []

        num_groups = len(groups)
        num_ok = 0
        num_skips = 0
        num_err = 0
        idx = 0
        for group in groups:
            self.logger.info(
                "adding group %s (%d of %d groups)", group["name"], idx + 1, num_groups
            )

            retval = self.clockify.add_usergroup(group["name"], workspace)
            if retval == RetVal.EXISTS:
                self.logger.info("User Group %s already exists, skip...", group["name"])
                num_skips += 1
            else:
                num_err += 1
            idx += 1

        return num_groups, num_ok, num_skips, num_err

    def sync_clients(self, workspace):
        """
        Synchronize clients from toggl to clockify
        """
        t_clients = self.toggl.get_clients(workspace)
        c_clients = self.clockify.get_clients(workspace)
        self.logger.info("Number of total clients in Toggl: %d", len(t_clients))
        t_clients = self.cull_same_name(t_clients, c_clients)

        num_clients = len(t_clients)
        num_ok = 0
        num_skips = 0
        num_err = 0

        for idx, client in enumerate(t_clients):
            self.logger.info(
                "Adding client %s (%d of %d)",
                client["name"],
                idx + 1,
                num_clients,
            )

            retval = self.clockify.add_client(client["name"], workspace)
            if retval == RetVal.EXISTS:
                self.logger.info("client %s already exists, skip...", client["name"])
                num_skips += 1
            elif retval == RetVal.OK:
                num_ok += 1
            else:
                num_err += 1
            idx += 1

        return num_clients, num_ok, num_skips, num_err

    def match_project(self, toggl_project_id, workspace):
        """
        given a toggl_project id, returns clockify project_id
        """

        result = None
        proj_name = None
        proj_client = None

        toggl_projs = self.toggl.projects
        clock_projs = self.clockify.projects.data

        # grab project
        for t_proj in toggl_projs:
            if toggl_project_id == t_proj["id"]:
                proj_name = t_proj["name"]
                proj_client = t_proj["cid"] if "cid" in t_proj else None
                break

        # find out client name
        proj_client = self.toggl.get_client_name(proj_client, workspace, True)

        # match in clockify
        for c_proj in clock_projs:
            if c_proj["name"] == proj_name and c_proj["clientName"] == proj_client:
                return c_proj["id"]

        return result

    def get_estimate(self, time_in_seconds):
        """
        Convert from toggl duration to clockify "estimate", (e.g. PT1H30M15S)
        """

        time = time_in_seconds
        if time > 0:
            hours = time // (3600)
            concat_h = hours > 0
            time = time % (3600)
            minutes = time // (60)
            concat_m = (minutes > 0) or (concat_h)
            time = time % (60)
            seconds = time
            time_est = (
                "PT"
                + ["", "%dH" % hours][concat_h]
                + ["", "%dM" % minutes][concat_m]
                + "%dS" % seconds
            )
            self.logger.info("Estimated time: %s", time_est)
        else:
            time_est = None

        return time_est

    def sync_tasks(self, workspace):
        """
        Synchronize tasks from toggl to clockify
        Does *not* synchronize user assignments
        """
        tasks = self.toggl.get_tasks(workspace)
        if tasks is None:
            tasks = []
        workspace_id = self.clockify.get_workspace_id(workspace)

        num_tasks = len(tasks)
        num_ok = 0
        num_skips = 0
        num_err = 0

        self.logger.info("Number of Toggl projects found: %s", len(self.toggl.projects))
        self.logger.info(
            "Number of Clockify projects found: %s", len(self.clockify.projects.data)
        )

        for idx, task in enumerate(tasks):
            self.logger.info(
                "Adding tasks %s (%d of %d tasks)...", task["name"], idx + 1, num_tasks
            )

            proj_id = self.match_project(task["pid"], workspace)

            time_est = self.get_estimate(task["estimated_seconds"])

            # Add the task to Clockify:
            retval = self.clockify.add_task(
                workspace_id, task["name"], proj_id, time_est
            )

            if retval == RetVal.EXISTS:
                self.logger.info("task %s already exists, skip...", task["name"])
                num_skips += 1
            elif retval == RetVal.OK:
                num_ok += 1
                self.logger.info(" ... done.")
            else:
                num_err += 1

        return num_tasks, num_ok, num_skips, num_err

    def cull_same_name(self, toggl_items, clock_items):
        """
        Removes projects in toggl_projs that are already on clock_projs
        """
        clock_names = {item["name"] for item in clock_items}

        if len(clock_items) > 0:
            new_toggl_items = [
                item for item in toggl_items if item["name"] not in clock_names
            ]
            toggl_items = new_toggl_items
            if len(toggl_items) > 0:
                self.logger.info("Clockify already has items. Adding:")
                printables = "\n".join([item["name"] for item in toggl_items])
                self.logger.info(printables)
        return toggl_items

    def _get_new_toggl_projects(self, workspace):
        """
        Gets projects in toggl that aren't in clockify
        """
        toggl_projs = self.toggl.get_projects(workspace)
        self.logger.info("Number of total Projects in Toggl: %d", len(toggl_projs))
        clock_projs = self.clockify.get_projects(workspace)

        return self.cull_same_name(toggl_projs, clock_projs)

    def sync_projects(self, workspace):
        """
        Synchronize projects from toggl to clockify
        """
        toggl_projs = self._get_new_toggl_projects(workspace)
        # Load all Workspace Groups in simple array
        t_groups = self.toggl.get_groups(workspace)
        # map from toggl group_id to group_name
        tgroupid_to_groupname = {group["id"]: group["name"] for group in t_groups}

        num_prjs = len(toggl_projs)
        num_ok = 0
        num_skips = 0
        num_err = 0

        for idx, t_proj in enumerate(toggl_projs):
            c_proj = Project(t_proj)

            # Convert from toggl_ids to strings
            c_memberships = MemberShips(self.clockify)
            err = c_proj.ingest(
                workspace, self.toggl, t_proj, tgroupid_to_groupname, c_memberships
            )

            self.logger.info(
                "Adding project %s|%s (%d of %d projects)",
                str(c_proj.name),
                str(c_proj.client),
                idx + 1,
                num_prjs,
            )

            if err:
                num_err += 1
                continue

            retval = self.clockify.add_project(c_proj)

            if retval == RetVal.OK and not c_proj.groups:
                self.logger.info(" ...ok, done.")
                num_ok += 1
            if retval == RetVal.OK and c_proj.groups:
                self.logger.info(" ...ok, processing User/Group assignments:")
                self.clockify.add_groups_to_project(c_proj)
                self.logger.info(" ...ok, done.")
                num_ok += 1
            elif retval == RetVal.EXISTS:
                self.logger.info("... project %s exists, skip...", c_proj.name)
                num_skips += 1
            elif retval == RetVal.FORBIDDEN:
                self.logger.error(
                    " Could not add project %s. %s was project admin in toggl, \
                      but seems to not be admin in clockify. Check your workspace \
                      settings and grant admin rights to %s.",
                    c_proj.name,
                    c_proj.manager,
                    c_proj.manager,
                )
                sys.exit(1)
            else:
                num_err += 1

        return num_prjs, num_ok, num_skips, num_err

    def sync_projects_archive(self, workspace):
        """
        Archives projects in clockify that are archived in toggl
        """
        projects = self.toggl.get_projects(workspace)

        idx = 0
        num_prjs = len(projects)
        num_ok = 0
        num_skips = 0
        num_err = 0
        for project in projects:
            name = project["name"]
            client_name = None
            if "cid" in project:
                client_name = self.toggl.get_client_name(
                    project["cid"], workspace, null_ok=True
                )

            if not project["active"]:
                # get clientName

                self.logger.info(
                    "project %s is not active, trying to archive (%d of %d)",
                    name + "|" + str(client_name),
                    idx,
                    num_prjs,
                )

                c_prj_id = self.clockify.get_project_id(name, client_name, workspace)
                c_prj = self.clockify.get_project(c_prj_id, workspace)
                retval = self.clockify.archive_project(c_prj)
                if retval == RetVal.OK:
                    self.logger.info("...ok")
                    num_ok += 1
                else:
                    num_err += 1
            else:
                self.logger.info(
                    "project %s is still active, skipping (%d of %d)",
                    name + "|" + str(client_name),
                    idx,
                    num_prjs,
                )
                num_skips += 1

            idx += 1

        return num_prjs, num_ok, num_skips, num_err

    def verify_email(self, toggl_uid, toggl_username, description):
        """
        Verifies and returns the email associated with a toggl User ID
        """
        try:
            # get email from toggl
            email = self.toggl.get_user_email(toggl_uid, self._workspace)
            # verify email actually exists in workspace. This will raise an
            # exception if it doesnt exist.
            self.clockify.get_userid_by_email(email, self._workspace)
        except RuntimeError:
            try:
                # attempt to match user via username
                c_id = self.clockify.get_userid_from_name(
                    toggl_username, self._workspace
                )
                self.logger.info(
                    "user '%s' found in clockify workspace as ID=%s",
                    toggl_username,
                    c_id,
                )
                email = self.clockify.get_email_by_id(c_id, self._workspace)
                self.logger.info(
                    "user ID %s (name='%s') not in toggl workspace, \
                     but found a match in clockify workspace %s...",
                    toggl_uid,
                    toggl_username,
                    email,
                )
            except RuntimeError:
                # skip user entirely
                if self._skip_inv_toggl_users:
                    self.logger.info(
                        "user ID %s (name='%s') not in toggl workspace, skipping entry %s...",
                        toggl_uid,
                        toggl_username,
                        description,
                    )
                    return None
                # assign task to the fallback email address.
                if self.clockify.fallback_email is not None:
                    email = self.clockify.fallback_email
                    self.logger.info(
                        "user '%s' not found in clockify workspace, using fallback user '%s'",
                        toggl_uid,
                        email,
                    )
                else:
                    raise

        return email

    def on_new_reports(self, entries, total_count):
        """
        Queues entries into format suitable for clockify
        Then asks clockify to add the entries
        """

        entry_tasks = []

        for idx, t_entry in enumerate(entries):
            c_entry = Entry(t_entry)

            self.logger.info(
                "Queuing entry %s, project: %s (%d of %d)",
                c_entry.description,
                str(c_entry.project_name) + "|" + str(c_entry.client_name),
                idx,
                total_count,
            )

            email = self.verify_email(
                t_entry["uid"], t_entry["user"], t_entry["description"]
            )
            if email is None:
                self._num_skip += 1
                continue

            c_entry.email = email
            c_entry.workspace = self._workspace
            c_entry.timezone = "Z"

            entry_tasks.append(c_entry)

        results = self.clockify.add_entries_threaded(entry_tasks)

        for retval, _ in results:
            if retval == RetVal.ERR:
                self._num_err += 1
            elif retval == RetVal.EXISTS:
                self._num_skip += 1
            else:
                self._num_ok += 1
        self._num_entries += len(entries)

    def sync_entries(self, workspace, since, skip_inv_toggl_users=False, until=None):
        """
        Synchronize time entries from toggl to clockify
        """
        if until is None:
            until = datetime.datetime.now()

        self._num_skip = 0
        self._num_ok = 0
        self._num_err = 0
        self._num_entries = 0
        self._workspace = workspace
        self._skip_inv_toggl_users = skip_inv_toggl_users

        since_until = (since, until)
        self.toggl.get_reports(workspace, since_until, self.on_new_reports)

        return self._num_entries, self._num_ok, self._num_skip, self._num_err

    def get_toggl_workspaces(self):
        """
        Returns list of workspaces in toggl.
        """
        workspaces = []
        for workspace in self.toggl.get_workspaces():
            workspaces.append(workspace["name"])
        return workspaces
