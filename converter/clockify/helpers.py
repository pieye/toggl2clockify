"""
Helper functions
"""


def match_client(project_data, client_name):
    """
    Given a project's json data, sees if the client name matches
    """
    if client_name is None:
        client_name = ""
    if "clientName" in project_data and project_data["clientName"] == client_name:
        return True
    return False


def safe_get(dictionary, key):
    """
    Safely get value from dictionary
    """
    if key in dictionary:
        return dictionary[key]
    return None


def first(the_iterable, condition=lambda x: True):
    """
    Finds first item in iterable that meets condition
    """
    for i in the_iterable:
        if condition(i):
            return i
    return None
