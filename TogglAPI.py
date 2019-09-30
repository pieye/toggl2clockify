#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = "Markus Proeller"
__copyright__ = "Copyright 2019, pieye GmbH (www.pieye.org)"
__maintainer__ = "Markus Proeller"
__email__ = "markus.proeller@pieye.org"

import base64
import requests
import time
import datetime
import logging
import json


class TogglAPI:
    def __init__(self, apiToken):
        self.logger = logging.getLogger('toggl2clockify')
        self.apiToken = apiToken
        self.url = 'https://www.toggl.com/api/v8/me'

        response = self._request(self.url)
        if response.status_code != 200:
            raise RuntimeError("Login failed. Check your API key")

        response = response.json()
        self.email = response['data']['email']
        self._getWorkspaces()
        self._syncProjects = True
        self._syncClients = True
        self._syncUsers = True
        self._syncTags = True
        self._syncGroups = True
        self._syncTasks = True

    def _request(self, url, params=None):
        string = self.apiToken + ':api_token'
        headers = {
            'Authorization': 'Basic ' + base64.b64encode(string.encode('ascii')).decode("utf-8")}
        response = requests.get(url, headers=headers, params=params)
        time.sleep(1)
        return response

    def _getWorkspaces(self):
        response = self._request(self.url)
        response = response.json()
        self.workspace_ids_names = [{'name': item['name'], 'id': item['id']} for item in response['data']['workspaces']
                                    if item['admin'] == True]

    def getWorkspaces(self):
        return self.workspace_ids_names

    def getWorkspaceID(self, workspaceName):
        ws_id = None
        workspaces = self.getWorkspaces()
        for ws in workspaces:
            if ws["name"] == workspaceName:
                ws_id = ws["id"]
        if ws_id == None:
            raise RuntimeError("Workspace %s not found. Available workspaces: %s" % (workspaceName, workspaces))
        return ws_id

    def getWorkspaceTags(self, workspaceName):
        if self._syncTags == True:
            self.tags = []
            wsId = self.getWorkspaceID(workspaceName)
            url = r"https://www.toggl.com/api/v8/workspaces/%d/tags" % wsId
            req = self._request(url)
            if req.ok:
                self.tags = req.json()
            else:
                raise RuntimeError(
                    "Error getting toggl workspace tags, status code=%d, msg=%s" % (req.status_code, req.reason))
            self._syncTags = False

        return self.tags

    def getWorkspaceGroups(self, workspaceName):
        if self._syncGroups == True:
            self.groups = []
            wsId = self.getWorkspaceID(workspaceName)
            url = r"https://www.toggl.com/api/v8/workspaces/%d/groups" % wsId
            req = self._request(url)
            if req.ok:
                self.groups = req.json()
            else:
                raise RuntimeError(
                    "Error getting toggl workspace groups, status code=%d, msg=%s" % (req.status_code, req.reason))
            self._syncGroups = False

        return self.groups

    def getWorkspaceUsers(self, workspaceName):
        if self._syncUsers == True:
            wsId = self.getWorkspaceID(workspaceName)
            url = r"https://www.toggl.com/api/v8/workspaces/%d/users" % wsId
            req = self._request(url)
            if req.ok:
                self.users = req.json()
            else:
                raise RuntimeError(
                    "Error getting toggl workspace users, status code=%d, msg=%s" % (req.status_code, req.reason))
            self._syncUsers = False

        return self.users

    def getWorkspaceClients(self, workspaceName):
        if self._syncClients == True:
            wsId = self.getWorkspaceID(workspaceName)
            url = r"https://www.toggl.com/api/v8/workspaces/%d/clients" % wsId
            req = self._request(url)
            self.clients = req.json()
            self._syncClients = False

        return self.clients

    def getWorkspaceProjects(self, workspaceName):
        if self._syncProjects == True:
            wsId = self.getWorkspaceID(workspaceName)
            url = r"https://www.toggl.com/api/v8/workspaces/%d/projects" % wsId
            params = {"active": "both"}
            req = self._request(url, params=params)
            self.projects = req.json()
            self._syncProjects = False

            f = open("toggl_projects.json.old", "w")
            f.write(json.dumps(self.projects, indent=2))
            f.close()

        return self.projects

    def getWorkspaceTasks(self, workspaceName):
        if self._syncTasks == True:
            wsId = self.getWorkspaceID(workspaceName)
            url = r"https://www.toggl.com/api/v8/workspaces/%d/tasks" % wsId
            req = self._request(url)
            self.tasks = req.json()
            self._syncTasks = False

            f = open("toggl_tasks.json", "w")
            f.write(json.dumps(self.tasks, indent=2))
            f.close()

        return self.tasks

    def getReports(self, workspaceName, since, until, cb, timeZone="CET"):
        #        entries = []

        end = False
        nextStart = since
        while True:
            curStop = nextStart + datetime.timedelta(days=300)
            if curStop > until:
                curStop = until
                end = True

            self.logger.info("fetching entries from %s to %s" % (nextStart.isoformat(), curStop.isoformat()))
            self._getReports(workspaceName, nextStart, curStop, cb, timeZone=timeZone)
            if end:
                break

            cb(None, 0)

            nextStart = curStop

    #        return entries

    def _getReports(self, workspaceName, since, until, cb, timeZone="CET"):
        since = since.isoformat() + timeZone
        until = until.isoformat() + timeZone

        wsId = self.getWorkspaceID(workspaceName)
        curPage = 1
        #        entries = []

        numEntries = 0
        while True:
            params = {'user_agent': self.email, 'workspace_id': wsId, "since": since, "until": until, "page": curPage}
            reportUrl = "https://toggl.com/reports/api/v2/details"
            response = self._request(reportUrl, params=params)
            if response.status_code == 400:
                break

            curPage += 1

            jsonresp = response.json()

            data = jsonresp["data"]
            numEntries += len(data)
            totalCount = jsonresp["total_count"]
            if len(data) == 0:
                break
            else:
                cb(data, totalCount)
            #                entries += jsonresp["data"]

            self.logger.info("got %d from %d entries" % (numEntries, totalCount))

    #        return entries

    def getProjectID(self, projectName, workspaceName):
        pID = None
        prjs = self.getWorkspaceProjects(workspaceName)
        for p in prjs:
            if p["name"] == projectName:
                pID = p["id"]
        if pID == None:
            raise RuntimeError("project %s not found in workspace %s" % (projectName, workspaceName))
        return pID

    def getProjectUsers(self, projectName, workspaceName):
        prjId = self.getProjectID(projectName, workspaceName)
        url = "https://www.toggl.com/api/v8/projects/%d/project_users" % prjId
        response = self._request(url)
        return response.json()

    def getProjectGroups(self, projectName, workspaceName):
        prjId = self.getProjectID(projectName, workspaceName)
        url = "https://www.toggl.com/api/v8/projects/%d/project_groups" % prjId
        response = self._request(url)
        return response.json()

    def getClientName(self, clientID, workspace):
        clients = self.getWorkspaceClients(workspace)
        cName = None
        for c in clients:
            if c["id"] == clientID:
                cName = c["name"]
        if cName == None:
            raise RuntimeError("clientID %d not found in workspace %s" % (clientID, workspace))
        return cName

    def getUserName(self, userID, workspaceName):
        users = self.getWorkspaceUsers(workspaceName)
        uName = None
        for u in users:
            if u["id"] == userID:
                uName = u["fullname"]
        if uName == None:
            raise RuntimeError("userID %d not found in workspace %s" % (userID, workspaceName))
        return uName

    def getUserEmail(self, userID, workspaceName):
        users = self.getWorkspaceUsers(workspaceName)
        email = None
        for u in users:
            if u["id"] == userID:
                email = u["email"]
        if email == None:
            raise RuntimeError("userID %d (%s) not found in workspace %s" % (userID, email, workspaceName))
        return email
