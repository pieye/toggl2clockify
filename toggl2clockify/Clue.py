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

import dateutil.parser
import pytz

import toggl2clockify.toggl_api as toggl_api
import toggl2clockify.clockify_api as clockify_api


def time_to_utc(time):
    """
    Converts time from its relevant timezone to UTC
    """
    time = dateutil.parser.parse(time)
    utc = time.astimezone(pytz.UTC).isoformat().split("+")[0]
    return dateutil.parser.parse(utc)


class Clue:
    """
    Clockify to toggl translation api.
    """

    def __init__(self, clockifyKey, clockifyAdmin, togglKey, fallbackUserMail):
        self.logger = logging.getLogger("toggl2clockify")

        self.logger.info("testing toggl API key %s", togglKey)
        try:
            self.toggl = toggl_api.TogglAPI(togglKey)
            self.logger.info("...ok, togglKey resolved to email %s", self.toggl.email)
        except Exception as error:
            self.logger.error(
                "something went wrong with your toggl key, msg=%s", str(error)
            )
            raise

        self.clockify = clockify_api.ClockifyAPI(
            clockifyKey, clockifyAdmin, fallbackUserMail
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

            retval = self.clockify.addTag(tag["name"], workspace)
            if retval == clockify_api.RetVal.EXISTS:
                self.logger.info("tag %s already exists, skip...", tag["name"])
                num_skips += 1
            elif retval == clockify_api.RetVal.OK:
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

            retval = self.clockify.addUserGroup(group["name"], workspace)
            if retval == clockify_api.RetVal.EXISTS:
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
        clients = self.toggl.get_clients(workspace)

        idx = 0
        num_clients = len(clients)
        num_ok = 0
        num_skips = 0
        num_err = 0

        for client in clients:
            self.logger.info(
                "adding client %s (%d of %d clients)",
                client["name"],
                idx + 1,
                num_clients,
            )

            retval = self.clockify.addClient(client["name"], workspace)
            if retval == clockify_api.RetVal.EXISTS:
                self.logger.info("client %s already exists, skip...", client["name"])
                num_skips += 1
            elif retval == clockify_api.RetVal.OK:
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
        clock_projs = self.clockify.projects

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
        workspace_id = self.clockify.getWorkspaceID(workspace)

        num_tasks = len(tasks)
        num_ok = 0
        num_skips = 0
        num_err = 0

        self.logger.info("Number of Toggl projects found: %s", len(self.toggl.projects))
        self.logger.info(
            "Number of Clockify projects found: %s", len(self.clockify.projects)
        )

        for idx, task in enumerate(tasks):
            self.logger.info(
                "Adding tasks %s (%d of %d tasks)...", task["name"], idx + 1, num_tasks
            )

            proj_id = self.match_project(task["pid"], workspace)

            time_est = self.get_estimate(task["estimated_seconds"])

            # Add the task to Clockify:
            retval = self.clockify.addTask(
                workspace_id, task["name"], proj_id, time_est
            )

            if retval == clockify_api.RetVal.EXISTS:
                self.logger.info("task %s already exists, skip...", task["name"])
                num_skips += 1
            elif retval == clockify_api.RetVal.OK:
                num_ok += 1
                self.logger.info(" ... done.")
            else:
                num_err += 1

        return num_tasks, num_ok, num_skips, num_err

    def sync_projects(self, workspace):
        """
        Synchronize projects from toggl to clockify
        """
        toggl_projs = self.toggl.get_projects(workspace)
        self.logger.info("Number of total Projects in Toggl: %d", len(toggl_projs))

        # getWorkspaceProjects() uses Clockify's Working API entry point,
        # which gets all Projects without iterating all users, much quicker
        clock_projs = self.clockify.getWorkspaceProjects(workspace)

        clock_proj_names = {cPrj["name"] for cPrj in clock_projs}

        # Check if it's the first run (cPrjs = 0)
        # Get only new projects on Toggl to update in Clockify
        if len(clock_projs) >= 1:
            updated_toggl_projs = [
                tPrj for tPrj in toggl_projs if tPrj["name"] not in clock_proj_names
            ]
            self.logger.info(
                "Found projects in Clockify, skipping matching ones in Toggl:"
            )
            for proj in updated_toggl_projs:
                self.logger.info("Found different Project: %s", proj["name"])
            toggl_projs = updated_toggl_projs

        self.logger.info("Number of new Projects in Toggl: %d", (len(toggl_projs)))
        self.logger.info(
            " Number of total Projects in Clockify: %d, begin sync:", (len(clock_projs))
        )

        workspace_id = self.clockify.getWorkspaceID(workspace)

        # Load all Workspace Groups in simple array
        ws_groups = self.toggl.get_groups(workspace)
        if ws_groups is None:
            ws_groups = []

        ws_group_ids = []
        for wgroup in ws_groups:
            ws_group_ids.append(wgroup["id"])

        idx = 0
        num_prjs = len(toggl_projs)
        num_ok = 0
        num_skips = 0
        num_err = 0

        for proj in toggl_projs:
            client_name = ""
            if "cid" in proj:
                client_name = self.toggl.get_client_name(
                    proj["cid"], workspace, null_ok=True
                )
            self.logger.info(
                "Adding project %s (%d of %d projects)",
                proj["name"] + "|" + client_name,
                idx + 1,
                num_prjs,
            )

            # Prepare Group assignment to Projects
            proj_groups = self.toggl.get_project_groups(proj["name"], workspace)
            # self.logger.info(" Groups assigned in Toggl: %s"%pgroups)

            if proj_groups is None:
                proj_groups = []
                ws_group_ids = []
            else:
                # Add group name to toggl Groups array
                for pgroup in proj_groups:
                    for wgroup in ws_groups:
                        if pgroup["group_id"] == wgroup["id"]:
                            pgroup["name"] = wgroup["name"]

            name = proj["name"]

            if name not in clock_proj_names:
                err = False

                is_public = not proj["is_private"]
                billable = proj["billable"]
                color = proj["hex_color"]
                members = self.toggl.get_project_users(proj["name"], workspace)
                if members is None:
                    members = []

                membership = clockify_api.MemberShip(self.clockify)
                for member in members:
                    try:
                        email = self.toggl.get_user_email(member["uid"], workspace)
                    except Exception as error:
                        self.logger.warning(
                            "user id %d not found in toggl workspace, msg=%s",
                            member["uid"],
                            str(error),
                        )
                        err = True
                        break

                    try:
                        manager = member["manager"]
                        membership.addMembership(
                            email,
                            proj["name"],
                            workspace,
                            membershipType="PROJECT",
                            membershipStatus="ACTIVE",
                            hourlyRate=None,
                            manager=manager,
                        )
                    except Exception as error:
                        self.logger.warning(
                            "error adding user %s to clockify project, msg=%s",
                            email,
                            str(error),
                        )
                        err = True
                        break

                if not err:

                    retval = self.clockify.addProject(
                        name,
                        client_name,
                        workspace,
                        is_public,
                        billable,
                        color,
                        memberships=membership,
                        manager=membership.getManagerUserMail(),
                    )
                    if (retval == clockify_api.RetVal.OK) and (proj_groups == []):
                        self.logger.info(" ...ok, done.")
                        num_ok += 1
                    if (retval == clockify_api.RetVal.OK) and (proj_groups != []):
                        self.logger.info(
                            " ...ok, now processing User Group assignments:"
                        )
                        proj_id = self.clockify.getProjectID(
                            name, client_name, workspace
                        )
                        self.clockify.addGroupsToProject(
                            workspace, workspace_id, proj_id, ws_group_ids, proj_groups
                        )
                        self.logger.info(" ...ok, done.")
                        num_ok += 1
                    elif retval == clockify_api.RetVal.EXISTS:
                        self.logger.info("... project %s already exists, skip...", name)
                        num_skips += 1
                    elif retval == clockify_api.RetVal.FORBIDDEN:
                        manager = membership.getManagerUserMail()
                        self.logger.error(
                            " Could not add project %s. %s was project admin in toggl, \
                              but seems to not be admin in clockify. Check your workspace \
                              settings and grant admin rights to %s.",
                            name,
                            manager,
                            manager,
                        )
                        sys.exit(1)
                    else:
                        num_err += 1
                else:
                    num_err += 1
            else:
                self.logger.info(" ...project %s already exists, skip...", name)

                # Add groups even if project exist.
                # if pgroups != []:
                #    self.clockify.addGroupsToProject(workspace, wsId, pId, wgroupIds, pgroups)

                num_skips += 1
            idx += 1

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

                c_prj_id = self.clockify.getProjectID(name, client_name, workspace)
                c_prj = self.clockify.getProject(c_prj_id)
                retval = self.clockify.archiveProject(c_prj)
                if retval == clockify_api.RetVal.OK:
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

    def verify_email(self, toggl_uid, toggl_username):
        """
        Verifies and returns the email associated with a toggl User ID
        """
        try:

            # get email from toggl
            email = self.toggl.get_user_email(toggl_uid, self._workspace)

            # verify email actually exists in workspace.
            self.clockify.getUserIDByMail(email, self._workspace)

        except:
            try:
                # attempt to match user via username
                c_id = self.clockify.getUserIDByName(toggl_username, self._workspace)
                self.logger.info(
                    "user '%s' found in clockify workspace as ID=%s",
                    toggl_username,
                    c_id,
                )
                email = self.clockify.getUserMailById(c_id, self._workspace)
                self.logger.info(
                    "user ID %s (name='%s') not in toggl workspace, \
                     but found a match in clockify workspace %s...",
                    toggl_uid,
                    toggl_username,
                    email,
                )
            except:
                # skip user entirely
                if self._skip_inv_toggl_users:
                    return None
                # assign task to the fallback email address.
                if self.clockify.fallbackUserMail is not None:
                    email = self.clockify.fallbackUserMail
                    self.logger.info(
                        "user '%s' not found in clockify workspace, using fallback user '%s'",
                        toggl_uid,
                        email,
                    )

                raise

        return email

    def on_new_reports(self, entries, total_count):
        """
        Queues entries into format suitable for clockify
        Then asks clockify to add the entries
        """

        entry_data = []

        for idx, entry in enumerate(entries):
            start = time_to_utc(entry["start"])
            if entry["end"] is not None:
                end = time_to_utc(entry["end"])
            else:
                end = None
            description = entry["description"]
            project_name = entry["project"]
            user_id = entry["uid"]
            billable = entry["is_billable"]
            tag_names = entry["tags"]
            username = entry["user"]
            task_name = entry["task"]
            client_name = entry["client"]

            self.logger.info(
                "Queuing entry %s, project: %s (%d of %d)",
                description,
                str(project_name) + "|" + str(client_name),
                idx,
                total_count,
            )

            email = self.verify_email(user_id, username)
            if email is None and self._skip_inv_toggl_users:
                self.logger.warning(
                    "user ID %s (name='%s') not in toggl workspace, skipping entry %s...",
                    user_id,
                    username,
                    description,
                )
                self._num_skip += 1
                continue

            entry_data.append(
                [
                    start,
                    description,
                    project_name,
                    client_name,
                    email,
                    self._workspace,
                    "Z",
                    end,
                    billable,
                    tag_names,
                    task_name,
                ]
            )

        results = self.clockify.addEntriesThreaded(entry_data)
        for retval, _ in results:
            if retval == clockify_api.RetVal.ERR:
                self._num_err += 1
            elif retval == clockify_api.RetVal.EXISTS:
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
