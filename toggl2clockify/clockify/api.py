#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""
Entrypoint for Clockify api
"""

__author__ = "Markus Proeller"
__copyright__ = "Copyright 2019, pieye GmbH (www.pieye.org)"
__maintainer__ = "Markus Proeller"
__email__ = "markus.proeller@pieye.org"


import time
from multiprocessing.pool import ThreadPool
import logging
import json

import requests

from toggl2clockify.clockify.retval import RetVal


def dump_json(file_name, data):
    """
    dumps a dictionary into file_name
    """
    with open(file_name, "w") as file:
        file.write(json.dumps(data, indent=2))


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


def match_client(project_data, client_name):
    """
    Given a project's json data, sees if the client name matches
    """
    if client_name is None:
        client_name = ""
    if "clientName" in project_data and project_data["clientName"] == client_name:
        return True
    return False


def get_projname_from_dict(project):
    """
    Safely returns the project's name from it's dictionary
    """
    if "name" in project:
        return project["name"]
    return None


def get_clientname_from_dict(project):
    """
    Safely returns the project's client's name from it's dictionary
    """
    if "clientName" in project:
        return project["clientName"]
    return None


class ClockifyAPI:
    """
    Entrypoint for Clockify's API
    https://clockify.me/developers-api
    """

    requests_per_second = 10.0  # Rate limit is 10/s
    # Add slight time buffer so we don't trigger limit
    time_per_request = 1.0 / (requests_per_second - 1)

    def __init__(self, api_tokens, admin_email="", fallback_email=None):
        self.logger = logging.getLogger("toggl2clockify")
        self.url = "https://clockify.me/api/v1"
        self.url_working = "https://api.clockify.me/api/v1"
        self._resync_clients = True
        self._resync_users = True
        self._resync_projects = True
        self._resync_tags = True
        self._resync_groups = True
        self._resync_tasks = True
        self._admin_email = admin_email
        self.fallback_email = fallback_email
        self.thread_pool = ThreadPool(
            int(self.requests_per_second)
        )  # only used for entry deletion

        self._api_users = []
        self.test_tokens(api_tokens, admin_email)
        self._loaded_user_email = None
        self._load_user(self._api_users[0]["email"])
        self.projects = []
        self.users = []
        self.usergroups = []
        self.tags = []
        self.clients = []
        self.project_tasks = []

        self._get_workspaces()

    def test_tokens(self, api_tokens, admin_email):
        """
        Test supplied api_tokens, and search for admin/fallback email
        """
        admin_found = False
        fallback_found = False
        for token in api_tokens:
            self.logger.info("testing clockify APIKey %s", token)

            self.api_token = token
            url = self.url + "/user"
            retval = self._request(url)
            if retval.status_code != 200:
                raise RuntimeError(
                    "error loading user (API token %s), status code %s"
                    % (token, str(retval.status_code))
                )

            retval = retval.json()
            user = {}
            user["name"] = retval["name"]
            user["token"] = token
            user["email"] = retval["email"]
            user["id"] = retval["id"]

            if retval["status"].upper() not in ["ACTIVE", "PENDING_EMAIL_VERIFICATION"]:
                raise RuntimeError(
                    "user '%s' is not an active user in clockify. \
                                    Please activate the user for the migration process"
                    % user["email"]
                )

            self._api_users.append(user)

            if retval["email"].lower() == admin_email.lower():
                admin_found = True

            if self.fallback_email is not None:
                if retval["email"].lower() == self.fallback_email.lower():
                    fallback_found = True

            self.logger.info("...ok, key resolved to email %s", retval["email"])

        if not admin_found:
            raise RuntimeError(
                "admin mail address was given as %s \
                                but not found in clockify API tokens"
                % admin_email
            )

        if not fallback_found and self.fallback_email is not None:
            raise RuntimeError(
                "falback user mail address was given as %s \
                                but not found in clockify API tokens"
                % self.fallback_email
            )

    def _load_admin(self):
        """
        Loads admin user as current api user.
        """
        return self._load_user(self._admin_email)

    def _load_user(self, email):
        """
        Loads given email as api user
        """
        current_email = self._loaded_user_email
        if current_email is None:
            current_email = ""

        # Early exit if already loaded.
        if email.lower() == current_email.lower():
            return RetVal.OK

        success = False
        for user in self._api_users:
            if user["email"].lower() == email.lower():
                self.api_token = user["token"]
                self.user_email = user["email"]
                self.user_id = user["id"]
                url = self.url + "/user"
                retval = self._request(url)
                if retval.status_code != 200:
                    raise RuntimeError(
                        "error loading user %s, status code %s"
                        % (user["email"], str(retval.status_code))
                    )
                success = True
                self._loaded_user_email = user["email"]
                break

        if not success:
            retval = RetVal.ERR
            self.logger.warning("user %s not found", email)
        else:
            retval = RetVal.OK

        return retval

    def multi_get_request(self, url, id_key="id"):
        """
        Paginated get request
        """
        headers = {"X-Api-Key": self.api_token}

        page = 1
        retval_data = []
        while True:
            start_ts = time.time()
            body = {"page": page, "page-size": 50}
            retval = requests.get(url, headers=headers, params=body)
            if retval.status_code == 200:
                data = retval.json()
                if len(data) < 50:
                    retval_data.extend(data)
                    break

                # check if we got new data
                check_id = data[0][id_key]
                if not any(d[id_key] == check_id for d in retval_data):
                    retval_data.extend(data)
                else:
                    break
                page += 1
            elif retval.status_code == 429:
                time.sleep(1.0)
                self.time_per_request *= 1.1
                self.logger.warning(
                    "Timed out. Setting cooldown to %s and retrying",
                    str(self.time_per_request),
                )
            else:
                raise RuntimeError(
                    "get on url %s failed with status code %d"
                    % (url, retval.status_code)
                )
            if time.time() - start_ts < self.time_per_request:
                time.sleep(self.time_per_request - (time.time() - start_ts))

        return retval_data

    def _request(self, url, body=None, typ="GET"):
        """
        Executes a requests.get/put/post/delete
        Automatically halts to prevent overloading API limit
        """
        start_ts = time.time()
        headers = {"X-Api-Key": self.api_token}
        if typ == "GET":
            response = requests.get(url, headers=headers, params=body)
        elif typ == "PUT":
            response = requests.put(url, headers=headers, json=body)
        elif typ == "POST":
            response = requests.post(url, headers=headers, json=body)
        elif typ == "DELETE":
            response = requests.delete(url, headers=headers)
        else:
            raise RuntimeError(f"invalid request type {typ}")

        if time.time() - start_ts < self.time_per_request:
            time.sleep(self.time_per_request - (time.time() - start_ts))

        # retry on timeout
        if response.status_code == 429:
            time.sleep(1.0)
            self.time_per_request *= 1.1
            self.logger.warning(
                "Timed out. Setting cooldown to %f and retrying", self.time_per_request
            )
            return self._request(url, body, typ)

        return response

    def get_workspaces(self):
        """
        get cached workspaces
        """
        return self.workspaces

    def get_workspace_id(self, workspace_name):
        """
        Convert from workspace_name to id
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

    def _get_workspaces(self):
        """
        Return current workspaces
        """
        url = self.url + "/workspaces"
        retval = self._request(url)
        if retval.status_code == 200:
            self.workspaces = retval.json()
        else:
            raise RuntimeError(
                "Querying workspaces for user %s failed, status code=%d, msg=%s"
                % (self._api_users[0]["email"], retval.status_code, retval.text)
            )
        return self.workspaces

    def add_client(self, name, workspace):
        """
        Add client to workspace
        """
        cur_user = self._loaded_user_email
        self._load_admin()

        ws_id = self.get_workspace_id(workspace)
        url = self.url + "/workspaces/%s/clients" % ws_id
        params = {"name": name}
        retval = self._request(url, body=params, typ="POST")

        if not retval.ok:
            if retval.status_code == 400:
                retval = RetVal.EXISTS
            else:
                self.logger.warning(
                    "Error adding client %s, status code=%d, msg=%s",
                    name,
                    retval.status_code,
                    retval.reason,
                )
                retval = RetVal.ERR
        else:
            retval = RetVal.OK
            self._resync_clients = True

        self._load_user(cur_user)

        return retval

    def get_clients(self, workspace):
        """
        Lazily loads clients into self.clients and returns it
        """
        if self._resync_clients:
            cur_user = self._loaded_user_email
            self._load_admin()

            ws_id = self.get_workspace_id(workspace)
            url = self.url + "/workspaces/%s/clients" % ws_id
            self.clients = self.multi_get_request(url)
            self._resync_clients = False

            self.logger.info(
                "finished getting clockify clients, saving results to clockify_clients.json"
            )

            dump_json("clockify_clients.json", self.clients)

            self._load_user(cur_user)
        return self.clients

    def get_tasks_from_project_id(self, workspace, project_id):
        """
        Get tasks assigned to project
        """
        cur_user = self._loaded_user_email
        self._load_admin()

        ws_id = self.get_workspace_id(workspace)

        url = self.url + "/workspaces/%s/projects/%s/tasks" % (ws_id, project_id)
        self.project_tasks = self.multi_get_request(url)

        self._load_user(cur_user)

        return self.project_tasks

    def get_client_name(self, client_id, workspace, use_cache=False, null_ok=False):
        """
        get client_name from client_id
        """
        result = None
        if use_cache:
            clients = self.clients
        else:
            clients = self.get_clients(workspace)

        for client in clients:
            if client["id"] == client_id:
                result = client["name"]

        if result is None:
            if null_ok:
                result = ""
            else:
                raise RuntimeError(
                    "Client %s not found in workspace %s" % (client_id, workspace)
                )

        return result

    def get_client_id(self, client_name, workspace, use_cache=False, null_ok=False):
        """
        Get client_id from client_name
        """
        result = None
        if use_cache:
            clients = self.clients
        else:
            clients = self.get_clients(workspace)

        for client in clients:
            if client["name"] == client_name:
                result = client["id"]

        if result is None:
            if null_ok:
                return None

            raise RuntimeError(
                "Client %s not found in workspace %s" % (client_name, workspace)
            )
        return result

    def get_projects(self, workspace, use_cache=False):
        """
        Lazily loads self.projects and returns it
        """
        if self._resync_projects:

            if not use_cache:
                self.projects = []

                ws_id = self.get_workspace_id(workspace)
                url = self.url_working + "/workspaces/%s/projects" % ws_id

                self.projects = self.multi_get_request(url)

                self.logger.info(
                    "Finished getting clockify projects, \
                    saving results to clockify_projects.json"
                )

                dump_json("clockify_projects.json", self.projects)
            self._resync_projects = False

        return self.projects

    def get_project_id(self, proj_name, client, workspace, use_cache=False):
        """
        Returns project_id given project's name and client's name
        """
        result = None
        if use_cache:
            projects = self.projects
        else:
            projects = self.get_projects(workspace)

        for project in projects:
            if project["name"] == proj_name and match_client(proj_name, client):
                result = project["id"]
                break

        if result is None:
            raise RuntimeError(
                "Project %s with client %s not found in workspace %s"
                % (proj_name, str(client), workspace)
            )
        return result

    def get_project(self, project_id, workspace, use_cache=False):
        """
        Get project data (json with name, id, clients etc)
        """
        if use_cache:
            projects = self.projects
        else:
            projects = self.get_projects(workspace)

        for project in projects:
            if project["id"] == project_id:
                return project
        return None

    def get_users(self, workspace):
        """
        Reloads self.users lazily
        """
        if self._resync_users:
            cur_user = self._loaded_user_email
            self._load_admin()

            ws_id = self.get_workspace_id(workspace)
            url = self.url + "/workspace/%s/users" % ws_id
            retval = self._request(url, typ="GET")
            self.users = retval.json()
            self._resync_users = False

            self.logger.info(
                "finsihed getting clockify users, saving results to clockify_users.json"
            )

            dump_json("clockify_users.json", self.users)

            self._load_user(cur_user)
        return self.users

    def get_project_users(self, workspace_id, project_id):
        """
        Returns list of users in project
        """
        user_ids = []
        url = self.url_working + "/workspaces/%s/projects/%s/users" % (
            workspace_id,
            project_id,
        )

        retval = self._request(url, typ="GET")
        user_ids = retval.json()
        self.logger.info("Finished getting users already assigned to the project.")

        return user_ids

    def get_userid_from_name(self, username, workspace):
        """
        Convert from username to user_id
        """
        user_id = None
        users = self.get_users(workspace)
        for user in users:
            if user["name"] == username:
                user_id = user["id"]
        if user_id is None:
            raise RuntimeError(
                "User %s not found in workspace %s" % (username, workspace)
            )
        return user_id

    def get_email_by_id(self, user_id, workspace):
        """
        Convert from user_id to email
        """
        email = None
        users = self.get_users(workspace)
        for user in users:
            if user["id"] == user_id:
                email = user["email"]
        if email is None:
            raise RuntimeError(
                "User ID %s not found in workspace %s" % (user_id, workspace)
            )
        return email

    def get_userid_by_email(self, email, workspace):
        """
        Convert from email to userid
        """
        user_id = None
        users = self.get_users(workspace)
        for user in users:
            if user["email"] == email:
                user_id = user["id"]
        if user_id is None:
            raise RuntimeError("User %s not found in workspace %s" % (email, workspace))
        return user_id

    def add_project(
        self,
        name,
        client,
        workspace,
        public=False,
        billable=False,
        color="#f44336",
        memberships=None,
        hourly_rate=None,
        manager="",
    ):
        """
        Add project to workspace
        """
        cur_user = self._loaded_user_email
        if manager == "":
            if not public:
                admin = self._admin_email
                self.logger.warning(
                    "no manager found for project %s, making %s as manager", name, admin
                )
            self._load_admin()
        else:
            self._load_user(manager)

        workspace_id = self.get_workspace_id(workspace)
        client_id = None
        if client is not None:
            client_id = self.get_client_id(client, workspace, null_ok=True)

        url = self.url + "/workspaces/%s/projects" % workspace_id
        params = {
            "name": name,
            "isPublic": public,
            "billable": billable,
            "color": color,
        }

        if client_id is not None:
            params["clientId"] = client_id

        if memberships is not None:
            params["memberships"] = memberships.get_data()
        if hourly_rate is not None:
            params["hourlyRate"] = hourly_rate.rate
        retval = self._request(url, body=params, typ="POST")
        if retval.status_code == 201:
            self._resync_projects = True
            retval = RetVal.OK
        elif retval.status_code == 400:
            retval = RetVal.EXISTS
        elif retval.status_code == 403:
            retval = RetVal.FORBIDDEN
        else:
            self.logger.warning(
                "Error adding project  %s, status code=%d, msg=%s",
                name,
                retval.status_code,
                retval.reason,
            )
            retval = RetVal.ERR

        self._load_user(cur_user)

        return retval

    def add_groups_to_project(
        self, workspace, ws_id, proj_id, ws_group_ids, proj_groups
    ):
        """
        Add groups to project
        """
        # API fields to POST: {userIds = [], userGroupIds = []}
        # From: https://clockify.github.io/clockify_api_docs/#operation--workspaces--workspaceId--projects--projectId--team-post

        url = self.url_working + "/workspaces/%s/projects/%s/team" % (ws_id, proj_id)

        user_ids = []
        user_group_ids = []

        proj_users = self.get_project_users(ws_id, proj_id)

        if proj_users is not None:
            for user in proj_users:
                user_ids.append(user["id"])

        # Check for group_id existence
        for proj_group in proj_groups:
            try:
                group_id = proj_group["group_id"]
                ws_group_ids.index(group_id)  # check for existence
            except ValueError as error:
                self.logger.warning(
                    "Group id %d not found in toggl workspace, msg=%s",
                    group_id,
                    str(error),
                )
                break

        for proj_group in proj_groups:
            group_id = self.get_usergroup_id(proj_group["name"], workspace)
            user_group_ids.append(group_id)

        params = {"userIds": user_ids, "userGroupIds": user_group_ids}

        retval = self._request(url, body=params, typ="POST")
        if (retval.status_code == 201) or (retval.status_code == 200):
            retval = RetVal.OK
        elif retval.status_code == 400:
            retval = RetVal.EXISTS
        elif retval.status_code == 403:
            retval = RetVal.FORBIDDEN
        else:
            self.logger.warning(
                "Error adding Groups to Project, status code=%d, msg=%s",
                retval.status_code,
                retval.reason,
            )
            retval = RetVal.ERR

        return retval

    def get_usergroups(self, workspace):
        """
        Lazily load usergroups into self.usergroups and return them
        """
        if self._resync_groups:
            cur_user = self._loaded_user_email
            self._load_admin()

            self.usergroups = []
            ws_id = self.get_workspace_id(workspace)
            url = self.url_working + "/workspaces/%s/userGroups" % ws_id
            self.usergroups = self.multi_get_request(url)
            self._resync_groups = False

            self.logger.info(
                "Finished getting clockify groups, saving results to clockify_groups.json"
            )

            dump_json("clockify_groups.json", self.usergroups)

            self._load_user(cur_user)
        return self.usergroups

    def add_usergroup(self, group_name, workspace):
        """
        Add usergrup to workspace
        """
        cur_user = self._loaded_user_email
        self._load_admin()

        ws_id = self.get_workspace_id(workspace)
        url = self.url_working + "/workspaces/%s/userGroups/" % ws_id
        params = {"name": group_name}
        retval = self._request(url, body=params, typ="POST")
        if retval.status_code == 201:
            self._resync_groups = True
            retval = RetVal.OK
        elif retval.status_code == 400:
            retval = RetVal.EXISTS
        else:
            self.logger.warning(
                "Error adding group %s, status code=%d, msg=%s",
                group_name,
                retval.status_code,
                retval.reason,
            )
            retval = RetVal.ERR

        self._load_user(cur_user)
        return retval

    def get_usergroup_name(self, usergroup_id, workspace):
        """
        Converts from usergroup_id to usergroup_name
        """
        usergroup_name = None
        usergroups = self.get_usergroups(workspace)
        for usergroup in usergroups:
            if usergroup["id"] == usergroup_id:
                usergroup_name = usergroup["name"]
        if usergroup_name is None:
            raise RuntimeError(
                "User Group %s not found in workspace %s" % (usergroup_id, workspace)
            )
        return usergroup_name

    def get_usergroup_id(self, usergroup_name, workspace):
        """
        Converts from usergroup_name to id
        """
        usergroup_id = None
        user_groups = self.get_usergroups(workspace)
        for usergroup in user_groups:
            if usergroup["name"] == usergroup_name:
                usergroup_id = usergroup["id"]

        if usergroup_id is None:
            raise RuntimeError(
                "User Group %s not found in workspace %s" % (usergroup_name, workspace)
            )
        return usergroup_id

    def get_tags(self, workspace):
        """
        Lazily loads tags into self.tags and returns them.
        """
        if self._resync_tags:
            cur_user = self._loaded_user_email
            self._load_admin()

            self.tags = []
            ws_id = self.get_workspace_id(workspace)
            url = self.url + "/workspaces/%s/tags" % ws_id
            self.tags = self.multi_get_request(url)
            self._resync_tags = False

            self.logger.info(
                "Finished getting clockify tags, saving results to clockify_tags.json"
            )

            dump_json("clockify_tags.json", self.tags)

            self._load_user(cur_user)
        return self.tags

    def add_tag(self, tag_name, workspace):
        """
        Add tag to workspace
        """
        # change to admin and then back again at the end.
        cur_user = self._loaded_user_email
        self._load_admin()

        ws_id = self.get_workspace_id(workspace)
        url = self.url + "/workspaces/%s/tags" % ws_id
        params = {"name": tag_name}
        retval = self._request(url, body=params, typ="POST")
        if retval.status_code == 201:
            self._resync_tags = True
            retval = RetVal.OK
        elif retval.status_code == 400:
            retval = RetVal.EXISTS
        else:
            self.logger.warning(
                "Error adding tag %s, status code=%d, msg=%s",
                tag_name,
                retval.status_code,
                retval.reason,
            )
            retval = RetVal.ERR

        self._load_user(cur_user)
        return retval

    def get_tag_name(self, tag_id, workspace):
        """
        Gets tag_name from tag_id
        """
        tag_name = None
        tags = self.get_tags(workspace)
        for tag in tags:
            if tag["id"] == tag_id:
                tag_name = tag["name"]
        if tag_name is None:
            raise RuntimeError(
                "TagID %s not found in workspace %s" % (tag_id, workspace)
            )
        return tag_name

    def get_tag_id(self, tag_name, workspace):
        """
        Gets tag_id from tag_name
        """
        tag_id = None
        tags = self.get_tags(workspace)
        for tag in tags:
            if tag["name"] == tag_name:
                tag_id = tag["id"]
        if tag_id is None:
            raise RuntimeError(
                "Tag %s not found in workspace %s" % (tag_name, workspace)
            )
        return tag_id

    def add_task(self, workspace_id, name, project_id, estimate):
        """
        Add task to workspace
        """
        cur_user = self._loaded_user_email
        self._load_admin()

        url = self.url + "/workspaces/%s/projects/%s/tasks/" % (
            workspace_id,
            project_id,
        )
        params = {"name": name, "projectId": project_id, "estimate": estimate}
        retval = self._request(url, body=params, typ="POST")
        if retval.status_code == 201:
            self._resync_tasks = True
            retval = RetVal.OK
        elif retval.status_code == 400:
            retval = RetVal.EXISTS
        else:
            self.logger.warning(
                "Error adding task %s, status code=%d, msg=%s",
                name,
                retval.status_code,
                retval.reason,
            )
            retval = RetVal.ERR

        self._load_user(cur_user)
        return retval

    def add_entries_threaded(self, entry_tasks):
        """
        entry_tasks is a list of lists, each task represents an entry to add, and its contents the arguments
        to _add_entry_threaded
        """
        # Create a shared status array, add it to the entry_task
        # so they can update the shared status array can be updated
        num_tasks = len(entry_tasks)
        status_indicator = [0, num_tasks]
        for task in entry_tasks:
            task.append(status_indicator)

        return self.thread_pool.starmap(self._add_entry_threaded, entry_tasks)

    def _add_entry_threaded(
        self,
        start,
        description,
        proj_name,
        client_name,
        email,
        workspace,
        timezone,
        end,
        billable,
        tag_names,
        task_name,
        threaded_status,
    ):
        """
        Private mutlithreaded entry adding wrapper
        """
        result = self.add_entry(
            start,
            description,
            proj_name,
            client_name,
            email,
            workspace,
            timezone,
            end,
            billable,
            tag_names,
            task_name,
        )
        threaded_status[0] += 1
        self.logger.info(
            "Added Entries: (%d / %d)", threaded_status[0], threaded_status[1]
        )
        return result

    def add_entry(
        self,
        start,
        description,
        project_name,
        client_name,
        email,
        workspace,
        timezone="Z",
        end=None,
        billable=False,
        tag_names=None,
        task_name=None,
    ):
        """
        Adds a given entry
        """
        retval = self._load_user(email)
        entry = None

        if retval == RetVal.OK:
            ws_id = self.get_workspace_id(workspace)
            url = self.url + "/workspaces/%s/time-entries" % ws_id

            task_id = None
            if project_name is not None:
                proj_id = self.get_project_id(project_name, client_name, workspace)

                if task_name is not None:
                    proj_tasks = self.get_tasks_from_project_id(workspace, proj_id)
                    task_id = get_task_id_from_name(task_name, proj_tasks)
                    self.logger.info(
                        "Found task %s in project %s", task_name, project_name
                    )
            else:
                self.logger.info("no project in entry %s", description)

            start_time = start.isoformat() + timezone
            if end is not None:
                end = end.isoformat() + timezone

            params = {
                "start": start_time,
                "billable": billable,
                "description": description,
            }

            if project_name is not None:
                params["projectId"] = proj_id

            if task_id is not None:
                params["taskId"] = task_id

            if end is not None:
                params["end"] = end
            else:
                params["end"] = start_time

            if tag_names is not None:
                tag_ids = []
                for tag in tag_names:
                    tid = self.get_tag_id(tag, workspace)
                    tag_ids.append(tid)
                params["tagIds"] = tag_ids

            retval, entries = self.get_time_entries(
                email,
                workspace,
                description,
                project_name,
                client_name,
                start,
                timezone=timezone,
            )

            if retval == RetVal.OK:
                if entries != []:
                    # filter data
                    filtered_data = []
                    for entry in entries:
                        has_diff = False
                        if params["start"] != entry["timeInterval"]["start"]:
                            has_diff = True
                        # self.logger.info("entry diff @start: %s %s"%(str(params["start"]), str(d['timeInterval']["start"])))
                        if (
                            "projectId" in params
                            and params["projectId"] != entry["projectId"]
                        ):
                            has_diff = True
                        # self.logger.info("entry diff @projectID: %s %s"%(str(params["projectId"]), str(d['projectId'])))
                        if params["description"] != entry["description"]:
                            has_diff = True
                        # self.logger.info("entry diff @desc: %s %s"%(str(params["description"]), str(d['description'])))
                        if self.user_id != entry["userId"]:
                            has_diff = True
                        # self.logger.info("entry diff @userID: %s %s"%(str(self.userID), str(d['userId'])))
                        if tag_names is not None:
                            tag_ids_recved = entry["tagIds"]
                            tag_ids_recved = tag_ids_recved or []
                            tag_names_recved = []
                            for tag_id in tag_ids_recved:
                                tag_names_recved.append(
                                    self.get_tag_name(tag_id, workspace)
                                )
                            if set(tag_names) != set(tag_names_recved):
                                # self.logger.info("entry diff @tagNames: %s %s"%(str(set(tagNames)), str(set(tagNamesRcv))))
                                has_diff = True

                        if not has_diff:
                            filtered_data.append(entry)

                    entries = filtered_data

                if not entries:
                    retval = self._request(url, body=params, typ="POST")
                    if retval.ok:
                        self.logger.info(
                            "Added entry:\n%s", json.dumps(params, indent=2)
                        )
                        entry = retval.json()
                        retval = RetVal.OK
                    else:
                        self.logger.warning(
                            "Error adding time entry:\n%s, status code=%d, msg=%s",
                            json.dumps(params, indent=2),
                            retval.status_code,
                            retval.text,
                        )
                        retval = RetVal.ERR
                else:
                    retval = RetVal.EXISTS
            else:
                retval = RetVal.ERR

        return retval, entry

    def get_time_entries(
        self,
        email,
        workspace,
        description,
        project_name,
        client_name,
        start,
        timezone="Z",
    ):
        """
        Returns the time entries for a given user
        """
        data = None
        retval = self._load_user(email)

        if retval == RetVal.OK:
            ws_id = self.get_workspace_id(workspace)
            url = self.url + "/workspaces/%s/user/%s/time-entries" % (
                ws_id,
                self.user_id,
            )
            params = {"description": description}

            if start is not None:
                start = start.isoformat() + timezone
                params["start"] = start

            if project_name is not None:
                proj_id = self.get_project_id(project_name, client_name, workspace)
                params["project"] = proj_id

            retval = self._request(url, body=params, typ="GET")
            if retval.ok:
                data = retval.json()
                retval = RetVal.OK
            else:
                self.logger.warning(
                    "Error getTimeEntryForUser, status code=%d, msg=%s",
                    retval.status_code,
                    retval.reason,
                )
                retval = RetVal.ERR

        return retval, data

    def archive_project(self, project):
        """
        Sets project to archived. Pass in the project dictionary.
        """
        proj_id = project["id"]
        workspace_id = project["workspaceId"]
        project["archived"] = True
        proj_name = get_projname_from_dict(project)

        url = self.url_working + "/workspaces/%s/projects/%s" % (workspace_id, proj_id)
        retval = self._request(url, body=project, typ="PUT")
        if retval.status_code == 200:
            retval = RetVal.OK
        else:
            self.logger.warning(
                "Archiving project %s failed, status code=%d, msg=%s",
                str(proj_name),
                retval.status_code,
                retval.reason,
            )
            retval = RetVal.ERR

        return retval

    def delete_user_entries(self, email, workspace):
        """
        Deletes all user's time entries
        """
        ws_id = self.get_workspace_id(workspace)
        while True:
            self.logger.info("Fetching more entries (50 at a time):")
            retval, entries = self.get_time_entries(
                email, workspace, "", None, None, None, ""
            )
            entry_cnt = 0
            if retval == RetVal.OK:
                cur_user = self._loaded_user_email
                retval = self._load_admin()
                if retval == RetVal.OK:
                    entry_cnt = len(entries)
                    delete_tasks = []
                    task_status = ["_"] * entry_cnt
                    # add tasks to task list
                    for idx, entry in enumerate(entries):
                        delete_tasks.append(
                            (entry["id"], ws_id, (idx, entry_cnt, task_status))
                        )
                    retval = self.thread_pool.starmap(
                        self.delete_entry_threaded, delete_tasks
                    )

                self._load_user(cur_user)
            if entry_cnt == 0:
                break
        return entry_cnt

    def delete_entry_threaded(self, entry_id, workspace_id, task_info):
        """
        Pretty prints deleteEntry, assuming it receives a few status variables
        """
        dem, nom, status_arr = task_info
        entry_str = "(%s / %s)" % (str(dem + 1), str(nom))

        retval = self.delete_entry(entry_id, workspace_id)  # actually do the work.

        if retval.ok:
            status_arr[dem] = "O"
            self.logger.info("".join(status_arr))
            return RetVal.OK

        status_arr[dem] = "X"
        self.logger.info("".join(status_arr))
        self.logger.warning(
            "Error deleteEntry %s, status code=%d, msg=%s",
            entry_str,
            retval.status_code,
            retval.reason,
        )
        return RetVal.ERR

    def delete_entry(self, entry_id, ws_id):
        """
        Returns a direct requests.request result, including retval.ok, retval.status_code etc.
        """
        url = self.url + "/workspaces/%s/time-entries/%s" % (ws_id, entry_id)
        retval = self._request(url, typ="DELETE")
        return retval

    def delete_project(self, project):
        """
        Deletes a given project (pass in the project's dictionary)
        """
        ws_id = project["workspaceId"]
        proj_id = project["id"]
        # We have to archive before deletion.
        self.logger.info(
            "Archiving project before deletion (this is required by the API):"
        )
        retval = self.archive_project(project)
        if retval == RetVal.OK:
            self.logger.info("...ok")

        # Now we can delete.
        self.logger.info("Deleting project:")
        url = self.url_working + "/workspaces/%s/projects/%s" % (ws_id, proj_id)
        retval = self._request(url, typ="DELETE")

        if retval.ok:
            self._resync_projects = True
            self.logger.info("...ok")
            return RetVal.OK

        self.logger.warning(
            "Error delete_project, status code=%d, msg=%s",
            retval.status_code,
            retval.reason,
        )
        return RetVal.ERR

    def delete_all_projects(self, workspace):
        """
        Deletes all projects in the workspace
        """
        cur_user = self._loaded_user_email  # store current user
        for user in self._api_users:
            self._load_user(user["email"])
            self.logger.info("Deleting all project from user %s", user["email"])
            projects = self.get_projects(workspace)

            project_cnt = len(projects)
            for idx, project in enumerate(projects):
                c_name = get_clientname_from_dict(project)
                p_name = get_projname_from_dict(project)
                msg = "deleting project %s (%d of %d)" % (
                    str(p_name) + "|" + str(c_name),
                    idx + 1,
                    project_cnt,
                )
                self.logger.info(msg)
                self.delete_project(project)

        self._load_user(cur_user)  # restore previous user

    def wipeout_workspace(self, workspace):
        """
        Deletes all contents of workspace, starting from entries
        then proceeding to projects, clients, tags and tasks
        """
        cur_user = self._loaded_user_email
        for user in self._api_users:
            self.logger.info("Deleting all entries from user %s", user["email"])
            self.delete_user_entries(user["email"], workspace)

        # self.delete_all_tags(workspace) not implemented
        # self.delete_all_tasks(workspace) not implemented
        # self.delete_all_groups(workspace) not implemented
        self.delete_all_projects(workspace)
        self.delete_all_clients(workspace)

        self._load_user(cur_user)

    def delete_client(self, client_id, workspace_id):
        """
        Deletes a given client
        """
        url = self.url_working + "/workspaces/%s/clients/%s" % (workspace_id, client_id)
        retval = self._request(url, typ="DELETE")
        if retval.ok:
            self._resync_clients = True
            return RetVal.OK

        self.logger.warning(
            "Error delete_client, status code=%d, msg=%s",
            retval.status_code,
            retval.reason,
        )
        return RetVal.ERR

    def delete_all_clients(self, workspace):
        """
        Deletes all clients in workspace
        """
        clients = self.get_clients(workspace)

        num_clients = len(clients)
        for idx, client in enumerate(clients):
            msg = "Deleting client %s (%d of %d)" % (
                client["name"],
                idx + 1,
                num_clients,
            )
            self.logger.info(msg)
            self.delete_client(client["id"], client["workspaceId"])
