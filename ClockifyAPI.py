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
import json

class RetVal(Enum):
    OK=0
    ERR=1
    EXISTS=2
    FORBIDDEN=3

class HourlyRate:
    def __init__(self, amount, currency="EUR"):
        self.rate = {}
        self.rate["amount"] = amount
        self.rate["currency"] = currency

class MemberShip:
    def __init__(self, api):
        self.connector = api
        self.memberShip = []
        self.workspace = ""
        
    def addMembership(self, userMail, projectName, workspace, 
                      membershipType="PROJECT", membershipStatus="ACTIVE",
                      hourlyRate=None, manager=False):
        self.workspace = workspace
        userID = self.connector.getUserIDByMail(userMail, workspace)
        #prjID = self.connector.getProjectID(projectName, workspace)
        
        membership = {}
        membership["membershipStatus"] = membershipStatus
        membership["membershipType"] = membershipType
        #membership["targetId"] = prjID
        membership["userId"] = userID
        membership["manager"] = manager
        if hourlyRate != None:
            membership["hourlyRate"] = hourlyRate.rate
        self.memberShip.append(membership)
        
    def getManagerUserMail(self):
        mail = ""
        for m in self.memberShip:
            if m["manager"] == True:
                mail = self.connector.getUserMailById(m["userId"], self.workspace)
                break
        return mail
        
    def getData(self):
        return self.memberShip


class ClockifyAPI:
    def __init__(self, apiToken, adminEmail="", reqTimeout=0.01):
        self.logger = logging.getLogger('toggl2clockify')
        self.url = 'https://clockify.me/api/v1'
        self._syncClients = True
        self._syncUsers = True
        self._syncProjects = True
        self._syncTags = True
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
                self._syncTags = True
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
        
        curUser = self._loadedUserEmail
        self._loadAdmin()
        
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
            
        self._loadUser(curUser)
            
        return rv
   
    def getClients(self, workspace):
        if self._syncClients == True:
            curUser = self._loadedUserEmail
            self._loadAdmin()
            
            wsId = self.getWorkspaceID(workspace)
            url = self.url + "/workspaces/%s/clients"%wsId
            rv = self._request(url, typ="GET")
            self.clients = rv.json()
            self._syncClients = False
            
            self._loadUser(curUser)
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

    def getProjects(self, workspace, skipPrjQuery=False):
        if self._syncProjects == True:
            curUser = self._loadedUserEmail
            self.projects = []
            
            for user in self._APIusers:
                self.logger.info("synchronizing clockify projects for user %s..."%user["email"])
                self._loadUser(user["email"])
                
                wsId = self.getWorkspaceID(workspace)
                url = self.url + "/workspaces/%s/projects"%wsId
                pg=1
                while True:
                    params = {"page": pg}
                    rv = self._request(url, body=params, typ="GET")
                    prj0ID = -1
                    if rv.ok:
                        prjs = rv.json()
                        self.logger.info("amount of projects: %d"%len(prjs))
                        for p in prjs:
                            curPIDs = [x["id"] for x in self.projects]
                            if p["id"] not in curPIDs:
                                self.projects.append(p)
                        if len(prjs) < 50:
                            break
                        if prj0ID == prjs[0]["id"]:
                            break
                        prj0ID = prjs[0]["id"]
                    else:
                        self.logger.error("Error requesting workspace projects, status code=%d, msg=%s"%(rv.status_code, rv.reason))
                        break
                    pg+=1
                   
            self.logger.info("finsihed synchronizing clockify projects, saving results")
            f = open("clockify_projects.json", "w")
            f.write(json.dumps(self.projects, indent=2))
            f.close()
            self._loadUser(curUser)
            self._syncProjects = False
            
#        print (self.projects)
        return self.projects

    def getProjectID(self, project, workspace, skipPrjQuery=False):
        pId = None
        if skipPrjQuery:
            projects = self.projects
        else:
            projects = self.getProjects(workspace, skipPrjQuery)
            
        for p in projects:
            if p["name"] == project:
                pId = p["id"]
        if pId == None:
            raise RuntimeError("Project %s not found in workspace %s"%(project, workspace))
        return pId

    def getUsers(self, workspace):
        if self._syncUsers == True:
            curUser = self._loadedUserEmail
            self._loadAdmin()            
            
            wsId = self.getWorkspaceID(workspace)
            url = self.url + "/workspace/%s/users"%wsId
            rv = self._request(url, typ="GET")
            self.users = rv.json()
            self._syncUsers = False
            
            self._loadUser(curUser)
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
    
    def getUserMailById(self, userID, workspace):
        mail = None
        users = self.getUsers(workspace)
        for u in users:
            if u["id"] == userID:
                mail = u["email"]
        if mail == None:
            raise RuntimeError("User ID %s not found in workspace %s"%(userID, workspace))
        return mail    
    
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
                   color="#f44336", memberships=None, hourlyRate=None, manager=""):
                   
        curUser = self._loadedUserEmail
        if manager == "":
            if isPublic == False:
                admin = self._adminEmail
                self.logger.warning("no manager found for project %s, making %s as manager"%(name, admin))
            self._loadAdmin()
        else:
            self._loadUser(manager)
                   
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
        elif rv.status_code == 403:
            rv = RetVal.FORBIDDEN
        else:
            self.logger.warning("Error adding project  %s, status code=%d, msg=%s"%(name, rv.status_code, rv.reason))
            rv = RetVal.ERR
        
        self._loadUser(curUser)
        
        return rv
    
    def getTags(self, workspace):
        if self._syncTags == True:
            curUser = self._loadedUserEmail
            self._loadAdmin()
            
            self.tags = []
            wsId = self.getWorkspaceID(workspace)
            url = self.url + "/workspaces/%s/tags"%wsId
            rv = self._request(url, typ="GET")
            if rv.ok:
                self.tags = rv.json()
            else:
                self.logger.error("Error requesting workspace tags, status code=%d, msg=%s"%(rv.status_code, rv.reason))
            self._syncTags = False
            
            self._loadUser(curUser)
        return self.tags
    
    def addTag(self, tagName, workspace):
        curUser = self._loadedUserEmail
        self._loadAdmin()
        
        wsId = self.getWorkspaceID(workspace)
        url = self.url + "/workspaces/%s/tags"%wsId
        params = {"name": tagName}
        rv = self._request(url, body=params, typ="POST")
        if rv.status_code == 201:
            self._syncTags = True
            rv = RetVal.OK
        elif rv.status_code == 400:
            rv = RetVal.EXISTS
        else:
            self.logger.warning("Error adding tag %s, status code=%d, msg=%s"%(tagName, rv.status_code, rv.reason))
            rv = RetVal.ERR
        
        self._loadUser(curUser)
        return rv
    
    def getTagName(self, tagID, workspace):
        tName = None
        tags = self.getTags(workspace)
        for t in tags:
            if t["id"] == tagID:
                tName = t["name"]
        if tName == None:
            raise RuntimeError("TagID %s not found in workspace %s"%(tagID, workspace))
        return tName
    
    def getTagID(self, tagName, workspace):
        tId = None
        tags = self.getTags(workspace)
        for t in tags:
            if t["name"] == tagName:
                tId = t["id"]
        if tId == None:
            raise RuntimeError("Tag %s not found in workspace %s"%(tagName, workspace))
        return tId
    
    def addEntry(self, start, description, projectName, userMail, workspace, 
                 timeZone="Z", end=None, billable=False, tagNames=None):
        rv = self._loadUser(userMail)
        data = None
        
        if rv == RetVal.OK:
            wsId = self.getWorkspaceID(workspace)
            url = self.url + "/workspaces/%s/time-entries"%wsId
            
            if projectName != None:
                projectId = self.getProjectID(projectName, workspace)
            else:
                self.logger.warning("no project in entry %s"%description)
            
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
            if tagNames != None:
                tagIDs = []
                for tag in tagNames:
                    tid = self.getTagID(tag, workspace)
                    tagIDs.append(tid)
                params["tagIds"] = tagIDs
                
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
#                            self.logger.info("entry diff @start: %s %s"%(str(params["start"]), str(d['timeInterval']["start"])))
                        if 'projectId' in params:
                            if params["projectId"] != d['projectId']:
                                anyDiff = True
#                                self.logger.info("entry diff @projectID: %s %s"%(str(params["projectId"]), str(d['projectId'])))
                        if params["description"] != d["description"]:
                            anyDiff = True
#                            self.logger.info("entry diff @desc: %s %s"%(str(params["description"]), str(d['description'])))
                        if self.userID != d["userId"]:
                            anyDiff = True
#                            self.logger.info("entry diff @userID: %s %s"%(str(self.userID), str(d['userId'])))
                        if tagNames != None:
                            tagIdsRcv = d["tagIds"]
                            tagNamesRcv = []
                            for tagID in tagIdsRcv:
                                tagNamesRcv.append(self.getTagName(tagID, workspace))
                            if set(tagNames) != set(tagNamesRcv):
#                                self.logger.info("entry diff @tagNames: %s %s"%(str(set(tagNames)), str(set(tagNamesRcv))))
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
    
    def archiveProject(self, projectName, workspace, skipPrjQuery=False):
        wsId = self.getWorkspaceID(workspace)
        pID = self.getProjectID(projectName, workspace, skipPrjQuery=skipPrjQuery)
        url = "https://api.clockify.me/api/workspaces/%s/projects/%s/archive"%(wsId, pID)
        rv = self._request(url, typ="GET")
        if rv.status_code == 200:
            rv = RetVal.OK
        else:
            self.logger.warning("Archiving project %s failed, status code=%d, msg=%s"%(projectName, rv.status_code, rv.reason))
            rv = RetVal.ERR
        
        return rv
    
    def deleteEntriesOfUser(self, userMail, workspace):
        while True:
            rv, entries = self.getTimeEntryForUser(userMail, workspace, "", None, None, "")
            numEntries = 0
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
            if numEntries == 0:
                break
        return numEntries
                    
    def deleteEntry(self, entryID, workspace):
        wsId = self.getWorkspaceID(workspace)
        url = self.url +"/workspaces/%s/time-entries/%s"%(wsId, entryID)
        rv = self._request(url, typ="DELETE")
        if rv.ok:
            return RetVal.OK
        else:
            self.logger.warning("Error deleteEntry, status code=%d, msg=%s"%(rv.status_code, rv.reason))
            return RetVal.ERR

    def deleteProject(self, projectName, workspace, skipPrjQuery=False):
        wsId = self.getWorkspaceID(workspace)
        projectID = self.getProjectID(projectName, workspace, skipPrjQuery)
        url = self.url +"/workspaces/%s/projects/%s"%(wsId, projectID)
        rv = self._request(url, typ="DELETE")
        if rv.ok:
            self._syncProjects = True
            return RetVal.OK
        else:
            self.logger.warning("Error deleteProjet, status code=%d, msg=%s"%(rv.status_code, rv.reason))
            return RetVal.ERR
        
    def deleteAllProjects(self, workspace):
        curUser = self._loadedUserEmail
        for user in self._APIusers:
            self._loadUser(user["email"])
            self.logger.info("Deleting all project from user %s"%user["email"])
            prjs = self.getProjects(workspace)
            idx = 0
            numProjects = len(prjs)
            for p in prjs:
                msg = "deleting project %s (%d of %d)"%(p["name"], idx+1, numProjects)
                self.logger.info(msg)
                self.deleteProject(p["name"], workspace, skipPrjQuery=True)
                idx+=1
        self._loadUser(curUser)
        
    def wipeOutWorkspace(self, workspace):
        curUser = self._loadedUserEmail
        for user in self._APIusers:
            self.logger.info("Deleting all entries from user %s"%user["email"])
            self.deleteEntriesOfUser(user["email"] ,workspace)
        
        self.deleteAllProjects(workspace)
#        self.deleteAllTags(workspace)
#        self.deleteAllClients(workspace)
        
        self._loadUser(curUser)

if __name__ == "__main__":
    formatter = logging.Formatter(fmt='%(asctime)s - %(levelname)s - %(module)s - %(message)s')
    
    handler = logging.StreamHandler()
    handler.setFormatter(formatter)
    logger = logging.getLogger("toggl2clockify")
    logger.setLevel(logging.DEBUG)
    if len(logger.handlers) == 0:
        logger.addHandler(handler)

    
    c = ClockifyAPI(["XMRIwBCA7DZVjRhc", "XMS4+xCA7DZVjTVy", "XMVR6xCA7DZVjUrb", "XMVmmxCA7DZVjU8L", "XMXO49J4rgxSDDgr"], "markus.proeller@pieye.org")
#    prj = c.getProjects("pieye workspace")
    c.wipeOutWorkspace("pieye workspace")
#    prjs = c.getProjects("pieye workspace")