#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = "Markus Proeller"
__copyright__ = "Copyright 2019, pieye GmbH (www.pieye.org)"
__maintainer__ = "Markus Proeller"
__email__ = "markus.proeller@pieye.org"

import TogglAPI
import ClockifyAPI
import dateutil.parser
import pytz
import datetime
import logging
import sys

class Clue:
    def __init__(self, clockifyKey, clockifyAdmin, togglKey, clockifyReqTimeout=1):
        self.logger = logging.getLogger('toggl2clockify')
        
        self.logger.info("testing toggl API key %s"%togglKey)
        try:
            self.toggl = TogglAPI.TogglAPI(togglKey)
            self.logger.info("...ok, togglKey resolved to email %s"%self.toggl.email)
        except Exception as e:
            self.logger.error("something went wrong with your toggl key, msg=%s"%str(e))
            raise
        
        self.clockify = ClockifyAPI.ClockifyAPI(clockifyKey, clockifyAdmin, reqTimeout=clockifyReqTimeout)
        
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
            
    def syncProjects(self, workspace):
        prjs = self.toggl.getWorkspaceProjects(workspace)
        clockifyPrjs = self.clockify.getProjects(workspace)
        clockifyPrjNames = []
        for pr in clockifyPrjs:
            clockifyPrjNames.append(pr["name"])
        
        idx = 0
        numPrjs = len(prjs)
        numOk = 0
        numSkips = 0
        numErr = 0
        for p in prjs:
            self.logger.info ("adding project %s (%d of %d projects)"%(p["name"], idx+1, numPrjs))
            name = p["name"]
            if name not in clockifyPrjNames:
                err = False
                clientName = None
                if "cid" in p:
                    clientName = self.toggl.getClientName(p["cid"], workspace)
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
                    if rv == ClockifyAPI.RetVal.OK:
                        self.logger.info("...ok")
                        numOk+=1
                    elif rv == ClockifyAPI.RetVal.EXISTS:
                        self.logger.info("project %s already exists, skip..."%name)
                        numSkips+=1
                    elif rv == ClockifyAPI.RetVal.FORBIDDEN:
                        manager = m.getManagerUserMail()
                        self.logger.error("Could not add project %s. %s was project admin in toggl, but seems to \
be no admin in clockify. Check your workspace settings and grant admin rights to %s."%(name, manager, manager))
                        sys.exit(1)
                    else:
                        numErr+=1
                else:
                    numErr+=1
            else:
                self.logger.info("project %s already exists, skip..."%name)
                numSkips+=1
            idx += 1
            
        return numPrjs, numOk, numSkips, numErr
    
    def syncProjectsArchive(self, workspace):
        prjs = self.toggl.getWorkspaceProjects(workspace)
        clockifyPrjs = self.clockify.getProjects(workspace)
        clockifyPrjNames = []
        for pr in clockifyPrjs:
            clockifyPrjNames.append(pr["name"])
        
        idx = 0
        numPrjs = len(prjs)
        numOk = 0
        numSkips = 0
        numErr = 0
        for p in prjs:
            name = p["name"]
            if p["active"] == False:
                self.logger.info("project %s is not active, trying to archive (%d of %d)"%(name, idx, numPrjs))
                rv = self.clockify.archiveProject(name, workspace)
                if rv == ClockifyAPI.RetVal.OK:
                    self.logger.info("...ok")
                    numOk+=1
                else:
                    numErr+=1
            else:
                self.logger.info("project %s is still active, skipping (%d of %d)"%(name, idx, numPrjs))
                numSkips+=1
            
            idx += 1
            
        return numPrjs, numOk, numSkips, numErr
    
    def timeToUtc(self, time):
        t = dateutil.parser.parse(time)
        utc = t.astimezone(pytz.UTC).isoformat().split("+")[0]#
        return dateutil.parser.parse(utc)

    def onNewReports(self, entries, totalCount):
            
        if entries == None and totalCount == 0:
            #next page
            self._idx = 0
        else:
            for e in entries:
                self._idx+=1
                self.logger.info("adding entry %s, project: %s (%d of %d)"%(e["description"], e["project"], self._idx, totalCount))
                start = self.timeToUtc(e["start"])
                end = self.timeToUtc(e["end"])
                description = e["description"]
                projectName = e["project"]
                userID = e["uid"]
                billable = e["is_billable"]
                tagNames = e["tags"]
                userName = e["user"]
                
                try:
                    userMail = self.toggl.getUserEmail(userID, self._workspace)
                except:
                    try:
                        cID = self.clockify.getUserIDByName(userName, self._workspace)
                        userMail = self.clockify.getUserMailById(self, cID, self._workspace)
                        self.logger.info("user ID %s (name=%s) not in toggl workspace, but found a match in clockify workspace %s..."%(userID, e["user"], userMail))
                    except:
                        if self._skipInvTogglUsers:
                            self.logger.warning("user ID %s (name=%s) not in toggl workspace, skipping entry %s..."%(userID, userName, description))
                            continue
                        else:
                            raise
                            
                rv, data = self.clockify.addEntry(start, description, projectName, userMail, self._workspace, 
                         timeZone="Z", end=end, billable=billable, tagNames=tagNames)
                if rv == ClockifyAPI.RetVal.ERR:
                    self._numErr+=1
                elif rv == ClockifyAPI.RetVal.EXISTS:
                    self.logger.info("entry already exists, skip...")
                    self._numSkips+=1
                else:
                    self.logger.info("...ok")
                    self._numOk+=1
            self._numEntries += len(entries)
    
    
    def syncEntries(self, workspace, startTime, skipInvTogglUsers=False):
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
