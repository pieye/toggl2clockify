import argparse

def parse():
    # fmt off
    parser = argparse.ArgumentParser()
    parser.add_argument("--skipClients", help="don't sync workspace clients", action="store_true")
    parser.add_argument("--skipProjects", help="don't sync workspace projects", action="store_true")
    parser.add_argument("--skipEntries", help="don't sync workspace time entries", action="store_true")
    parser.add_argument("--skipTags", help="don't sync tags", action="store_true")
    parser.add_argument("--skipTasks", help="don't sync tasks", action="store_true")
    parser.add_argument("--skipGroups", help="don't sync groups", action="store_true")
    parser.add_argument("--doArchive", help="sync archiving of projects", action="store_true")
    parser.add_argument("--reqTimeout", help="sleep time between clockify web requests", type=float, default=0.01)
    parser.add_argument("--deleteEntries", nargs='+', help="delete all entries of given users")
    parser.add_argument("--wipeAll", help="delete all clockify entries, projects, clients, tasks", default=False, action="store_true")
    #fmt on
    return parser.parse_args()

