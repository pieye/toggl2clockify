#!/usr/bin/env python
# -*- coding: utf-8 -*-

__author__ = "Markus Proeller"
__copyright__ = "Copyright 2019, pieye GmbH (www.pieye.org)"
__maintainer__ = "Markus Proeller"
__email__ = "markus.proeller@pieye.org"

import logging
import os
import json
import datetime
import dateutil
import sys

logger = logging.getLogger("toggl2clockify")


from toggl2clockify.args import parse as parse_args
from toggl2clockify.Clue import Clue

def query_yes_no(question, default="yes"):
    """Ask a yes/no question via raw_input() and return their answer.

    "question" is a string that is presented to the user.
    "default" is the presumed answer if the user just hits <Enter>.
        It must be "yes" (the default), "no" or None (meaning
        an answer is required of the user).

    The "answer" return value is True for "yes" or False for "no".
    """
    valid = {"yes": True, "y": True, "ye": True,
             "no": False, "n": False}
    if default is None:
        prompt = " [y/n] "
    elif default == "yes":
        prompt = " [Y/n] "
    elif default == "no":
        prompt = " [y/N] "
    else:
        raise ValueError("invalid default answer: '%s'" % default)

    while True:
        sys.stdout.write(question + prompt)
#        try:
#            input = raw_input
#        except NameError:
#            pass
        choice = input().lower()
        if default is not None and choice == '':
            return valid[default]
        elif choice in valid:
            return valid[choice]
        else:
            sys.stdout.write("Please respond with 'yes' or 'no' "
                             "(or 'y' or 'n').\n")

def load_config():
    fName = os.path.abspath("config.json")
    
    try:
        with open(fName, "r") as f:
            try: 
                data = json.load(f)
                return data
            except json.JSONDecodeError as e:
                logger.error("Error decoding file: %s" % str(e))
    except FileNotFoundError:
        logger.error("File %s not found"%(fName))
    
    return None
        


def check_config(data):
    """
    Tries to parse each config item, and then returns a (success, values_tuple)
    """

    if "ClockifyKeys" not in data:
        logger.error("json entry 'ClockifyKeys' missing in file %s"%fName)
        return (False, None)
        
        
    clockifyTokens = data["ClockifyKeys"]
    if type(clockifyTokens) != type ([]):
        logger.error("json entry 'ClockifyKeys' must be a list of strings")
        return (False, None)

    if "TogglKey" not in data:
        logger.error("json entry 'TogglKey' missing in file %s"%fName)
        return (False, None)
                
    togglKey = data["TogglKey"]
    if type(togglKey) != type(u""):
        logger.error("json entry 'TogglKey' must be a string")
        return (False, None)
                
    if "StartTime" not in data:
        logger.error("json entry 'StartTime' missing in file %s"%fName)
        return (False, None)

    
    try:
        startTime = dateutil.parser.parse(data["StartTime"])
    except (ValueError, OverFlowError):
        logger.error("Could not parse 'StartTime' correctly" +
                     "make sure it is a ISO 8601 time string")
        return (False, None)

    if "EndTime" in data:
        try:
            endTime = dateutil.parser.parse(data["EndTime"])
        except (ValueError, OverFlowError):
            logger.error("Could not parse 'EndTime' correctly" +
                         "make sure it is a ISO 8601 time string")
            return (False, None)
    else:
        logger.info("'EndTime' not found in config file, " +
                    "importing all entries until now")
        endTime = datetime.datetime.now()

    
    if "Workspaces" in data:
        workspaces = data["Workspaces"]
        if type(workspaces) != type([]):
            logger.error("json entry 'Workspaces' must be a list")
            return (False, None)
    else:
        workspaces = None
            
    
    if "ClockifyAdmin" not in data:
        logger.error("json entry 'ClockifyAdmin' missing in file %s"%fName)
        return (False, None)
    else:
        clockifyAdmin = data["ClockifyAdmin"]
        if type(clockifyAdmin) != type(u""):
            logger.error("json entry 'ClockifyAdmin' must be a string")
            return (False, None)
    
    if "FallbackUserMail" in data:
        fallbackUserMail = data["FallbackUserMail"]
    else:
        fallbackUserMail = None

    return (True, [clockifyTokens,togglKey,startTime,endTime,
                   workspaces,clockifyAdmin,fallbackUserMail])

def get_workspaces(cl, workspaces):
    """
    Imports all workspaces if none were provided.
    Returns list of workspace names
    """
    if workspaces == None:
        logger.info("no workspaces specified in json file,"+
                    "I'm trying to import all toggl workspaces...")
        workspaces = cl.getTogglWorkspaces()
        logger.info("The following workspaces were found " +
                    "and will be imported now %s" % str(workspaces))
    
    return workspaces

def import_workspace(ws, idx, numWS, cl, startTime, endTime, args):
    logger.info("-------------------------------------------------------------")
    logger.info("Starting to import workspace '%s' (%d of %d)"%(ws, idx, numWS))
    logger.info("-------------------------------------------------------------")
        
    logger.info("-------------------------------------------------------------")
    logger.info("Phase 1 of 7: Import clients")
    logger.info("-------------------------------------------------------------")
    
    if args.skipClients == False:
        numEntries, numOk, numSkips, numErr = cl.syncClients(ws)    
    else:        
        numEntries, numOk, numSkips, numErr = (0,0,0,0)
        logger.info("... skipping phase 1")
    
    logger.info("-------------------------------------------------------------")
    logger.info("Phase 1 of 7 (Import clients) completed " 
                + "(entries=%d, ok=%d, skips=%d, err=%d)"
                %  (numEntries, numOk, numSkips, numErr))
    logger.info("-------------------------------------------------------------")
    
        
    logger.info("-------------------------------------------------------------")
    logger.info("Phase 2 of 7: Import tags")
    logger.info("-------------------------------------------------------------")
    if args.skipTags == False:
        numEntries, numOk, numSkips, numErr = cl.syncTags(ws)
    else:
        numEntries, numOk, numSkips, numErr = (0,0,0,0)
        logger.info("... skipping phase 2")
        
    logger.info("-------------------------------------------------------------")
    logger.info("Phase 2 of 7 (Import tags) completed " 
                + "(entries=%d, ok=%d, skips=%d, err=%d)"
                % (numEntries, numOk, numSkips, numErr))
    logger.info("-------------------------------------------------------------")

    logger.info("-------------------------------------------------------------")
    logger.info("Phase 3 of 7: Import groups")
    logger.info("-------------------------------------------------------------")
    if not args.skipGroups:
        numEntries, numOk, numSkips, numErr = cl.syncGroups(ws)
    else:
        numEntries, numOk, numSkips, numErr = (0,0,0,0)
        logger.info("... skipping phase 3")
        
    logger.info("-------------------------------------------------------------")
    logger.info("Phase 3 of 7 (Import groups) completed " 
                + "(entries=%d, ok=%d, skips=%d, err=%d)"
                %  (numEntries, numOk, numSkips, numErr))
    logger.info("-------------------------------------------------------------")
        
    logger.info("-------------------------------------------------------------")
    logger.info("Phase 4 of 7: Import projects")
    logger.info("-------------------------------------------------------------")
    if not args.skipProjects:
        numEntries, numOk, numSkips, numErr = cl.syncProjects(ws)
    else:
        numEntries, numOk, numSkips, numErr = (0,0,0,0)
        logger.info("... skipping phase 3")
             
    logger.info("-------------------------------------------------------------")
    logger.info("Phase 4 of 7 (Import projects) completed " 
                + "(entries=%d, ok=%d, skips=%d, err=%d)"
                %  (numEntries, numOk, numSkips, numErr))
    logger.info("-------------------------------------------------------------")        
        
    logger.info("-------------------------------------------------------------")
    logger.info("Phase 5 of 7: Import tasks")
    logger.info("-------------------------------------------------------------")
    if not args.skipTasks:
        numEntries, numOk, numSkips, numErr = cl.syncTasks(ws)
    else:
        numEntries, numOk, numSkips, numErr = (0,0,0,0)
        logger.info("... skipping phase 5")


    logger.info("-------------------------------------------------------------")
    logger.info("Phase 6 of 7: Import time entries from %s until %s"
                % (str(startTime), str(endTime)))
    logger.info("-------------------------------------------------------------")
    if not args.skipEntries:
        numEntries, numOk, numSkips, numErr = cl.syncEntries(ws, startTime, until=endTime)
    else:
        numEntries, numOk, numSkips, numErr = (0,0,0,0)
        logger.info("... skipping phase 6")
        
    logger.info("-------------------------------------------------------------")
    logger.info("Phase 6 of 7 (Import entries) completed " 
                + "(entries=%d, ok=%d, skips=%d, err=%d)"
                %  (numEntries, numOk, numSkips, numErr))
    logger.info("-------------------------------------------------------------")
        
    logger.info("-------------------------------------------------------------")
    logger.info("Phase 7 of 7: Archiving projects")
    logger.info("-------------------------------------------------------------")
    if args.doArchive:
        numEntries, numOk, numSkips, numErr = cl.syncProjectsArchive(ws)
    else:
        numEntries, numOk, numSkips, numErr = (0,0,0,0)
        logger.info("... skipping phase 7")
        
    logger.info("-------------------------------------------------------------")
    logger.info("Phase 7 of 7 (Archiving  projects) completed " 
                + "(entries=%d, ok=%d, skips=%d, err=%d)"
                %  (numEntries, numOk, numSkips, numErr))
    logger.info("-------------------------------------------------------------")
        
    logger.info("Finished importing workspace '%s'" % (ws))

def migrate(args):
    """
    Migrates toggl to clockify in 7 stages. 
    Alternatively wipes the entire workspace if --wipeAll is used.
    """
    ok = False

    data = load_config()
    if data is None:
        return
            
    ok, rv = check_config(data)
    if not ok:
        return

    (clockifyTokens, togglKey, startTime, endTime, 
    workspaces, clockifyAdmin, fallbackUserMail) = rv


    cl = Clue(clockifyTokens, clockifyAdmin, togglKey, fallbackUserMail)
    
    workspaces = get_workspaces(cl, workspaces)
    
    # Option to delete specified entries and exit    
    if args.deleteEntries != None:
        question = ("All entries for user %s in workspaces %s will be deleted." 
                   + "This cannot be undone, do you want to proceed"
                   % (args.deleteEntries, workspaces))
        if not query_yes_no(question, default="no"):
            return
        for ws in workspaces:
            logger.info("deleting all entries in workspace %s" % ws)
            for user in args.deleteEntries:
                cl.clockify.deleteEntriesOfUser(user, ws)
    
    # Option to wipe all entries and exit
    if args.wipeAll:
        question = "This will wipe your entire workspace. Are you sure?"
        if not query_yes_no(question, default="no"):
            return
        else:
            for ws in workspaces:
                cl.clockify.wipeOutWorkspace(ws)
            return

    numWS = len(workspaces)
    idx = 1
    for idx, ws in enumerate(workspaces):
        import_workspace(ws, idx+1, numWS, cl, startTime, endTime, args)
        
