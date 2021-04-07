"""
Clockify project
"""

import logging


class Project:
    """
    Clockify project, constructed from toggl dictionary
    Can export to API Dictionary
    """

    def __init__(self, toggl_dict):
        self.logger = logging.getLogger("toggl2clockify")
        self.name = toggl_dict["name"]

        self.public = not toggl_dict["is_private"]
        self.billable = toggl_dict["billable"]
        self.color = toggl_dict["hex_color"]

        # these are defined in ingest()
        self.workspace = None
        self.client = None
        self.memberships = None
        self.hourly_rate = None
        self.manager = ""
        self.groups = []  # list of group_names associated with project

    def ingest(self, workspace, toggl_api, t_proj, group_map, c_membership):
        """
        Converts toggl *proj* dictionary with unique_ids into text names
        It then stores these into this class.
        Returns true if an error occurred
        """
        self.workspace = workspace
        if "cid" in t_proj:
            self.client = toggl_api.get_client_name(
                t_proj["cid"], workspace, null_ok=True
            )

        # Prepare Group assignment to Projects
        proj_groups = toggl_api.get_project_groups(self.name, workspace)
        proj_groups = proj_groups or []  # ensure empty list
        proj_groups = [group_map[item["group_id"]] for item in proj_groups]
        self.groups = proj_groups

        self.memberships = c_membership
        err = self.set_memberships(toggl_api)
        return err

    def excrete(self, api):
        """
        Now, pass in Clockify api to convert from strings to clockify_ids
        Outputs a json dict for the api request.
        """
        client_id = None
        if self.client is not None:
            client_id = api.get_client_id(self.client, self.workspace, null_ok=True)

        params = {
            "name": self.name,
            "isPublic": self.public,
            "billable": self.billable,
            "color": self.color,
        }

        if client_id is not None:
            params["clientId"] = client_id
        if self.memberships is not None:
            params["memberships"] = self.memberships.get_data()
        if self.hourly_rate is not None:
            params["hourlyRate"] = self.hourly_rate.rate

        return params

    def get_toggl_email(self, toggl_api, toggl_uid):
        try:
            email = toggl_api.get_user_email(toggl_uid, self.workspace)
        except RuntimeError as error:
            self.logger.warning(
                "user id %d not found in toggl workspace, msg=%s",
                toggl_uid,
                str(error),
            )
            raise
        return email

    def set_memberships(self, toggl_api):
        """
        Fills in the membership class
        Returns True on any error
        """

        t_members = toggl_api.get_project_users(self.name, self.workspace)
        t_members = t_members or []  # ensure empty list

        for member in t_members:
            # grab email of user
            try:
                email = self.get_toggl_email(member["uid"], toggl_api)
            except RuntimeError:
                return True

            # add user to membership list
            try:
                self.memberships.add_membership(
                    email,
                    self.name,
                    self.workspace,
                    is_manager=member["manager"],
                )
            except RuntimeError as error:
                self.logger.warning(
                    "error adding user %s to clockify project, msg=%s",
                    email,
                    str(error),
                )
                return True

        self.manager = self.memberships.get_manager_email()
        return False
