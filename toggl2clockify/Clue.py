#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = "Markus Proeller"
__copyright__ = "Copyright 2019, pieye GmbH (www.pieye.org)"
__maintainer__ = "Markus Proeller"
__email__ = "markus.proeller@pieye.org"

from toggl2clockify import TogglAPI
from toggl2clockify import ClockifyAPI
import dateutil.parser
import pytz
import datetime
import logging
import sys
import json

class Clue:
    def __init__(self, clockifyKey, clockifyAdmin, togglKey, fallbackUserMail):
        self.logger = logging.getLogger('toggl2clockify')
        
        self.logger.info("testing toggl API key %s"%togglKey)
        try:
            self.toggl = TogglAPI.TogglAPI(togglKey)
            self.logger.info("...ok, togglKey resolved to email %s"%self.toggl.email)
        except Exception as e:
            self.logger.error("something went wrong with your toggl key, msg=%s"%str(e))
            raise
        
        self.clockify = ClockifyAPI.ClockifyAPI(clockifyKey, clockifyAdmin, fallbackUserMail)
        
    def syncTags(self, workspace):
        tags = self.toggl.getWorkspaceTags(workspace)
        numTags = len(tags)
        numOk = 0
        numSkips = 0
        numErr = 0
        idx = 0
        for t in tags:
            self.logger.info("adding tag %s (%d of %d tags)"%(t["name"], idx+1, numTags))            
            rv = self.clockify.addTag(t["name"], workspace)
            if rv == ClockifyAPI.RetVal.EXISTS:
                self.logger.info("tag %s already exists, skip..."%t["name"])
                numSkips+=1
            elif rv == ClockifyAPI.RetVal.OK:
                numOk+=1
            else:
                numErr+=1
            idx+=1
            
        return numTags, numOk, numSkips, numErr
        
    def syncGroups(self, workspace):
        groups = self.toggl.getWorkspaceGroups(workspace)
        if groups == None:
            groups = []

        numGroups = len(groups)
        numOk = 0
        numSkips = 0
        numErr = 0
        idx = 0
        for t in groups:
            self.logger.info("adding group %s (%d of %d groups)"%(t["name"], idx+1, numGroups))
                                   
            rv = self.clockify.addUserGroup(t["name"], workspace)
            if rv == ClockifyAPI.RetVal.EXISTS:
                self.logger.info("User Group %s already exists, skip..."%t["name"])
                numSkips+=1
            else:
                numErr+=1
            idx+=1
            
        return numGroups, numOk, numSkips, numErr

    def syncClients(self, workspace):
        clients = self.toggl.getWorkspaceClients(workspace)
        
        idx = 0
        compl = len(clients)
        numOk = 0
        numSkips = 0
        numErr = 0
        
        for cli in clients:
            self.logger.info("adding client %s (%d of %d clients)"%(cli["name"], idx+1, compl))            
            rv = self.clockify.addClient(cli["name"], workspace)
            if rv == ClockifyAPI.RetVal.EXISTS:
                self.logger.info("client %s already exists, skip..."%cli["name"])
                numSkips+=1
            elif rv == ClockifyAPI.RetVal.OK:
                numOk+=1
            else:
                numErr+=1
            idx+=1
            
        return compl, numOk, numSkips, numErr

    # does not sync user assignments!
    def syncTasks(self, workspace):
        tasks = self.toggl.getWorkspaceTasks(workspace)
        if tasks == None:
            tasks = []
        wsId = self.clockify.getWorkspaceID(workspace)
        
        idx = 0
        compl = len(tasks)
        numOk = 0
        numSkips = 0
        numErr = 0
     
        tProjs = self.toggl.projects
        cProjs = self.clockify.projects 

        self.logger.info("Number of Toggl projects found: %s"%(len(tProjs)))
        self.logger.info("Number of Clockify projects found: %s"%(len(cProjs)))

        for task in tasks:
            self.logger.info("Adding tasks %s (%d of %d tasks)..."%(task["name"], idx+1, compl))

            # Find which Clockify project should the task be assigned to:
            projectId = None
            for tProj in tProjs:
                if task["pid"] == tProj["id"]:
                    projectName = tProj["name"]
                    for cProj in cProjs:
                        if cProj["name"] == projectName:
                            projectId = cProj["id"]
                            self.logger.info("Clockify project ID found: %s, for project %s"%(projectId, projectName))

            # Convert Toggl duration (seconds) into Clockify "Estimate" string (e.g. PT1H30M15S):
            time = task["estimated_seconds"]
            if time > 0:
                hours = time // (3600)
                concatH = True if (hours > 0) else False
                time = time % (3600)
                minutes = time // (60)
                concatM = True if (minutes > 0) or (concatH) else False
                time = time % (60)
                seconds = time
                estimatedTime = "PT" + ["", "%dH"%hours][concatH] + ["", "%dM"%minutes][concatM] +"%dS"%seconds
                self.logger.info("Estimate time: %s"%estimatedTime)
            else:
                estimatedTime = None;

            # Add the task to Clockify:
            rv = self.clockify.addTask(wsId, task["name"], clockify_pid, estimatedTime)

            if rv == ClockifyAPI.RetVal.EXISTS:
                self.logger.info("task %s already exists, skip..."%task["name"])
                numSkips+=1
            elif rv == ClockifyAPI.RetVal.OK:
                numOk+=1
                self.logger.info(" ... done.")
            else:
                numErr+=1
            idx+=1
            
        return compl, numOk, numSkips, numErr
            
    def syncProjects(self, workspace):
        prjs = self.toggl.getWorkspaceProjects(workspace)
        self.logger.info("Number of total Projects in Toggl: %d"%(len(prjs)))

        # getWorkspaceProjects() uses Clockify's Working API entry point, which gets all Projects without iterating all users, much quicker
        clockifyPrjs = self.clockify.getWorkspaceProjects(workspace)

        clockifyPrjNames = {cPrj["name"] for cPrj in clockifyPrjs}

        # Check if it's the first run (cPrjs = 0)
        # Get only new projects on Toggl to update in Clockify
        if len(clockifyPrjs) >= 1:
            updTPrjs = [tPrj for tPrj in prjs if tPrj["name"] not in clockifyPrjNames]
            self.logger.info("Found projects in Clockify, skipping matching ones in Toggl:")
            for updTPrj in updTPrjs:
                self.logger.info("Found different Project: %s"%updTPrj["name"])
            prjs = updTPrjs

        self.logger.info("Number of new Projects in Toggl: %d"%(len(prjs)))
        self.logger.info(" Number of total Projects in Clockify: %d, begin sync:"%(len(clockifyPrjs)))

        wsId = self.clockify.getWorkspaceID(workspace)

        # Load all Workspace Groups in simple array
        wgroups = self.toggl.getWorkspaceGroups(workspace)
        if wgroups == None:
            wgroups = []
        
        wgroupIds = []
        for wgroup in wgroups:
            wgroupIds.append(wgroup["id"])
        
        idx = 0
        numPrjs = len(prjs)
        numOk = 0
        numSkips = 0
        numErr = 0

        for p in prjs:
            clientName = ""
            if "cid" in p:
                clientName = self.toggl.getClientName(p["cid"], workspace, nullOK=True)
            self.logger.info ("Adding project %s (%d of %d projects)" % (p["name"] + "|" + clientName, idx+1, numPrjs))

            # Prepare Group assignment to Projects
            pgroups = self.toggl.getProjectGroups(p["name"], workspace)
            #self.logger.info(" Groups assigned in Toggl: %s"%pgroups)

            if pgroups == None:
                pgroups = []
                wgroupIds = []
            else:              
                # Add group name to toggl Groups array
                for pgroup in pgroups:
                    for wgroup in wgroups:
                        if pgroup["group_id"] == wgroup["id"]:
                            pgroup["name"] = wgroup["name"]

            name = p["name"]
            
            if name not in clockifyPrjNames:
                err = False
                
                isPublic = not p["is_private"]
                billable = p["billable"]
                color = p["hex_color"]
                members = self.toggl.getProjectUsers(p["name"], workspace)
                if members == None:
                    members = []

                m = ClockifyAPI.MemberShip(self.clockify)
                for member in members:
                    try:
                        userMail = self.toggl.getUserEmail(member["uid"], workspace)
                    except Exception as e:
                        self.logger.warning ("user id %d not found in toggl workspace, msg=%s"%(member["uid"] ,str(e)))
                        err = True
                        break
                        
                    try:
                        manager = False
                        if member["manager"] == True:
                            manager = True
                        m.addMembership(userMail, p["name"], workspace, 
                          membershipType="PROJECT", membershipStatus="ACTIVE",
                          hourlyRate=None,manager=manager)
                    except Exception as e:
                        self.logger.warning ("error adding user %s to clockify project, msg=%s"%(userMail, str(e)))
                        err = True
                        break
    
                if err == False:

                    rv = self.clockify.addProject(name, clientName, workspace, isPublic, billable, 
                           color, memberships=m, manager=m.getManagerUserMail())
                    if (rv == ClockifyAPI.RetVal.OK) and (pgroups == []):
                        self.logger.info(" ...ok, done.")
                        numOk+=1
                    if (rv == ClockifyAPI.RetVal.OK) and (pgroups != []):
                        self.logger.info(" ...ok, now processing User Group assignments:")
                        #try?
                        self.clockify.addGroupsToProject(workspace, wsId, pId, wgroupIds, pgroups)
                        self.logger.info(" ...ok, done.")
                        numOk+=1
                    elif rv == ClockifyAPI.RetVal.EXISTS:
                        self.logger.info("... project %s already exists, skip..."%name)
                        numSkips+=1
                    elif rv == ClockifyAPI.RetVal.FORBIDDEN:
                        manager = m.getManagerUserMail()
                        self.logger.error(" Could not add project %s. %s was project admin in toggl, but seems to \
be no admin in clockify. Check your workspace settings and grant admin rights to %s."%(name, manager, manager))
                        sys.exit(1)
                    else:
                        numErr+=1
                else:
                    numErr+=1
            else:
                self.logger.info(" ...project %s already exists, skip..."%name)

                # Add groups even if project exist.
                #if pgroups != []:
                #    self.clockify.addGroupsToProject(workspace, wsId, pId, wgroupIds, pgroups)

                numSkips+=1
            idx += 1
            
        return numPrjs, numOk, numSkips, numErr
    
    def syncProjectsArchive(self, workspace):
        prjs = self.toggl.getWorkspaceProjects(workspace)
        
        idx = 0
        numPrjs = len(prjs)
        numOk = 0
        numSkips = 0
        numErr = 0
        for p in prjs:
            name = p["name"]
            clientName = None
            if "cid" in p:
                clientName = self.toggl.getClientName(p["cid"], workspace, nullOK=True)
            if p["active"] == False:
                # get clientName
                
                self.logger.info("project %s is not active, trying to archive (%d of %d)" % 
                                 (name + "|" + str(clientName), idx, numPrjs))
                c_prjID = self.clockify.getProjectID(name, clientName, workspace)
                c_prj = self.clockify.getProject(c_prjID)
                rv = self.clockify.archiveProject(c_prj)
                if rv == ClockifyAPI.RetVal.OK:
                    self.logger.info("...ok")
                    numOk+=1
                else:
                    numErr+=1
            else:
                self.logger.info("project %s is still active, skipping (%d of %d)"%(name +"|"+str(clientName), idx, numPrjs))
                numSkips+=1
            
            idx += 1
            
        return numPrjs, numOk, numSkips, numErr
    
    def timeToUtc(self, time):
        t = dateutil.parser.parse(time)
        utc = t.astimezone(pytz.UTC).isoformat().split("+")[0]#
        return dateutil.parser.parse(utc)

    def verifyUserMail(self, togglUserID, togglUserName):
        """
        Verifies and returns the email associated with a toggl User ID
        """
        try:
            #verify email exists in both toggl / clockify
            userMail = self.toggl.getUserEmail(togglUserID, self._workspace) #verify email exists in toggl.
            self.clockify.getUserIDByMail(userMail, self._workspace) # verify email actually exists in workspace.
        except:
            try:
                # attempt to match user via username
                cID = self.clockify.getUserIDByName(togglUserName, self._workspace)
                self.logger.info("user '%s' found in clockify workspace as ID=%s"%(togglUserName, cID))
                userMail = self.clockify.getUserMailById(cID, self._workspace)
                self.logger.info("user ID %s (name='%s') not in toggl workspace, but found a match in clockify workspace %s..."%(togglUserID, togglUserName, userMail))
            except:
                # skip user entirely
                if self._skipInvTogglUsers:
                    self.logger.warning("user ID %s (name='%s') not in toggl workspace, skipping entry %s..."%(togglUserID, togglUserName, description))
                    return None
                # assign task to the fallback email address.
                elif self.clockify.fallbackUserMail != None:
                    userMail = self.clockify.fallbackUserMail
                    self.logger.info("user '%s' not found in clockify workspace, using fallback user '%s'"%(togglUserID, userMail))
                else:
                    raise
        return userMail

    def onNewReports(self, entries, totalCount):
            
        if entries == None and totalCount == 0:
            #next page
            self._idx = 0
        else:
            entry_data = []
            
            for idx, e in enumerate(entries):
                self._idx+=1
                
                start = self.timeToUtc(e["start"])
                if e["end"] != None:
                    end = self.timeToUtc(e["end"])
                else:
                    end = None
                description = e["description"]
                projectName = e["project"]
                userID = e["uid"]
                billable = e["is_billable"]
                tagNames = e["tags"]
                userName = e["user"]
                taskName = e["task"]
                clientName = e["client"]
                
                self.logger.info("Queuing entry %s, project: %s (%d of %d)"%(description, str(projectName)+"|"+str(clientName), self._idx, totalCount))
                userMail = self.verifyUserMail(userID, userName)
                if userMail is None and self._skipInvTogglUsers:
                    self._numSkips+=1
                    continue

                entry_data.append([start,description,projectName,clientName,userMail,self._workspace,
                                   "Z",end,billable,tagNames,taskName])

            results = self.clockify.addEntriesThreaded(entry_data)
            for rv, _ in results:
                if rv == ClockifyAPI.RetVal.ERR:
                    self._numErr+=1
                elif rv == ClockifyAPI.RetVal.EXISTS:
                    self._numSkips+=1
                else:
                    self._numOk+=1
            self._numEntries += len(entries)
    
    
    def syncEntries(self, workspace, startTime, skipInvTogglUsers=False, until=None):
        if until is None:
            until = datetime.datetime.now()

        self._idx = 0
        self._numSkips = 0
        self._numOk = 0
        self._numErr = 0
        self._numEntries = 0
        self._workspace = workspace
        self._skipInvTogglUsers = skipInvTogglUsers
        
        self.toggl.getReports(workspace, startTime, until, self.onNewReports)
                
        return self._numEntries, self._numOk, self._numSkips, self._numErr
    
    def getTogglWorkspaces(self):
        workspaces = []
        for ws in self.toggl.getWorkspaces():
            workspaces.append(ws["name"])
        return workspaces
