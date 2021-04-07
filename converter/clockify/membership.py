"""
Membership class. Links workspace, user and manager
"""


class MemberShips:
    """
    Memberships class. Links workspace, user and manager
    """

    def __init__(self, api):
        self.connector = api
        self.memberships = []
        self.workspace = ""

    def add_membership(
        self,
        email,
        workspace,
        hourly_rate=None,
        is_manager=False,
    ):
        """
        Creates an api friendly dictionary of a membership
        Adds it to our list of memberships for export later
        """
        self.workspace = workspace

        user_id = self.connector.get_userid_by_email(email, workspace)

        membership = {}
        membership["membershipStatus"] = "PROJECT"
        membership["membershipType"] = "ACTIVE"
        membership["userId"] = user_id  # clockify_user_id
        membership["manager"] = is_manager  # boolean
        if hourly_rate is not None:
            membership["hourlyRate"] = hourly_rate.rate
        self.memberships.append(membership)
        return True

    def get_manager_email(self):
        """
        Searches for first manager and gets their email
        """
        mail = ""
        for m_ship in self.memberships:
            if m_ship["manager"]:
                mail = self.connector.get_email_by_id(m_ship["userId"], self.workspace)
                break
        return mail

    def get_data(self):
        """
        Returns memberships
        """
        return self.memberships
