# toggl2clockify
Migrate data from toggl to clockify

**No warranty that the tools works as expected. Read the following lines CAREFULLY and TEST it on a non productive system!**

# Usage
If you're on windows you can run the file bin/toggl2clockify.exe directly or through python by "python toggl2clockify.py"
make sure you have a file called "config.json" in the folder from where you invoke the program.

You can run the tool as often as you want, all time entries are checked for existance before being added.

Clockify doesn't allow to add a time entry for a different user account, hence you have to specify all clockify API keys of all users for the migration.

The config.json file needs the following entries:
- TogglKey: the toggl API key
- ClockifyKeys: A list of all API keys of all clockify users which shall be migrated
- StartTime: A ISO 8601 containing the start time from when to migrate entries
- ClockifyAdmin: The email address of the clockify workspace owner
- Workspaces (optional): A list of workspace names which shall be migrated

A complete list of command line parameters are shown with the -h flag, e.g.
bin/toggl2clockify.exe -h

# Prerequisites:
- The workspaces must already exist in clockify
- The useres must have already joined to the clockify workspaces

# What is migrated
- All clients of the workspace
- All tags of the workspace
- The following project attributes are migrated:
    - name
    - client
    - isPublic
    - billable
    - color
    - membership

    - NOT MIRGATED: tasks, hourlyRate, estimate

- The following time entry attributes are migrated:
    - start
    - billable
    - description
    - projectID
    - userID
    - end
    - tagIds
    
    - NOT MIRGATED: taskId, timeInterval (not sure what purpose this serves), isLocked
    
# What is not migrated
- Tasks
- User groups