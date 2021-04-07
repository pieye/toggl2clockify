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
from toggl2clockify.clockify.entry import EntryQuery
from toggl2clockify.clockify.cached_list import CachedList


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

    # API limits. Add a small buffer so we dont hit the limit
    requests_per_second = 10.0  # Rate limit is 10/s
    time_per_request = 1.0 / (requests_per_second - 1)

    # API URLS
    base_url = "https://clockify.me/api/v1"
    base_url_api = "https://api.clockify.me/api/v1"

    def __init__(self, api_tokens, admin_email="", fallback_email=None):
        self.logger = logging.getLogger("toggl2clockify")

        projects_url = self.base_url_api + "/workspaces/%s/projects"
        users_url = self.base_url + "/workspace/%s/users"
        usergroups_url = self.base_url_api + "/workspaces/%/userGroups"
        tags_url = self.base_url + "/workspaces/%s/tags"
        clients_url = self.base_url + "/workspaces/%s/clients"

        self.projects = CachedList(projects_url, "projects", True)
        self.users = CachedList(users_url, "users", False)
        self.usergroups = CachedList(usergroups_url, "usergroups", True)
        self.tags = CachedList(tags_url, "tags", True)
        self.clients = CachedList(clients_url, "clients", True)

        self.admin_email = admin_email
        self.fallback_email = fallback_email
        self.thread_pool = ThreadPool(int(self.requests_per_second))
        # self.thread_pool = ThreadPool(int(1))

        self._api_users = []
        self.test_tokens(api_tokens)
        self._loaded_user_email = None
        self._load_user(self._api_users[0]["email"])

        self._get_workspaces()

    def test_tokens(self, api_tokens):
        """
        Test supplied api_tokens, and search for admin/fallback email
        """
        admin_found = False
        fallback_found = False
        for token in api_tokens:
            self.logger.info("testing clockify APIKey %s", token)

            self.api_token = token
            url = self.base_url + "/user"
            retval = self._request(url)
            if retval.status_code != 200:
                raise RuntimeError(
                    "Error loading user (API token %s), status code %s"
                    % (token, str(retval.status_code))
                )

            retval = retval.json()
            user = {}
            user["name"] = retval["name"]
            user["token"] = token
            user["email"] = retval["email"]
            user["id"] = retval["id"]

            active_status = ["ACTIVE", "PENDING_EMAIL_VERIFICATION"]
            if retval["status"].upper() not in active_status:
                raise RuntimeError(
                    "user '%s' is not an active user in clockify. \
                    Please activate the user for the migration process"
                    % user["email"]
                )

            self._api_users.append(user)

            if retval["email"].lower() == self.admin_email.lower():
                admin_found = True

            if (
                self.fallback_email is not None
                and retval["email"].lower() == self.fallback_email.lower()
            ):
                fallback_found = True

            self.logger.info("...ok, key resolved to email %s", retval["email"])

        if not admin_found:
            raise RuntimeError(
                "admin mail address was given as %s \
                but not found in clockify API tokens"
                % self.admin_email
            )

        if self.fallback_email is not None and not fallback_found:
            raise RuntimeError(
                "falback user mail address was given as %s \
                 but not found in clockify API tokens"
                % self.fallback_email
            )

    def _load_admin(self):
        """
        Loads admin user as current api user.
        """
        return self._load_user(self.admin_email)

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
                url = self.base_url + "/user"
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
        url = self.base_url + "/workspaces"
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
        url = self.base_url + "/workspaces/%s/clients" % ws_id
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
            self.clients.need_resync = True

        self._load_user(cur_user)

        return retval

    def get_clients(self, workspace):
        """
        Lazily loads clients into self.clients and returns it
        """
        workspace_id = self.get_workspace_id(workspace)
        return self.clients.get_data(self, workspace_id)

    def get_tasks_from_project_id(self, workspace, project_id):
        """
        Get tasks assigned to project
        """
        cur_user = self._loaded_user_email
        self._load_admin()

        ws_id = self.get_workspace_id(workspace)

        url = self.base_url + "/workspaces/%s/projects/%s/tasks" % (ws_id, project_id)
        project_tasks = self.multi_get_request(url)

        self._load_user(cur_user)

        return project_tasks

    def get_client_name(self, client_id, workspace, null_ok=False):
        """
        get client_name from client_id
        """
        result = None

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

    def get_client_id(self, client_name, workspace, null_ok=False):
        """
        Get client_id from client_name
        """
        result = None

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

    def get_projects(self, workspace):
        """
        Lazily loads self.projects and returns it
        """
        ws_id = self.get_workspace_id(workspace)
        return self.projects.get_data(self, ws_id)

    def get_project_id(self, proj_name, client, workspace):
        """
        Returns project_id given project's name and client's name
        """
        result = None

        projects = self.get_projects(workspace)

        for project in projects:
            if project["name"] == proj_name and match_client(project, client):
                result = project["id"]
                break

        if result is None:
            raise RuntimeError(
                "Project %s with client %s not found in workspace %s"
                % (proj_name, str(client), workspace)
            )
        return result

    def get_project(self, project_id, workspace):
        """
        Get project data (json with name, id, clients etc)
        """
        projects = self.get_projects(workspace)

        for project in projects:
            if project["id"] == project_id:
                return project
        return None

    def get_users(self, workspace):
        """
        Reloads self.users lazily
        """
        ws_id = self.get_workspace_id(workspace)
        return self.users.get_data(self, ws_id)

    def get_project_users(self, workspace_id, project_id):
        """
        Returns list of users in project
        """
        user_ids = []
        url = self.base_url_api + "/workspaces/%s/projects/%s/users" % (
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

    def _load_project_admin(self, project):
        """
        Set current user to project's manager,
        or default admin if no manager exists
        """
        if project.manager == "":
            self.logger.warning(
                "No manager for project: %s, using %s",
                project.name,
                self.admin_email,
            )
            self._load_admin()
        else:
            self._load_user(project, project.manager)

    def add_project(self, project):
        """
        Add project (clockify.project.Project) to workspace
        """
        # Load manager / admin for creating the project
        cur_user = self._loaded_user_email
        self._load_project_admin(project)

        # get url for request
        ws_id = self.get_workspace_id(project.workspace)
        url = self.base_url_api + "/workspaces/%s/projects" % ws_id

        # generate params json
        params = project.excrete(self)
        retval = self._request(url, body=params, typ="POST")
        if retval.status_code == 201:
            self.projects.need_resync = True
            retval = RetVal.OK
        elif retval.status_code == 400:
            retval = RetVal.EXISTS
        elif retval.status_code == 403:
            retval = RetVal.FORBIDDEN
        else:
            self.logger.warning(
                "Error adding project  %s, status code=%d, msg=%s",
                project.name,
                retval.status_code,
                retval.reason,
            )
            retval = RetVal.ERR

        self._load_user(cur_user)  # restore previous user

        return retval

    def add_groups_to_project(self, proj):
        # self, workspace, ws_id, proj_id, ws_group_ids, proj_groups
        """
        Add groups to project
        """
        ws_id = self.get_workspace_id(proj.workspace)
        proj_id = self.get_project_id(proj.name, proj.client, proj.workspace)
        url = self.base_url_api + "/workspaces/%s/projects/%s/team" % (ws_id, proj_id)

        user_ids = []
        user_group_ids = []

        proj_users = self.get_project_users(ws_id, proj_id)

        if proj_users is not None:
            for user in proj_users:
                user_ids.append(user["id"])

        for group_name in proj.proj_groups:
            group_id = self.get_usergroup_id(group_name, proj.workspace)
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
        ws_id = self.get_workspace_id(workspace)
        return self.usergroups.get_data(self, ws_id)

    def add_usergroup(self, group_name, workspace):
        """
        Add usergroup to workspace
        """
        cur_user = self._loaded_user_email
        self._load_admin()

        ws_id = self.get_workspace_id(workspace)
        url = self.base_url_api + "/workspaces/%s/userGroups/" % ws_id
        params = {"name": group_name}
        retval = self._request(url, body=params, typ="POST")
        if retval.status_code == 201:
            self.usergroups.need_resync = True
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
        ws_id = self.get_workspace_id(workspace)
        return self.tags.get_data(self, ws_id)

    def add_tag(self, tag_name, workspace):
        """
        Add tag to workspace
        """
        # change to admin and then back again at the end.
        cur_user = self._loaded_user_email
        self._load_admin()

        ws_id = self.get_workspace_id(workspace)
        url = self.base_url + "/workspaces/%s/tags" % ws_id
        params = {"name": tag_name}
        retval = self._request(url, body=params, typ="POST")
        if retval.status_code == 201:
            self.tags.need_resync = True
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

        url = self.base_url + "/workspaces/%s/projects/%s/tasks/" % (
            workspace_id,
            project_id,
        )
        params = {"name": name, "projectId": project_id, "estimate": estimate}
        retval = self._request(url, body=params, typ="POST")
        if retval.status_code == 201:
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

    def add_entries_threaded(self, entries):
        """
        entries is a list Entries
        """
        # Create a shared status array, add it to the entry_task
        # so they can update the shared status array can be updated
        num_tasks = len(entries)
        status_indicator = [0, num_tasks]

        # create a new task
        new_tasks = [[entry, status_indicator] for entry in entries]

        return self.thread_pool.starmap(self._add_entry_threaded, new_tasks)

    def _add_entry_threaded(self, entry, status_indicator):
        """
        Private multithreaded entry adding wrapper
        """
        result = self.add_entry(entry)
        status_indicator[0] += 1

        if result[0] == RetVal.EXISTS:
            msg = "Added entries (skipped) (%d / %d)"
        else:
            msg = "Added entries: (%d / %d)"
        msg = msg % tuple(status_indicator)
        self.logger.info(msg)
        return result

    def is_duplicate_entry(self, source, entries):
        """
        Returns if source exists inside entries
        """
        for entry in entries:
            different = source.diff_entry(entry, self, self.user_id)
            same = not different
            if same:
                return True
        return False

    def add_entry(self, entry):
        """
        Adds a given entry
        """
        retval = self._load_user(entry.email)
        if retval != RetVal.OK:
            return retval, None

        # get clockify ids
        entry.process_ids(self)
        api_dict = entry.to_api_dict()

        query = EntryQuery(entry)
        retval, web_entries = self.get_time_entries(query)

        if retval != RetVal.OK:  # Fail to get web entries
            return RetVal.ERR, None

        # Check if the entry already exists
        if self.is_duplicate_entry(entry, web_entries):
            return RetVal.EXISTS, None

        # actually add the entry
        ws_id = entry.workspace_id
        url = self.base_url + "/workspaces/%s/time-entries" % ws_id
        retval = self._request(url, body=api_dict, typ="POST")
        if not retval.ok:
            # Failed to add entry
            self.logger.warning(
                "Error adding time entry:\n%s, status code=%d, msg=%s",
                json.dumps(api_dict, indent=2),
                retval.status_code,
                retval.text,
            )
            return RetVal.ERR, None

        self.logger.info("Added entry:\n%s", json.dumps(api_dict, indent=2))
        return RetVal.OK, retval.json()

    def get_time_entries(self, query):
        """
        Returns the time entries for a given user
        """
        data = None
        retval = self._load_user(query.email)

        if retval == RetVal.OK:
            ws_id = self.get_workspace_id(query.workspace)
            url = self.base_url + "/workspaces/%s/user/%s/time-entries" % (
                ws_id,
                self.user_id,
            )
            params = query.to_api_dict(self)

            retval = self._request(url, body=params, typ="GET")
            if retval.ok:
                data = retval.json()
                retval = RetVal.OK
            else:
                self.logger.warning(
                    "Error get_time_entries, status code=%d, msg=%s\n%s",
                    retval.status_code,
                    retval.reason,
                    params,
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

        url = self.base_url_api + "/workspaces/%s/projects/%s" % (workspace_id, proj_id)
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
            query = EntryQuery(email, workspace)
            retval, entries = self.get_time_entries(query)
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
        url = self.base_url + "/workspaces/%s/time-entries/%s" % (ws_id, entry_id)
        retval = self._request(url, typ="DELETE")
        return retval

    def delete_project(self, project):
        """
        Deletes a given project (pass in the project's dictionary)
        """
        ws_id = project["workspaceId"]
        proj_id = project["id"]
        # We have to archive before deletion.
        self.archive_project(project)

        # Now we can delete.
        url = self.base_url_api + "/workspaces/%s/projects/%s" % (ws_id, proj_id)
        retval = self._request(url, typ="DELETE")

        if retval.ok:
            self.projects.need_resync = True
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

        self._load_user(self.admin_email)
        self.logger.info("Deleting all projects...")
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
        url = self.base_url_api + "/workspaces/%s/clients/%s" % (
            workspace_id,
            client_id,
        )
        retval = self._request(url, typ="DELETE")
        if retval.ok:
            self.clients.need_resync = True
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
