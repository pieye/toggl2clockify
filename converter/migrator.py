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
from converter.phase_status import PhaseStatus


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

        self._workspace = None
        self._skip_inv_toggl_users = False

    def sync_tags(self, workspace):
        """
        Synchronize tags from toggl to clockify
        """
        tags = self.toggl.get_tags(workspace)
        status = PhaseStatus()
        status.num_entries = len(tags)

        for tag in tags:
            self.logger.info(
                "adding tag %s (%d of %d tags)",
                tag["name"],
                status.num_processed + 1,
                status.num_entries,
            )

            retval = self.clockify.add_tag(tag["name"], workspace)
            if retval == RetVal.EXISTS:
                self.logger.info("tag %s already exists, skip...", tag["name"])
                status.add_skip()
            elif retval == RetVal.OK:
                status.add_ok()
            else:
                status.add_err()

        return status.get_result()

    def sync_groups(self, workspace):
        """
        Synchronize groups from toggl to clockify
        """
        groups = self.toggl.get_groups(workspace)
        groups = groups or []  # ensure empty list

        status = PhaseStatus()
        status.num_entries = len(groups)

        for group in groups:
            self.logger.info(
                "adding group %s (%d of %d groups)",
                group["name"],
                status.num_processed + 1,
                status.num_entries,
            )

            retval = self.clockify.add_usergroup(group["name"], workspace)
            if retval == RetVal.EXISTS:
                self.logger.info("User Group %s already exists, skip...", group["name"])
                status.add_skip()
            elif retval == RetVal.OK:
                status.add_ok()
            else:
                status.add_err()

        return status.get_result()

    def sync_clients(self, workspace):
        """
        Synchronize clients from toggl to clockify
        """
        t_clients = self.toggl.get_clients(workspace)
        c_clients = self.clockify.get_clients(workspace)
        self.logger.info("Number of total clients in Toggl: %d", len(t_clients))
        t_clients = self.cull_same_name(t_clients, c_clients)

        status = PhaseStatus()
        status.num_entries = len(t_clients)

        for client in t_clients:
            self.logger.info(
                "Adding client %s (%d of %d)",
                client["name"],
                status.num_processed + 1,
                status.num_entries,
            )

            retval = self.clockify.add_client(client["name"], workspace)
            if retval == RetVal.EXISTS:
                self.logger.info("client %s already exists, skip...", client["name"])
                status.add_skip()
            elif retval == RetVal.OK:
                status.add_ok()
            else:
                status.add_err()

        return status.get_result()

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
        time_s = time_in_seconds
        if time_s > 0:
            hours = time_s // (3600)
            concat_h = hours > 0
            time_s = time_s % (3600)
            minutes = time_s // (60)
            concat_m = (minutes > 0) or (concat_h)
            time_s = time_s % (60)
            seconds = time_s
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
        tasks = tasks or []  # ensure empty list
        workspace_id = self.clockify.get_workspace_id(workspace)

        status = PhaseStatus()
        status.num_entries = len(tasks)

        self.logger.info("Number of Toggl projects: %s", len(self.toggl.projects))
        self.logger.info(
            "Number of Clockify projects: %s", len(self.clockify.projects.data)
        )

        for task in tasks:
            self.logger.info(
                "Adding task %s (%d of %d tasks)...",
                task["name"],
                status.num_processed + 1,
                status.num_entries,
            )

            proj_id = self.match_project(task["pid"], workspace)
            time_est = self.get_estimate(task["estimated_seconds"])

            # Add the task to Clockify:
            retval = self.clockify.add_task(
                workspace_id, task["name"], proj_id, time_est
            )

            if retval == RetVal.EXISTS:
                self.logger.info("task %s already exists, skip...", task["name"])
                status.add_skip()
            elif retval == RetVal.OK:
                status.add_ok()
            else:
                status.add_err()

        return status.get_result()

    def cull_same_name(self, toggl_items, clock_items):
        """
        Removes projects in toggl_projs/clients
        that are already on clock_projs/clients
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
            else:
                self.logger.info("Toggl/Clockify projects already synced")
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

        status = PhaseStatus()
        status.num_entries = len(toggl_projs)

        for t_proj in toggl_projs:
            c_proj = Project(t_proj)

            # Convert from toggl_ids to strings
            c_memberships = MemberShips(self.clockify)
            err = c_proj.ingest(
                workspace, self.toggl, tgroupid_to_groupname, c_memberships
            )

            self.logger.info(
                "Adding project %s|%s (%d of %d projects)",
                str(c_proj.name),
                str(c_proj.client),
                status.num_processed + 1,
                status.num_entries,
            )

            if err:
                status.add_err()
                continue

            retval = self.clockify.add_project(c_proj)

            if retval == RetVal.OK and not c_proj.groups:
                self.logger.info(" ...ok, done.")
                status.add_ok()
            elif retval == RetVal.OK and c_proj.groups:
                self.logger.info(" ...ok, processing User/Group assignments:")
                self.clockify.add_groups_to_project(c_proj)
                self.logger.info(" ...ok, done.")
                status.add_ok()
            elif retval == RetVal.EXISTS:
                self.logger.info("... project %s exists, skip...", c_proj.name)
                status.add_skip()
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
                status.add_err()

        return status.get_result()

    def sync_projects_archive(self, workspace):
        """
        Archives projects in clockify that are archived in toggl
        """
        projects = self.toggl.get_projects(workspace)

        status = PhaseStatus()
        status.num_entries = len(projects)

        for project in projects:
            name = project["name"]
            client_name = None
            if "cid" in project:
                client_name = self.toggl.get_client_name(
                    project["cid"], workspace, null_ok=True
                )

            full_proj_name = name + "|" + str(client_name)
            if not project["active"]:
                self.logger.info(
                    "project %s is not active, trying to archive (%d of %d)",
                    full_proj_name,
                    status.num_processed,
                    status.num_entries,
                )

                c_prj_id = self.clockify.get_project_id(name, client_name, workspace)
                c_prj = self.clockify.get_project(c_prj_id, workspace)
                retval = self.clockify.archive_project(c_prj)
                if retval == RetVal.OK:
                    self.logger.info("...ok")
                    status.add_ok()
                else:
                    status.add_err()
            else:
                self.logger.info(
                    "project %s is still active, skipping (%d of %d)",
                    full_proj_name,
                    status.num_processed,
                    status.num_entries,
                )
                status.add_skip()

        return status.get_result()

    def verify_email(self, toggl_uid, toggl_username):
        """
        Verifies and returns the email associated with a toggl User ID
        """

        # direct match
        t_email = self.toggl.get_user_email(toggl_uid, self._workspace)
        if t_email is not None:
            c_uid = self.clockify.get_userid_by_email(t_email, self._workspace)
            if c_uid is not None:
                return t_email

        # attempt to match user via username
        c_id = self.clockify.get_userid_from_name(toggl_username, self._workspace)
        if c_id is not None:
            c_email = self.clockify.get_email_by_id(c_id, self._workspace)
            if c_email is not None:
                return c_email

        # if this flag is set, just return None immediately
        if self._skip_inv_toggl_users:
            return None

        # assign task to the fallback email address.
        if self.clockify.fallback_email is not None:
            return self.clockify.fallback_email

        raise RuntimeError("No email found for %s" % toggl_username)

    def on_new_reports(self, entries, total_count, entry_status):
        """
        Queues entries into format suitable for clockify
        Then asks clockify to add the entries
        """

        entry_tasks = []
        entry_status.num_entries = total_count
        for t_entry in entries:
            c_entry = Entry(t_entry)

            self.logger.info(
                "Queuing entry %s, project: %s (%d of %d)",
                c_entry.description,
                str(c_entry.project_name) + "|" + str(c_entry.client_name),
                entry_status.num_queued + 1,
                entry_status.num_entries,
            )

            email = self.verify_email(t_entry["uid"], t_entry["user"])

            if email is None:
                entry_status.add_skip()
                continue

            c_entry.email = email
            c_entry.workspace = self._workspace
            c_entry.timezone = "Z"

            entry_tasks.append(c_entry)
            entry_status.num_queued += 1

        # do the actual work
        results = self.clockify.add_entries_threaded(entry_tasks)

        for retval, _ in results:
            if retval == RetVal.ERR:
                entry_status.add_err()
            elif retval == RetVal.EXISTS:
                entry_status.add_skip()
            else:
                entry_status.add_ok()

    def sync_entries(self, workspace, since, skip_inv_toggl_users=False, until=None):
        """
        Synchronize time entries from toggl to clockify
        """
        if until is None:
            until = datetime.datetime.now()

        phase_status = PhaseStatus()
        self._workspace = workspace
        self._skip_inv_toggl_users = skip_inv_toggl_users

        callback = lambda entries, total: self.on_new_reports(
            entries, total, phase_status
        )
        since_until = (since, until)
        self.toggl.get_reports(workspace, since_until, callback)

        return phase_status.get_result()

    def get_toggl_workspaces(self):
        """
        Returns list of workspaces in toggl.
        """
        workspaces = []
        for workspace in self.toggl.get_workspaces():
            workspaces.append(workspace["name"])
        return workspaces
