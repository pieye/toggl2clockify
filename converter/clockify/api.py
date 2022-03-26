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

from converter.clockify.retval import RetVal
from converter.clockify.entry import EntryQuery, is_duplicate_entry
from converter.clockify.cached_list import CachedList
from converter.clockify.helpers import match_client, safe_get, first
from converter.clockify.api_user import APIUser


class ClockifyAPI:
    """
    Entrypoint for Clockify's API
    https://clockify.me/developers-api
    """

    # API limits.
    requests_per_second = 10.0  # Rate limit is 10/s
    time_per_request = 1.0 / (requests_per_second)

    # API URLS
    base_url = "https://api.clockify.me/api/v1"

    def __init__(self, api_tokens, admin_email="", fallback_email=None):
        self.logger = logging.getLogger("toggl2clockify")

        projects_url = self.base_url + "/workspaces/%s/projects"
        users_url = self.base_url + "/workspace/%s/users"
        usergroups_url = self.base_url + "/workspaces/%s/user-groups"
        tags_url = self.base_url + "/workspaces/%s/tags"
        clients_url = self.base_url + "/workspaces/%s/clients"

        self.projects = CachedList(projects_url, "projects", True)
        self.users = CachedList(users_url, "users", False)
        self.usergroups = CachedList(usergroups_url, "usergroups", True)
        self.tags = CachedList(tags_url, "tags", True)
        self.clients = CachedList(clients_url, "clients", True)
        self.workspaces = None

        self.admin_email = admin_email
        self.fallback_email = fallback_email
        self.thread_pool = ThreadPool(int(self.requests_per_second))
        # self.thread_pool = ThreadPool(int(1))

        self._api_users = []
        self._test_tokens(api_tokens)
        self._get_workspaces()

    def _test_tokens(self, api_tokens):
        """
        Test supplied api_tokens, and search for admin/fallback email
        """
        admin_found = False
        fallback_found = False
        for token in api_tokens:
            self.logger.info("testing clockify APIKey %s", token)
            url = self.base_url + "/user"
            retval = self._request(url, token, None, "GET")
            if retval.status_code != 200:
                raise RuntimeError(
                    "Error loading user (API token %s), status code %s"
                    % (token, str(retval.status_code))
                )

            retval = retval.json()

            user = APIUser(token, retval["name"], retval["email"], retval["id"])

            active_status = ["ACTIVE", "PENDING_EMAIL_VERIFICATION"]
            if retval["status"].upper() not in active_status:
                raise RuntimeError(
                    "user '%s' is not an active user in clockify. \
                    Please activate the user for the migration process"
                    % user.email
                )

            self._api_users.append(user)

            if user.email.lower() == self.admin_email.lower():
                admin_found = True
                user.is_admin = True

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

    def _get_api_key(self, email):
        user = first(self._api_users, lambda x: x.email == email)
        return user.token

    def get_user_id(self, email):
        """
        returns clockify_id of given email
        """
        user = first(self._api_users, lambda x: x.email == email)
        return user.clockify_id

    def multi_get_request(self, url, email):
        """
        Paginated get request
        """
        api_token = self._get_api_key(email)

        headers = {"X-Api-Key": api_token}
        id_key = "id"
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

    def request(self, url, email, body=None, typ="GET"):
        """
        Executes a requests.get/put/post/delete
        Automatically halts to prevent overloading API limit
        """
        token = self._get_api_key(email)
        return self._request(url, token, body, typ)

    def _request(self, url, api_token, body, typ):
        """
        Internal request function
        """

        start_ts = time.time()
        headers = {"X-Api-Key": api_token}

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
            return self.request(url, body, typ)

        return response

    def get_workspace_id(self, workspace_name):
        """
        Convert from workspace_name to id
        """
        workspace = first(self.workspaces, lambda x: x["name"] == workspace_name)
        if workspace is not None:
            return workspace["id"]

        raise RuntimeError(
            "Workspace %s not found. Available workspaces: %s"
            % (workspace_name, self.workspaces)
        )

    def _get_workspaces(self):
        """
        Return current workspaces
        """
        if self.workspaces is None:
            url = self.base_url + "/workspaces"
            retval = self.request(url, self.admin_email)
            if retval.status_code == 200:
                self.workspaces = retval.json()
            else:
                raise RuntimeError(
                    "Querying workspaces for user %s failed, status code=%d, msg=%s"
                    % (self._api_users[0].email, retval.status_code, retval.text)
                )
        return self.workspaces

    def add_client(self, name, workspace):
        """
        Add client to workspace
        """
        ws_id = self.get_workspace_id(workspace)
        url = self.base_url + "/workspaces/%s/clients" % ws_id
        params = {"name": name}
        retval = self.request(url, self.admin_email, body=params, typ="POST")

        if not retval.ok:
            if retval.status_code == 400:
                self.logger.warning(
                    "Error adding client %s, status code=%d, msg=%s",
                    name,
                    retval.status_code,
                    retval.reason,
                )
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
        ws_id = self.get_workspace_id(workspace)
        url = self.base_url + "/workspaces/%s/projects/%s/tasks" % (ws_id, project_id)
        project_tasks = self.multi_get_request(url, self.admin_email)

        return project_tasks

    def get_client_name(self, client_id, workspace, null_ok=False):
        """
        get client_name from client_id
        """
        clients = self.get_clients(workspace)

        client = first(clients, lambda x: x["id"] == client_id)
        if client is not None:
            return client["name"]

        if null_ok:
            return ""

        raise RuntimeError(
            "Client %s not found in workspace %s" % (client_id, workspace)
        )

    def get_client_id(self, client_name, workspace, null_ok=False):
        """
        Get client_id from client_name
        """
        clients = self.get_clients(workspace)

        client = first(clients, lambda x: x["name"] == client_name)
        if client is not None:
            return client["id"]

        if null_ok:
            return None

        raise RuntimeError(
            "Client %s not found in workspace %s" % (client_name, workspace)
        )

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
        projects = self.get_projects(workspace)
        condition = lambda x: x["name"] == proj_name and match_client(x, client)
        project = first(projects, condition)
        if project is not None:
            return project["id"]

        raise RuntimeError(
            "Project %s with client %s not found in workspace %s"
            % (proj_name, str(client), workspace)
        )

    def get_project(self, project_id, workspace):
        """
        Get project data (json with name, id, clients etc)
        """
        projects = self.get_projects(workspace)

        project = first(projects, lambda x: x["id"] == project_id)
        return project

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
        url = self.base_url + "/workspaces/%s/users" % (
            workspace_id
        )

        payload = {project_id: project_id}
        retval = self.request(url, self.admin_email, body=payload, typ="GET")
        user_ids = retval.json()
        self.logger.info("Finished getting users already assigned to the project.")

        return user_ids

    def get_userid_from_name(self, username, workspace):
        """
        Convert from username to user_id
        Returns None on failure
        """
        users = self.get_users(workspace)
        user = first(users, lambda x: x["name"] == username)
        if user is not None:
            return user["id"]

        return None

    def get_email_by_id(self, user_id, workspace):
        """
        Convert from user_id to email
        Returns None on failure.
        """
        users = self.get_users(workspace)
        user = first(users, lambda x: x["id"] == user_id)
        if user is not None:
            return user["email"]

        return None

    def get_userid_by_email(self, email, workspace):
        """
        Convert from email to userid
        Returns None on failure.
        """
        users = self.get_users(workspace)
        user = first(users, lambda x: x["email"] == email)
        if user is not None:
            return user["id"]

        return None

    def _get_project_admin(self, project):
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
            return self.admin_email

        return project.manager

    def add_project(self, project):
        """
        Add project (clockify.project.Project) to workspace
        """
        # Load manager / admin for creating the project
        email = self._get_project_admin(project)

        # get url for request
        ws_id = self.get_workspace_id(project.workspace)
        url = self.base_url + "/workspaces/%s/projects" % ws_id

        # generate params json
        params = project.excrete(self)
        retval = self.request(url, email, body=params, typ="POST")
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

        return retval

    def add_groups_to_project(self, proj):
        # self, workspace, ws_id, proj_id, ws_group_ids, proj_groups
        """
        Add groups to project
        """
        ws_id = self.get_workspace_id(proj.workspace)
        proj_id = self.get_project_id(proj.name, proj.client, proj.workspace)
        url = self.base_url + "/workspaces/%s/projects/%s/team" % (ws_id, proj_id)
        email = self._get_project_admin(proj)

        user_ids = []
        user_group_ids = []

        proj_users = self.get_project_users(ws_id, proj_id)

        if proj_users is not None:
            for user in proj_users:
                user_ids.append(user["id"])

        for group_name in proj.groups:
            group_id = self.get_usergroup_id(group_name, proj.workspace)
            user_group_ids.append(group_id)

        params = {"userIds": user_ids, "userGroupIds": user_group_ids}

        retval = self.request(url, email, body=params, typ="POST")
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

        ws_id = self.get_workspace_id(workspace)
        url = self.base_url + "/workspaces/%s/user-groups/" % ws_id
        params = {"name": group_name}
        retval = self.request(url, self.admin_email, body=params, typ="POST")
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
        user_groups = self.get_usergroups(workspace)
        for usergroup in user_groups:
            if usergroup["name"] == usergroup_name:
                return usergroup["id"]

        raise RuntimeError(
            "User Group %s not found in workspace %s" % (usergroup_name, workspace)
        )

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

        ws_id = self.get_workspace_id(workspace)
        url = self.base_url + "/workspaces/%s/tags" % ws_id
        params = {"name": tag_name}
        retval = self.request(url, self.admin_email, body=params, typ="POST")
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

        return retval

    def get_tag_name(self, tag_id, workspace):
        """
        Gets tag_name from tag_id
        """
        tags = self.get_tags(workspace)
        tag = first(tags, lambda x: x["id"] == tag_id)
        if tag is not None:
            return tag["name"]

        raise RuntimeError("TagID %s not found in workspace %s" % (tag_id, workspace))

    def get_tag_id(self, tag_name, workspace):
        """
        Gets tag_id from tag_name
        """
        tags = self.get_tags(workspace)
        tag = first(tags, lambda x: x["name"] == tag_name)
        if tag is not None:
            return tag["id"]

        raise RuntimeError("Tag %s not found in workspace %s" % (tag_name, workspace))

    def add_task(self, workspace_id, name, project_id, estimate):
        """
        Add task to workspace
        """
        url = self.base_url + "/workspaces/%s/projects/%s/tasks/" % (
            workspace_id,
            project_id,
        )
        params = {"name": name, "projectId": project_id, "estimate": estimate}
        retval = self.request(url, self.admin_email, body=params, typ="POST")
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

    def add_entry(self, entry):
        """
        Adds a given entry
        """
        # get clockify ids
        entry.process_ids(self)
        api_dict = entry.to_api_dict()

        query = EntryQuery(entry)
        retval, web_entries = self.get_time_entries(query)

        if retval != RetVal.OK:  # Fail to get web entries
            return RetVal.ERR, None

        # Check if the entry already exists
        if is_duplicate_entry(entry, web_entries):
            return RetVal.EXISTS, None

        # actually add the entry
        ws_id = entry.workspace_id
        url = self.base_url + "/workspaces/%s/time-entries" % ws_id
        retval = self.request(url, entry.email, body=api_dict, typ="POST")
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

        ws_id = self.get_workspace_id(query.workspace)
        url = self.base_url + "/workspaces/%s/user/%s/time-entries" % (
            ws_id,
            query.user_id,
        )
        params = query.to_api_dict(self)

        retval = self.request(url, query.email, body=params, typ="GET")
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

        url = self.base_url + "/workspaces/%s/projects/%s" % (workspace_id, proj_id)
        retval = self.request(url, self.admin_email, body=project, typ="PUT")
        if retval.status_code == 200:
            retval = RetVal.OK
        else:
            self.logger.warning(
                "Archiving project %s failed, status code=%d, msg=%s",
                str(safe_get(project, "name")),
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
        user = first(self._api_users, lambda x: x.email == email)
        query = EntryQuery(email, workspace)
        query.user_id = user.clockify_id

        while True:
            self.logger.info("Fetching more entries (50 at a time):")

            retval, entries = self.get_time_entries(query)  # returns first 50

            entry_cnt = 0

            if retval == RetVal.OK:
                entry_cnt = len(entries)
                delete_tasks = []
                task_status = ["_"] * entry_cnt
                # add tasks to task list
                for idx, entry in enumerate(entries):
                    delete_tasks.append(
                        (entry["id"], ws_id, (idx, entry_cnt, task_status))
                    )
                # do actual deletion
                retval = self.thread_pool.starmap(
                    self.delete_entry_threaded, delete_tasks
                )

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
        retval = self.request(url, self.admin_email, typ="DELETE")
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
        url = self.base_url + "/workspaces/%s/projects/%s" % (ws_id, proj_id)
        retval = self.request(url, self.admin_email, typ="DELETE")

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
        self.logger.info("Deleting all projects...")
        projects = self.get_projects(workspace)

        project_cnt = len(projects)
        for idx, project in enumerate(projects):
            c_name = safe_get(project, "clientName")
            p_name = safe_get(project, "name")
            msg = "deleting project %s (%d of %d)" % (
                str(p_name) + "|" + str(c_name),
                idx + 1,
                project_cnt,
            )
            self.logger.info(msg)
            self.delete_project(project)

    def wipeout_workspace(self, workspace):
        """
        Deletes all contents of workspace, starting from entries
        then proceeding to projects, clients, tags and tasks
        """
        for user in self._api_users:
            self.logger.info("Deleting all entries from user %s", user.email)
            self.delete_user_entries(user.email, workspace)

        # self.delete_all_tags(workspace) not implemented
        # self.delete_all_tasks(workspace) not implemented
        # self.delete_all_groups(workspace) not implemented
        self.delete_all_projects(workspace)
        self.delete_all_clients(workspace)

    def delete_client(self, client_id, workspace_id):
        """
        Deletes a given client
        """
        url = self.base_url + "/workspaces/%s/clients/%s" % (
            workspace_id,
            client_id,
        )
        retval = self.request(url, self.admin_email, typ="DELETE")
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
