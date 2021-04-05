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

        response=self._request(self.url)
        if response.status_code!=200:
            raise RuntimeError("Login failed. Check your API key")
            
        response=response.json()
        self.email=response['data']['email']
        self._get_workspaces()
        self._syncProjects = True
        self._syncClients = True
        self._syncUsers = True
        self._syncTags = True
        self._syncGroups = True
        self._syncTasks = True
        
    def _request(self, url, params=None):
        string=self.apiToken+':api_token'
        headers={
            'Authorization':'Basic '+base64.b64encode(string.encode('ascii')).decode("utf-8")}
        response=requests.get(url,headers=headers, params=params)
        time.sleep(1)
        return response
        
    def _get_workspaces(self):
        response=self._request(self.url)
        response=response.json()
        self.workspace_ids_names=[{'name':item['name'],'id':item['id']} for item in response['data']['workspaces'] if item['admin']==True]
    
    def get_workspaces(self):
        return self.workspace_ids_names
    
    def get_workspace_id(self, workspace_name):
        ws_id = None
        workspaces = self.get_workspaces()
        for ws in workspaces:
            if ws["name"] == workspace_name:
                ws_id = ws["id"]
        if ws_id == None:
            raise RuntimeError("Workspace %s not found. Available workspaces: %s"%(workspace_name, workspaces))
        return ws_id
    
    def get_tags(self, workspace_name):
        if self._syncTags:
            self.tags = []
            wsId = self.get_workspace_id(workspace_name)       
            url = r"https://www.toggl.com/api/v8/workspaces/%d/tags"%wsId
            req = self._request(url)
            if req.ok:
                self.tags = req.json()
                if self.tags is None:
                    self.tags = []
            else:
                raise RuntimeError("Error getting toggl workspace tags, status code=%d, msg=%s"%(req.status_code, req.reason))
            self._syncTags = False
        
        return self.tags
    
    def get_groups(self, workspace_name):
        if self._syncGroups:
            self.groups = []
            wsId = self.get_workspace_id(workspace_name)       
            url = r"https://www.toggl.com/api/v8/workspaces/%d/groups"%wsId
            req = self._request(url)
            if req.ok:
                self.groups = req.json()
            else:
                raise RuntimeError("Error getting toggl workspace groups, status code=%d, msg=%s"%(req.status_code, req.reason))
            self._syncGroups = False
        
        return self.groups

    def get_users(self, workspace_name):
        if self._syncUsers:
            wsId = self.get_workspace_id(workspace_name)       
            url = r"https://www.toggl.com/api/v8/workspaces/%d/users"%wsId
            req = self._request(url)
            if req.ok:
                self.users = req.json()
            else:
                raise RuntimeError("Error getting toggl workspace users, status code=%d, msg=%s"%(req.status_code, req.reason))
            self._syncUsers = False
        
        return self.users
    
    def get_clients(self, workspace_name):
        if self._syncClients:
            wsId = self.get_workspace_id(workspace_name)
            url = r"https://www.toggl.com/api/v8/workspaces/%d/clients"%wsId
            req = self._request(url)
            self.clients = req.json()
            if self.clients is None:
                self.clients = []
            self._syncClients = False
        
            self.dump_json("toggl_clients.json", self.clients)
            

        return self.clients
    
    def get_projects(self, workspace_name):
        if self._syncProjects:
            wsId = self.get_workspace_id(workspace_name)       
            url = r"https://www.toggl.com/api/v8/workspaces/%d/projects"%wsId
            params = {"active": "both"}
            req = self._request(url, params=params)
            self.projects = req.json()
            self._syncProjects = False
            
            self.dump_json("toggl_projects.json", self.projects)
        
        return self.projects

    def get_tasks(self, workspace_name):
        if self._syncTasks:
            wsId = self.get_workspace_id(workspace_name)
            url = r"https://www.toggl.com/api/v8/workspaces/%d/tasks"%wsId
            req = self._request(url)
            self.tasks = req.json()
            self._syncTasks = False

            self.dump_json("toggl_tasks.json", self.tasks)

        return self.tasks
    
    def dump_json(self, file_name, data):
        with open(file_name, "w") as file:
            file.write(json.dumps(data, indent=2))

    def get_reports(self, workspace_name, since, until, cb, time_zone="CET"):
        end = False
        nextStart = since
        while True:
            curStop = nextStart + datetime.timedelta(days=300)
            if curStop > until:
                curStop = until
                end = True
            
            self.logger.info ("fetching entries from %s to %s"%(nextStart.isoformat(), curStop.isoformat()))
            self._getReports(workspace_name, nextStart, curStop, cb, timeZone=time_zone)
            if end:
                break
            
            cb(None, 0)
            
            nextStart = curStop

    
    def _getReports(self, workspaceName, since, until, cb, timeZone="CET"):
        since = since.isoformat()+timeZone
        until = until.isoformat()+timeZone

        wsId = self.get_workspace_id(workspaceName)
        curPage = 1
        
        numEntries = 0
        while True:
            params={'user_agent':self.email,'workspace_id':wsId,"since":since,"until":until, "page":curPage}
            reportUrl = "https://toggl.com/reports/api/v2/details"
            response=self._request(reportUrl, params=params)
            if response.status_code == 400:
                break
            
            curPage+=1
            
            jsonresp = response.json()
            
            data = jsonresp["data"]
            numEntries += len(data)
            totalCount = jsonresp["total_count"]
            if len(data) == 0:
                break
            else:
                cb(data, totalCount)
                
            self.logger.info ("Received %d out of %d entries" % (numEntries, totalCount))
    
    def get_project_id(self, project_name, workspace_name):
        pID = None
        prjs = self.get_projects(workspace_name)
        for p in prjs:
            if p["name"] == project_name:
                pID = p["id"]
        if pID == None:
            raise RuntimeError("project %s not found in workspace %s"%(project_name, workspace_name))
        return pID
    
    def get_project_users(self, project_name, workspace_name):
        prjId = self.get_project_id(project_name, workspace_name)
        url = "https://www.toggl.com/api/v8/projects/%d/project_users"%prjId
        response=self._request(url)
        return response.json()
    
    def get_project_groups(self, project_name, workspace_name):
        prjId = self.get_project_id(project_name, workspace_name)
        url = "https://www.toggl.com/api/v8/projects/%d/project_groups"%prjId
        response=self._request(url)
        return response.json()

    def get_client_name(self, client_id, workspace, null_ok=False):
        clients = self.get_clients(workspace)
        cName = None
        for c in clients:
            if c["id"] == client_id:
                cName = c["name"]
        if cName == None:
            if null_ok:
                return ""
            else:
                raise RuntimeError("clientID %d not found in workspace %s"%(client_id, workspace))       
        return cName
    
    def get_username(self, user_id, workspace_name):
        users = self.get_users(workspace_name)
        uName = None
        for u in users:
            if u["id"] == user_id:
                uName = u["fullname"]
        if uName == None:
            raise RuntimeError("userID %d not found in workspace %s"%(user_id, workspace_name))
        return uName

    def get_user_email(self, user_id, workspace_name):
        users = self.get_users(workspace_name)
        email = None
        for u in users:
            if u["id"] == user_id:
                email = u["email"]
        if email == None:
            raise RuntimeError("userID %d (%s) not found in workspace %s"%(user_id, email, workspace_name))
        return email
