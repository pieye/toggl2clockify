#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = "Markus Proeller"
__copyright__ = "Copyright 2019, pieye GmbH (www.pieye.org)"
__maintainer__ = "Markus Proeller"
__email__ = "markus.proeller@pieye.org"

import requests
import time
from enum import Enum
import logging

class RetVal(Enum):
    OK=0
    ERR=1
    EXISTS=2

class HourlyRate:
    def __init__(self, amount, currency="EUR"):
        self.rate = {}
        self.rate["amount"] = amount
        self.rate["currency"] = currency

class MemberShip:
    def __init__(self, api):
        self.connector = api
        self.memberShip = []
        
    def addMembership(self, userMail, projectName, workspace, 
                      membershipType="PROJECT", membershipStatus="ACTIVE",
                      hourlyRate=None):
        userID = self.connector.getUserIDByMail(userMail, workspace)
        #prjID = self.connector.getProjectID(projectName, workspace)
        
        membership = {}
        membership["membershipStatus"] = membershipStatus
        membership["membershipType"] = membershipType
        #membership["targetId"] = prjID
        membership["userId"] = userID
        if hourlyRate != None:
            membership["hourlyRate"] = hourlyRate.rate
        self.memberShip.append(membership)
        
    def getData(self):
        return self.memberShip


class ClockifyAPI:
    def __init__(self, apiToken, adminEmail="", reqTimeout=1):
        self.logger = logging.getLogger('toggl2clockify')
        self.url = 'https://clockify.me/api/v1'
        self._syncClients = True
        self._syncUsers = True
        self._syncProjects = True
        self._adminEmail = adminEmail
        self._reqTimeout = reqTimeout
        
        self._APIusers = []
        adminFound = False
        for token in apiToken:
            self.logger.info("testing clockify APIKey %s"%token)
            
            self.apiToken = token
            url = self.url + "/user"
            rv = self._request(url)
            if rv.status_code != 200:
                raise RuntimeError("error loading user")
                
            rv = rv.json()
            user = {}
            user["name"] = rv["name"]
            user["token"] = token
            user["email"] = rv["email"]
            user["id"] = rv["id"]
            self._APIusers.append(user)
            
            if rv["email"] == adminEmail:
                adminFound = True
            
            self.logger.info("...ok, key resolved to email %s"%rv["email"])
            
        if not adminFound:
            raise RuntimeError("admin mail address was given as %s but not found in clockify API tokens"%adminEmail)
            
        self._loadedUserEmail = None
        self._loadUser(self._APIusers[0]["email"])
        
        self._getWorkspaces()
        
    def _loadAdmin(self):
        return self._loadUser(self._adminEmail)
        
    def _loadUser(self, userMail):
        if userMail == self._loadedUserEmail:
            return  RetVal.OK
        
        userLoaded = False
        for user in self._APIusers:
            if user["email"] == userMail:
                self.apiToken = user["token"]
                self.email = user["email"]
                self.userID = user["id"]
                url = self.url + "/user"
                rv = self._request(url)
                if rv.status_code != 200:
                    raise RuntimeError("error loading user")
                userLoaded = True
                self._loadedUserEmail = user["email"]
                break
            
        if userLoaded == False:
            rv = RetVal.ERR
            self.logger.warning("user %s not found"%userMail)
        else:
            rv = RetVal.OK
            
        return rv
        
    def _request(self, url, body=None, typ="GET"):
        headers={
            'X-Api-Key': self.apiToken}
        if typ == "GET":
            response=requests.get(url,headers=headers, params=body)
        elif typ == "POST":
            response=requests.post(url,headers=headers, json=body)
        elif typ == "DELETE":
            response=requests.delete(url,headers=headers)
        else:
            raise RuntimeError("invalid request type %s"%typ)
        time.sleep(self._reqTimeout)
        return response
    
    def getWorkspaces(self):
        return self.workspaces
    
    def getWorkspaceID(self, workspaceName):
        wsId = None
        workspaces = self.getWorkspaces()
        for ws in workspaces:
            if ws["name"] == workspaceName:
                wsId = ws["id"]
        if wsId == None:
            raise RuntimeError("Workspace %s not found. Available workspaces: %s"%(workspaceName, workspaces))
        return wsId
    
    def _getWorkspaces(self):
        url = self.url + "/workspaces"
        rv = self._request(url)
        self.workspaces = rv.json()
        return self.workspaces
    
    def addClient(self, name, workspace):
        wsId = self.getWorkspaceID(workspace)
        url = self.url + "/workspaces/%s/clients"%wsId
        params = {"name":name}
        rv = self._request(url, body=params, typ="POST")
        
        if rv.ok == False:
            if rv.status_code == 400:
                rv = RetVal.EXISTS
            else:
                self.logger.warning("Error adding client %s, status code=%d, msg=%s"%(name, rv.status_code, rv.reason))
                rv = RetVal.ERR
        else:
            rv = RetVal.OK
        return rv
   
    def getClients(self, workspace):
        if self._syncClients == True:
            wsId = self.getWorkspaceID(workspace)
            url = self.url + "/workspaces/%s/clients"%wsId
            rv = self._request(url, typ="GET")
            self.clients = rv.json()
            self._syncClients = False
        return self.clients
    
    def getClientID(self, client, workspace):
        clId = None
        clients = self.getClients(workspace)
        for c in clients:
            if c["name"] == client:
                clId = c["id"]
        if clId == None:
            raise RuntimeError("Client %s not found in workspace %s"%(client, workspace))
        return clId

    def getProjects(self, workspace):
        if self._syncProjects == True:
            curUser = self._loadedUserEmail
            
            self._loadAdmin()
            wsId = self.getWorkspaceID(workspace)
            url = self.url + "/workspaces/%s/projects"%wsId
            self.projects = []
            pg=1
            params = {"page": pg}
            rv = self._request(url, body=params, typ="GET")
            if rv.ok:
                self.projects = rv.json()
            else:
                self.logger.error("Error requesting workspace projects, status code=%d, msg=%s"%(rv.status_code, rv.reason))
                
            self._syncProjects = False
            
            self._loadUser(curUser)
        return self.projects

    def getProjectID(self, project, workspace):
        pId = None
        projects = self.getProjects(workspace)
        for p in projects:
            if p["name"] == project:
                pId = p["id"]
        if pId == None:
#            for p in projects:
#                print (p["name"])
            raise RuntimeError("Project %s not found in workspace %s"%(project, workspace))
        return pId

    def getUsers(self, workspace):
        if self._syncUsers == True:
            wsId = self.getWorkspaceID(workspace)
            url = self.url + "/workspace/%s/users"%wsId
            rv = self._request(url, typ="GET")
            self.users = rv.json()
            self._syncUsers = False
        return self.users

    def getUserIDByName(self, user, workspace):
        uId = None
        users = self.getUsers(workspace)
        for u in users:
            if u["name"] == user:
                uId = u["id"]
        if uId == None:
            raise RuntimeError("User %s not found in workspace %s"%(user, workspace))
        return uId
    
    def getUserIDByMail(self, email, workspace):
        uId = None
        users = self.getUsers(workspace)
        for u in users:
            if u["email"] == email:
                uId = u["id"]
        if uId == None:
            raise RuntimeError("User %s not found in workspace %s"%(email, workspace))
        return uId    
    
    def addProject(self, name, client, workspace, isPublic=False, billable=False, 
                   color="#f44336", memberships=None, hourlyRate=None):
        wsId = self.getWorkspaceID(workspace)
        clId = self.getClientID(client, workspace)
        url = self.url + "/workspaces/%s/projects"%wsId
        params = {"name":name, "clientId": clId, "isPublic": isPublic, 
                  "billable": billable, "color": color}
        if memberships != None:
            params["memberships"] = memberships.getData()
        if hourlyRate != None:
            params["hourlyRate"] = hourlyRate.rate
        rv = self._request(url, body=params, typ="POST")
        if rv.status_code == 201:
            self._syncProjects = True
            rv = RetVal.OK
        elif rv.status_code == 400:
            rv = RetVal.EXISTS
        else:
            self.logger.warning("Error adding project  %s, status code=%d, msg=%s"%(name, rv.status_code, rv.reason))
            rv = RetVal.ERR
        return rv
    
    def addEntry(self, start, description, projectName, userMail, workspace, 
                 timeZone="Z", end=None, billable=False):
        rv = self._loadUser(userMail)
        data = None
        
        if rv == RetVal.OK:
            wsId = self.getWorkspaceID(workspace)
            url = self.url + "/workspaces/%s/time-entries"%wsId
            
            if projectName != None:
                projectId = self.getProjectID(projectName, workspace)
            
            startTime = start.isoformat()+timeZone
            if end != None:
                end = end.isoformat()+timeZone
            
            params = {
                          "start": startTime,
                          "billable":billable,
                          "description": description
                      }

            if projectName != None:
                params["projectId"] = projectId
            if end != None:
                params["end"] = end
                
            rv, entr = self.getTimeEntryForUser(userMail, workspace, description, projectName,
                                         start, timeZone=timeZone)
            
            if rv == RetVal.OK:
                if entr != []:
                    # filter data
                    filteredData = []
                    for d in entr:
                        anyDiff = False
                        if params["start"] != d['timeInterval']["start"]:
                            anyDiff = True
                        if 'projectId' in params:
                            if params["projectId"] != d['projectId']:
                                anyDiff = True
                        if params["description"] != d["description"]:
                            anyDiff = True
                        if self.userID != d["userId"]:
                            anyDiff = True
                        if anyDiff == False:
                            filteredData.append(d)
                    entr = filteredData
                
                if entr == []:
                    rv = self._request(url, body=params, typ="POST")
                    
                    if rv.ok:
                        data = rv.json()
                        rv = RetVal.OK
                    else:
                        self.logger.warning("Error adding time entrs, status code=%d, msg=%s"%(rv.status_code, rv.reason))
                        rv = RetVal.ERR
                else:
                    rv = RetVal.EXISTS
            else:
                rv = RetVal.ERR
            
        return rv, data
    
    def getTimeEntryForUser(self, userMail, workspace, description, 
                            projectName, start, timeZone="Z"):
        data = None
        rv = self._loadUser(userMail)
        
        if rv == RetVal.OK:
            wsId = self.getWorkspaceID(workspace)
            uId = self.userID
            
            if projectName != None:
                prjID = self.getProjectID(projectName, workspace)
            if start != None:
                start = start.isoformat()+timeZone
                
            url = self.url + "/workspaces/%s/user/%s/time-entries"%(wsId, uId)
            params = {"description": description}
            if start != None:
                params["start"] = start
            if projectName != None:
                params["project"] = prjID
            
            rv = self._request(url, body=params, typ="GET")
            if rv.ok:
                data = rv.json()
                rv = RetVal.OK
            else:
                self.logger.warning("Error getTimeEntryForUser, status code=%d, msg=%s"%(rv.status_code, rv.reason))
                rv = RetVal.ERR
            
        return rv, data
    
    def deleteEntriesOfUser(self, userMail, workspace):
        rv, entries = self.getTimeEntryForUser(userMail, workspace, "", None, None, "")
        
        if rv == RetVal.OK:
            curUser = self._loadedUserEmail
            rv = self._loadAdmin()
            if rv == RetVal.OK:
                numEntries = len(entries)
                idx = 0
                for e in entries:
                    msg = "deleting entry %d of %d"%(idx+1, numEntries)
                    self.logger.info(msg)
                    rv = self.deleteEntry(e["id"], workspace)
                    if rv == RetVal.OK:
                        self.logger.info("...ok")   
                    idx += 1
            self._loadUser(curUser)
                    
    def deleteEntry(self, entryID, workspace):
        wsId = self.getWorkspaceID(workspace)
        url = self.url +"/workspaces/%s/time-entries/%s"%(wsId, entryID)
        rv = self._request(url, typ="DELETE")
        if rv.ok:
            return RetVal.OK
        else:
            self.logger.warning("Error deleteEntry, status code=%d, msg=%s"%(rv.status_code, rv.reason))
            return RetVal.ERR