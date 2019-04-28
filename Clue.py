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
                        m.addMembership(userMail, p["name"], workspace, 
                          membershipType="PROJECT", membershipStatus="ACTIVE",
                          hourlyRate=None)
                    except Exception as e:
                        self.logger.warning ("error adding user %s to clockify project, msg=%s"%(userMail, str(e)))
                        err = True
                        break
    
                if err == False:
                    
                    rv = self.clockify.addProject(name, clientName, workspace, isPublic, billable, 
                           color, memberships=m)
                    if rv == ClockifyAPI.RetVal.OK:
                        self.logger.info("...ok")
                        numOk+=1
                    elif rv == ClockifyAPI.RetVal.EXISTS:
                        self.logger.info("project %s already exists, skip..."%name)
                        numSkips+=1
                    else:
                        numErr+=1
                else:
                    numErr+=1
            else:
                self.logger.info("project %s already exists, skip..."%name)
                numSkips+=1
            idx += 1
            
        return numPrjs, numOk, numSkips, numErr
    
    def timeToUtc(self, time):
        t = dateutil.parser.parse(time)
        utc = t.astimezone(pytz.UTC).isoformat().split("+")[0]#
        return dateutil.parser.parse(utc)
        
    
    def syncEntries(self, workspace, startTime):
        until = datetime.datetime.now()
        entries = self.toggl.getReports(workspace, startTime, until)
        idx = 0
        numSkips = 0
        numOk = 0
        numErr = 0
        numEntries = len(entries)
        for e in entries:
            idx+=1
            self.logger.info("adding entry %d of %d"%(idx, len(entries)))
            start = self.timeToUtc(e["start"])
            end = self.timeToUtc(e["end"])
            description = e["description"]
            projectName = e["project"]
            userID = e["uid"]
            billable = e["is_billable"]
            tagNames = e["tags"]
            
            userMail = self.toggl.getUserEmail(userID, workspace)
            rv, data = self.clockify.addEntry(start, description, projectName, userMail, workspace, 
                     timeZone="Z", end=end, billable=billable, tagNames=tagNames)
            if rv == ClockifyAPI.RetVal.ERR:
                numErr+=1
            elif rv == ClockifyAPI.RetVal.EXISTS:
                self.logger.info("entry already exists, skip...")
                numSkips+=1
            else:
                self.logger.info("...ok")
                numOk+=1
                
        return numEntries, numOk, numSkips, numErr
    
    def getTogglWorkspaces(self):
        workspaces = []
        for ws in self.toggl.getWorkspaces():
            workspaces.append(ws["name"])
        return workspaces
