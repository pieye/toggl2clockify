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
    def __init__(self, apiToken, adminEmail="", reqTimeout=0.01, fallbackUserMail=None):
        self.logger = logging.getLogger('toggl2clockify')
        self.url = 'https://clockify.me/api/v1'
        self.urlWorking = 'https://api.clockify.me/api/v1'
        self._syncClients = True
        self._syncUsers = True
        self._syncProjects = True
        self._syncTags = True
        self._syncGroups = True
        self._syncTasks = True
        self._adminEmail = adminEmail
        self._reqTimeout = reqTimeout
        self.fallbackUserMail = fallbackUserMail
        
        self._APIusers = []
        adminFound = False
        fallbackFound = False
        for token in apiToken:
            self.logger.info("testing clockify APIKey %s"%token)
            
            self.apiToken = token
            url = self.url + "/user"
            rv = self._request(url)
            if rv.status_code != 200:
                raise RuntimeError("error loading user (API token %s), status code %s"%(token, str(rv.status_code)))
                
            rv = rv.json()
            user = {}
            user["name"] = rv["name"]
            user["token"] = token
            user["email"] = rv["email"]
            user["id"] = rv["id"]

            if (rv["status"].upper() != "ACTIVE") and (rv["status"].upper() != "PENDING_EMAIL_VERIFICATION"):
                raise RuntimeError("user '%s' is not an active user in clockify. Please activate the user for the migration process"%user["email"])
            
            self._APIusers.append(user)
            
            if rv["email"].lower() == adminEmail.lower():
                adminFound = True
                
            if self.fallbackUserMail != None:
                if rv["email"].lower() == self.fallbackUserMail.lower():
                    fallbackFound = True
            
            
            self.logger.info("...ok, key resolved to email %s"%rv["email"])
            
        if not adminFound:
            raise RuntimeError("admin mail address was given as %s but not found in clockify API tokens"%adminEmail)

        if fallbackFound==False and self.fallbackUserMail!=None:
            raise RuntimeError("falback user mail address was given as %s but not found in clockify API tokens"%self.fallbackUserMail)
            
        self._loadedUserEmail = None
        self._loadUser(self._APIusers[0]["email"])
        
        self._getWorkspaces()
        
    def _loadAdmin(self):
        return self._loadUser(self._adminEmail)
        
    def _loadUser(self, userMail):
        mailChk = self._loadedUserEmail
        if mailChk == None:
            mailChk = ""

        if userMail.lower() == mailChk.lower():
            return  RetVal.OK
        
        userLoaded = False
        for user in self._APIusers:
            if user["email"].lower() == userMail.lower():
                self.apiToken = user["token"]
                self.email = user["email"]
                self.userID = user["id"]
                url = self.url + "/user"
                rv = self._request(url)
                if rv.status_code != 200:
                    raise RuntimeError("error loading user %s, status code %s"%(user["email"], str(rv.status_code)))
                userLoaded = True
                self._loadedUserEmail = user["email"]
                break
            
        if userLoaded == False:
            rv = RetVal.ERR
            self.logger.warning("user %s not found"%userMail)
        else:
            rv = RetVal.OK
            
        return rv
    
    def multiGetRequest(self, url, idKey="id"):
        headers={
            'X-Api-Key': self.apiToken}
        
        curPage = 1
        rvData = []
        while True:
            body = {"page": curPage, "page-size": 50}
            rv = requests.get(url,headers=headers, params=body)
            if rv.status_code == 200:
                data = rv.json()
                if len(data) < 50:
                    rvData.extend(data)
                    break
                else:
                    #check if we got new data
                    chkID = data[0][idKey]
                    if not any(d[idKey] == chkID for d in rvData):
                        rvData.extend(data)
                    else:
                        break
                curPage += 1
            else:
                raise RuntimeError("get on url %s failed with status code %d"%(url, rv.status_code))
        return rvData
        
    def _request(self, url, body=None, typ="GET"):
        headers={'X-Api-Key': self.apiToken}
        if typ == "GET":
            response=requests.get(url,headers=headers, params=body)
        elif typ == "PUT":
            response=requests.put(url,headers=headers, json=body)
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
        if rv.status_code == 200:
            self.workspaces = rv.json()
        else:
            raise RuntimeError("Querying workspaces for user %s failed, status code=%d, msg=%s"%(self._APIusers[0]["email"], rv.status_code, rv.text))
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
            self._syncClients = True
            
        self._loadUser(curUser)
            
        return rv
    
    def getClients(self, workspace):
        if self._syncClients == True:
            curUser = self._loadedUserEmail
            self._loadAdmin()
            
            wsId = self.getWorkspaceID(workspace)
            url = self.url + "/workspaces/%s/clients"%wsId
            self.clients = self.multiGetRequest(url)
            self._syncClients = False
            
            self.logger.info("finished getting clockify clients, saving results to clockify_clients.json")
            f = open("clockify_clients.json", "w")
            f.write(json.dumps(self.clients, indent=2))
            f.close()            
            
            self._loadUser(curUser)
        return self.clients

    def getTasksFromProjectID(self, workspace, pId):
        curUser = self._loadedUserEmail
        self._loadAdmin()

        wsId = self.getWorkspaceID(workspace)

        url = self.url + "/workspaces/%s/projects/%s/tasks"%(wsId, pId)
        self.pTasks = self.multiGetRequest(url)
        
        self._loadUser(curUser)

        return self.pTasks
    
    def getTaskIdFromTasks(self, taskName, pTasks):
        tId = None
        if pTasks != None:
            for t in pTasks:
                if t["name"] == taskName:
                    tId = t["id"]
        if tId is None:
            raise RuntimeError("Task %s not found."%(taskName))
        return tId
    
    def getClientName(self, clientID, workspace, skipCliQuery=False, nullOK=False):
        clientName = None
        if skipCliQuery:
            clients = self.clients
        else:
            clients = self.getClients(workspace)
            
        for c in clients:
            if c["id"] == clientID:
                clientName = c["name"]

        if clientName is None:
            if nullOK:
                clientName = ""
            else:
                raise RuntimeError("Client %s not found in workspace %s" % (clientID, workspace))

        return clientName

    def getClientID(self, clientName, workspace, skipCliQuery=False):
        clId = None
        if skipCliQuery:
            clients = self.clients
        else:
            clients = self.getClients(workspace)
            
        for c in clients:
            if c["name"] == clientName:
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
                projects = self.multiGetRequest(url)
                self.projects.extend(projects)
                   
            self.logger.info("finished synchronizing clockify projects, saving results to clockify_projects.json")
            f = open("clockify_projects.json", "w")
            f.write(json.dumps(self.projects, indent=2))
            f.close()
            self._loadUser(curUser)
            self._syncProjects = False
            
        return self.projects

    #using Working API entry point
    def getWorkspaceProjects(self, workspace, skipPrjQuery=False):
        if self._syncProjects == True:
            curUser = self._loadedUserEmail

            if skipPrjQuery:
                projects = self.projects
            else:
                self.projects = []
                
                wsId = self.getWorkspaceID(workspace)
                url = self.urlWorking + "/workspaces/%s/projects"%wsId

                self.projects = self.multiGetRequest(url)
                self._syncProjects = False
                
                self.logger.info("Finished getting clockify projects, saving results to clockify_projects.json")
                f = open("clockify_projects.json", "w")
                f.write(json.dumps(self.projects, indent=2))
                f.close()
            
            self._loadUser(curUser)

        return self.projects

    def getProjectID(self, project, client, workspace, skipPrjQuery=False):
        result = None
        if skipPrjQuery:
            projects = self.projects
        else:
            projects = self.getProjects(workspace, skipPrjQuery)
            
        if client: 
            clientID = self.getClientID(client)
        else:
            clientID = None

        #find first project (no client)
        #find perfect match project (client + project match)
        for p in projects:
            if p["name"] == project and p["clientId"] == clientID:
                result = p["id"]
                break
                                   
        if result == None:
            raise RuntimeError("Project %s with client %s not found in workspace %s" %
                               (project, client, workspace))
        return result

    def getUsers(self, workspace):
        if self._syncUsers == True:
            curUser = self._loadedUserEmail
            self._loadAdmin()            
            
            wsId = self.getWorkspaceID(workspace)
            url = self.url + "/workspace/%s/users"%wsId
            rv = self._request(url, typ="GET")
            self.users = rv.json()
            self._syncUsers = False
            
            self.logger.info("finsihed getting clockify users, saving results to clockify_users.json")
            f = open("clockify_users.json", "w")
            f.write(json.dumps(self.users, indent=2))
            f.close()            
            
            self._loadUser(curUser)
        return self.users
    
    def getUsersInProject(self, wsId, pId):
        userIds = []
        url = self.urlWorking + "/workspaces/%s/projects/%s/users"%(wsId, pId)

        rv = self._request(url, typ="GET")
        userIds = rv.json()
        self.logger.info("Finished getting users already assigned to the project.")

        return userIds

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
        clId = None
        if not client is None:
            clId = self.getClientID(client, workspace)
        url = self.url + "/workspaces/%s/projects"%wsId
        params = {"name":name, "isPublic": isPublic,
                  "billable": billable, "color": color}
        if not clId is None:
            params["clientId"] = clId

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

    #using Working API entry point
    def addGroupsToProject(self, wsName, wsId, pId, wsGroupIds, pGroups):

        # API fields to POST: {userIds = [], userGroupIds = []}
        # From: https://clockify.github.io/clockify_api_docs/#operation--workspaces--workspaceId--projects--projectId--team-post

        url = self.urlWorking + "/workspaces/%s/projects/%s/team"%(wsId,pId)

        userIds = []
        userGroupIds = []

        pUsers = self.getUsersInProject(wsId, pId)

        if pUsers == None:
            userIds = []
        else:
            for pUser in pUsers:
                # try for errors?
                userIds.append(pUser["id"])

        for pGroup in pGroups:
            try:
                pg = wsGroupIds.index(pGroup["group_id"])
            except Exception as e:
                self.logger.warning ("Group id %d not found in toggl workspace, msg=%s"%(pGroup["group_id"] ,str(e)))
                break
        
        for pGroup in pGroups:
            # try for errors?
            gId = self.getUserGroupID(pGroup["name"],wsName)
            userGroupIds.append(gId)
        
        params = {"userIds": userIds, 
                  "userGroupIds": userGroupIds }
        
        rv = self._request(url, body=params, typ="POST")
        if (rv.status_code == 201) or (rv.status_code == 200):
            rv = RetVal.OK
        elif rv.status_code == 400:
            rv = RetVal.EXISTS
        elif rv.status_code == 403:
            rv = RetVal.FORBIDDEN
        else:
            self.logger.warning("Error adding Groups to Project, status code=%d, msg=%s"%(rv.status_code, rv.reason))
            rv = RetVal.ERR
        
        return rv
    
    # using Working API entry point
    def getUserGroups(self, workspace):
        if self._syncGroups == True:
            curUser = self._loadedUserEmail
            self._loadAdmin()
            
            self.userGroups = []
            wsId = self.getWorkspaceID(workspace)
            url = self.urlWorking + "/workspaces/%s/userGroups"%wsId
            self.userGroups = self.multiGetRequest(url)
            self._syncGroups = False
            
            self.logger.info("Finished getting clockify groups, saving results to clockify_groups.json")
            f = open("clockify_groups.json", "w")
            f.write(json.dumps(self.userGroups, indent=2))
            f.close()
            
            self._loadUser(curUser)
        return self.userGroups
    
    #using Working API entry point
    def addUserGroup(self, groupName, workspace):
        curUser = self._loadedUserEmail
        self._loadAdmin()
        
        wsId = self.getWorkspaceID(workspace)
        url = self.urlWorking + "/workspaces/%s/userGroups/"%wsId
        params = {"name": groupName}
        rv = self._request(url, body=params, typ="POST")
        if rv.status_code == 201:
            self._syncGroups = True
            rv = RetVal.OK
        elif rv.status_code == 400:
            rv = RetVal.EXISTS
        else:
            self.logger.warning("Error adding group %s, status code=%d, msg=%s"%(groupName, rv.status_code, rv.reason))
            rv = RetVal.ERR
        
        self._loadUser(curUser)
        return rv

    def getUserGroupName(self, userGroupID, workspace):
        uName = None
        userGroups = self.getUserGroups(workspace)
        for u in userGroups:
            if u["id"] == userGroupID:
                uName = u["name"]
        if uName == None:
            raise RuntimeError("User Group %s not found in workspace %s"%(userGroupID, workspace))
        return uName
    
    def getUserGroupID(self, userGroupName, workspace):
        uId = None
        userGroups = self.getUserGroups(workspace)
        for u in userGroups:
            if u["name"] == userGroupName:
                uId = u["id"]
        if uId == None:
            raise RuntimeError("User Group %s not found in workspace %s"%(userGroupName, workspace))
        return uId
    
    def getTags(self, workspace):
        if self._syncTags == True:
            curUser = self._loadedUserEmail
            self._loadAdmin()
            
            self.tags = []
            wsId = self.getWorkspaceID(workspace)
            url = self.url + "/workspaces/%s/tags"%wsId
            self.tags = self.multiGetRequest(url)
            self._syncTags = False
            
            self.logger.info("Finished getting clockify tags, saving results to clockify_tags.json")
            f = open("clockify_tags.json", "w")
            f.write(json.dumps(self.tags, indent=2))
            f.close()
            
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
    
    def addTask(self, wsId, name, projectId, estimate):
        curUser = self._loadedUserEmail
        self._loadAdmin()
        
        #wsId = self.getWorkspaceID(workspace)
        url = self.url + "/workspaces/%s/projects/%s/tasks/"%(wsId, projectId)
        params = {
            "name": name,
            "projectId": projectId,
            "estimate": estimate
        }
        rv = self._request(url, body=params, typ="POST")
        if rv.status_code == 201:
            self._syncTasks = True
            rv = RetVal.OK
        elif rv.status_code == 400:
            rv = RetVal.EXISTS
        else:
            self.logger.warning("Error adding task %s, status code=%d, msg=%s"%(name, rv.status_code, rv.reason))
            rv = RetVal.ERR
        
        self._loadUser(curUser)
        return rv

    def addEntry(self, start, description, projectName, clientName, userMail, workspace, 
                 timeZone="Z", end=None, billable=False, tagNames=None, taskName=None):
        rv = self._loadUser(userMail)
        data = None
        
        if rv == RetVal.OK:
            wsId = self.getWorkspaceID(workspace)
            url = self.url + "/workspaces/%s/time-entries"%wsId
            
            if projectName != None:
                projectId = self.getProjectID(projectName, clientName, workspace)
                if taskName != None:
                    pTasks = self.getTasksFromProjectID(workspace, projectId)
                    taskId = self.getTaskIdFromTasks(taskName, pTasks)                   
                    self.logger.info("Found task %s in project %s"%(taskName, projectName))
                else:
                    taskId = None
            else:
                taskId = None
                self.logger.info("no project in entry %s"%description)
            
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
            if taskId != None:
                params["taskId"] = taskId
            if end != None:
                params["end"] = end
            else:
                params["end"] = startTime
            if tagNames != None:
                tagIDs = []
                for tag in tagNames:
                    tid = self.getTagID(tag, workspace)
                    tagIDs.append(tid)
                params["tagIds"] = tagIDs            

            rv, entr = self.getTimeEntryForUser(userMail, workspace, description, projectName, clientName,
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
                            tagIdsRcv = tagIdsRcv if tagIdsRcv != None else []
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
                    self.logger.info("Adding entry: %s"%(json.dumps(params, indent=2)))                
                    
                    if rv.ok:
                        data = rv.json()
                        rv = RetVal.OK
                    else:
                        self.logger.warning("Error adding time entrs, status code=%d, msg=%s"%(rv.status_code, rv.text))
                        rv = RetVal.ERR
                else:
                    rv = RetVal.EXISTS
            else:
                rv = RetVal.ERR
            
        return rv, data
    
    def getTimeEntryForUser(self, userMail, workspace, description, 
                            projectName, clientName, start, timeZone="Z", ):
        data = None
        rv = self._loadUser(userMail)
        
        if rv == RetVal.OK:
            wsId = self.getWorkspaceID(workspace)
            uId = self.userID
            
            if projectName != None and clientName != None:
                prjID = self.getProjectID(projectName, clientName, workspace)
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
    
    def archiveProject(self, projectName, clientName, workspace, skipPrjQuery=False):
        wsId = self.getWorkspaceID(workspace)
        pID = self.getProjectID(projectName, clientName, workspace, skipPrjQuery=skipPrjQuery)
        url = self.urlWorking + "/workspaces/%s/projects/%s/archive"%(wsId, pID)
        rv = self._request(url, typ="GET")
        if rv.status_code == 200:
            rv = RetVal.OK
        else:
            self.logger.warning("Archiving project %s failed, status code=%d, msg=%s"%(projectName, rv.status_code, rv.reason))
            rv = RetVal.ERR
        
        return rv
    
    def deleteEntriesOfUser(self, userMail, workspace):
        while True:
            rv, entries = self.getTimeEntryForUser(userMail, workspace, "", None, None, None, "")
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

    
    def deleteProject(self, project):
        # We have to archive before deletion.
        projectID = project["id"]
        wsId = project["workspaceId"]
        self.logger.info("Archiving project before deletion (this is required by the API):")
        project["archived"] = True
        url = self.urlWorking +"/workspaces/%s/projects/%s" % (wsId, projectID)
        rv = self._request(url, body=project, typ="PUT")
        if not rv.ok:
            self.logger.warning("Error archiveProject, status code=%d, msg=%s"%(rv.status_code, rv.reason))
            return RetVal.ERR
        
        # Now we can delete.
        url = self.urlWorking +"/workspaces/%s/projects/%s" % (wsId, projectID)
        rv = self._request(url, typ="DELETE")
        if rv.ok:
            self._syncProjects = True
            return RetVal.OK
        else:
            self.logger.warning("Error deleteProject, status code=%d, msg=%s"%(rv.status_code, rv.reason))
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

                clientName = self.getClientName(p["clientId"], workspace, nullOK=True)
                
                msg = "deleting project %s (%d of %d)"%(p["name"] + "|" + clientName, idx+1, numProjects)
                self.logger.info(msg)
                self.deleteProject(p)
                idx+=1
        self._loadUser(curUser)
        
    def wipeOutWorkspace(self, workspace):
        curUser = self._loadedUserEmail
        for user in self._APIusers:
            self.logger.info("Deleting all entries from user %s"%user["email"])
            self.deleteEntriesOfUser(user["email"] ,workspace)
        
        self.deleteAllProjects(workspace)
        self.deleteAllClients(workspace)
        self._loadUser(curUser)

    def deleteClient(self, clId, wsId):
        url = self.urlWorking + "/workspaces/%s/clients/%s" % (wsId, clId)
        rv = self._request(url, typ="DELETE")
        if rv.ok:
            self._syncClients = True
            return RetVal.OK
        else:
            self.logger.warning("Error deleteClient, status code=%d, msg=%s"%(rv.status_code, rv.reason))
            return RetVal.ERR
        
    def deleteAllClients(self, workspace):
        curUser = self._loadedUserEmail
        for user in self._APIusers:
            self._loadUser(user["email"])
            self.logger.info("Deleting all clients from user %s"%user["email"])
            clis = self.getClients(workspace)
            idx = 0
            numClients = len(clis)
            for c in clis:
                msg = "deleting client %s (%d of %d)"%(c["name"], idx+1, numClients)
                self.logger.info(msg)
                self.deleteClient(c["id"], c["workspaceId"])
                idx+=1
        self._loadUser(curUser)