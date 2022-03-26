#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Toggl api class, allows asking toggl for information
"""

__author__ = "Markus Proeller"
__copyright__ = "Copyright 2019, pieye GmbH (www.pieye.org)"
__maintainer__ = "Markus Proeller"
__email__ = "markus.proeller@pieye.org"

import base64
import time
import datetime
import logging
import json
import requests


def dump_json(file_name, data):
    """
    dumps a dictionary into file_name
    """
    with open(file_name, "w") as file:
        file.write(json.dumps(data, indent=2))


class TogglAPI:
    """
    Toggl API Class, allows requests for entries/projects/clients etc.
    """

    def __init__(self, api_token):
        self.logger = logging.getLogger("toggl2clockify")
        self.api_token = api_token
        self.url = "https://api.track.toggl.com/api/v8"

        response = self._request(self.url + "/me")
        if response.status_code != 200:
            raise RuntimeError("Login failed. Check your API key")

        response = response.json()
        self.email = response["data"]["email"]
        self._get_workspaces()

        self.projects = []
        self.clients = []
        self.users = []
        self.tags = []
        self.groups = []
        self.tasks = []

        self._resync_projects = True
        self._resync_clients = True
        self._resync_users = True
        self._resync_tags = True
        self._resync_groups = True
        self._resync_tasks = True

    def _request(self, url, params=None):
        """
        Forwards a request, injecting api token
        """
        string = self.api_token + ":api_token"
        headers = {
            "Authorization": "Basic "
            + base64.b64encode(string.encode("ascii")).decode("utf-8")
        }
        response = requests.get(url, headers=headers, params=params)
        while response.status_code == 429:
            time.sleep(1.1)  # Safe limit is 1/second
            response = requests.get(url, headers=headers, params=params)

        return response

    def _get_workspaces(self):
        """
        setup workspace_id map
        """
        response = self._request(self.url + "/me")
        response = response.json()
        workspaces = response["data"]["workspaces"]

        self.workspace_ids_names = [
            {"name": item["name"], "id": item["id"]}
            for item in workspaces
            if item["admin"]
        ]

    def get_workspaces(self):
        """
        returns mapping for workspace_ids <-> workspace_names
        """
        return self.workspace_ids_names

    def get_workspace_id(self, workspace_name):
        """
        converts from workspace_name to workspace_id
        """
        ws_id = None
        workspaces = self.get_workspaces()
        for workspace in workspaces:
            if workspace["name"] == workspace_name:
                ws_id = workspace["id"]
        if ws_id is None:
            raise RuntimeError(
                "Workspace %s not found. Available workspaces: %s"
                % (workspace_name, workspaces)
            )
        return ws_id

    def get_tags(self, workspace_name):
        """
        lazily reloads tags into self.tags and returns it.
        """
        if self._resync_tags:
            self.tags = []
            ws_id = self.get_workspace_id(workspace_name)
            url = self.url + "/workspaces/%d/tags" % ws_id
            req = self._request(url)
            if req.ok:
                self.tags = req.json()
                if self.tags is None:
                    self.tags = []
            else:
                raise RuntimeError(
                    "Error getting toggl workspace tags, status code=%d, msg=%s"
                    % (req.status_code, req.reason)
                )
            self._resync_tags = False

        return self.tags

    def get_groups(self, workspace_name):
        """
        lazily reloads groups into self.groups and returns it.
        """
        if self._resync_groups:
            self.groups = []
            ws_id = self.get_workspace_id(workspace_name)
            url = self.url + "/workspaces/%d/groups" % ws_id
            req = self._request(url)
            if req.ok:
                # ensure empty list rather than None
                self.groups = req.json() or []
            else:
                raise RuntimeError(
                    "Error getting toggl workspace groups, status code=%d, msg=%s"
                    % (req.status_code, req.reason)
                )
            self._resync_groups = False

        return self.groups

    def get_users(self, workspace_name):
        """
        lazily reloads users into self.users and returns it.
        """
        if self._resync_users:
            ws_id = self.get_workspace_id(workspace_name)
            url = self.url + "/workspaces/%d/users" % ws_id
            req = self._request(url)
            if req.ok:
                self.users = req.json()
                dump_json("toggl_users.json", self.users)
            else:
                raise RuntimeError(
                    "Error getting toggl workspace users, status code=%d, msg=%s"
                    % (req.status_code, req.reason)
                )
            self._resync_users = False

        return self.users

    def get_clients(self, workspace_name):
        """
        lazily reloads clients into self.clients and returns it.
        """
        if self._resync_clients:
            ws_id = self.get_workspace_id(workspace_name)
            url = self.url + "/workspaces/%d/clients" % ws_id
            req = self._request(url)
            self.clients = req.json()
            if self.clients is None:
                self.clients = []
            self._resync_clients = False

            dump_json("toggl_clients.json", self.clients)

        return self.clients

    def get_projects(self, workspace_name):
        """
        lazily reloads projects into self.projects and returns it.
        """
        if self._resync_projects:
            ws_id = self.get_workspace_id(workspace_name)
            url = self.url + "/workspaces/%d/projects" % ws_id
            params = {"active": "both"}
            req = self._request(url, params=params)
            self.projects = req.json()
            self._resync_projects = False

            dump_json("toggl_projects.json", self.projects)

        return self.projects

    def get_tasks(self, workspace_name):
        """
        lazily reloads tasks into self.tasks and returns it.
        """
        if self._resync_tasks:
            ws_id = self.get_workspace_id(workspace_name)
            url = self.url + "/workspaces/%d/tasks" % ws_id
            req = self._request(url)
            self.tasks = req.json()
            self._resync_tasks = False

            dump_json("toggl_tasks.json", self.tasks)

        return self.tasks

    def get_reports(self, workspace_name, since_until, callback, time_zone="CET"):
        """
        Gets entries from *since* to *until*, calling *cb* so that you can
        write the results to clockify.
        """
        since, until = since_until
        end = False
        next_start = since
        while True:
            cur_stop = next_start + datetime.timedelta(days=300)
            if cur_stop > until:
                cur_stop = until
                end = True

            self.logger.info(
                "fetching entries from %s to %s",
                next_start.isoformat() + time_zone,
                cur_stop.isoformat() + time_zone,
            )

            self._get_reports(
                workspace_name,
                next_start.isoformat() + time_zone,
                cur_stop.isoformat() + time_zone,
                callback,
            )
            if end:
                break

            next_start = cur_stop

    def _get_reports(self, workspace_name, since, until, callback):
        """
        Stream entries for a user from the API
        """
        ws_id = self.get_workspace_id(workspace_name)
        page = 1

        entry_cnt = 0
        while True:
            params = {
                "user_agent": self.email,
                "workspace_id": ws_id,
                "since": since,
                "until": until,
                "page": page,
            }

            report_url = "https://api.track.toggl.com/reports/api/v2/details"
            response = self._request(report_url, params=params)
            if response.status_code == 400:
                break

            page += 1

            jsonresp = response.json()
            data = jsonresp["data"]
            entry_cnt += len(data)
            total_cnt = jsonresp["total_count"]
            if len(data) == 0:
                break

            callback(data, total_cnt)

            self.logger.info("Received %d out of %d entries", entry_cnt, total_cnt)

    def get_project_id(self, project_name, workspace_name):
        """
        Returns projectid from project_name and workspace_name
        """
        project_id = None
        projects = self.get_projects(workspace_name)
        for project in projects:
            if project["name"] == project_name:
                project_id = project["id"]
        if project_id is None:
            raise RuntimeError(
                "project %s not found in workspace %s" % (project_name, workspace_name)
            )
        return project_id

    def get_project_users(self, project_name, workspace_name):
        """
        Returns project's users
        """
        project_id = self.get_project_id(project_name, workspace_name)
        url = self.url + "/projects/%d/project_users" % project_id
        response = self._request(url)
        return response.json()

    def get_project_groups(self, project_name, workspace_name):
        """
        Returns project's groups
        """
        project_id = self.get_project_id(project_name, workspace_name)
        url = self.url + "/projects/%d/project_groups" % project_id
        response = self._request(url)
        return response.json()

    def get_client_name(self, client_id, workspace, null_ok=False):
        """
        Returns clients name, given it's id
        """
        clients = self.get_clients(workspace)
        client_name = None
        for client in clients:
            if client["id"] == client_id:
                client_name = client["name"]

        if client_name is None:
            if null_ok:
                return ""

            raise RuntimeError(
                "clientID %d not found in workspace %s" % (client_id, workspace)
            )
        return client_name

    def get_username(self, user_id, workspace_name):
        """
        Returns username, given it's id
        """
        users = self.get_users(workspace_name)
        username = None
        for user in users:
            if user["id"] == user_id:
                username = user["fullname"]
        if username is None:
            raise RuntimeError(
                "userID %d not found in workspace %s" % (user_id, workspace_name)
            )
        return username

    def get_user_email(self, user_id, workspace_name):
        """
        Returns user's email, given its id
        """
        users = self.get_users(workspace_name)

        for user in users:
            if user["id"] == user_id:
                return user["email"]

        return None
