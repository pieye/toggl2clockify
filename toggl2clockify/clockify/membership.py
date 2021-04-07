"""
Membership class. Links workspace, user and manager
"""


class MemberShips:
    """
    Membership class. Links workspace, user and manager
    """

    def __init__(self, api):
        self.connector = api
        self.memberships = []
        self.workspace = ""

    def add_membership(
        self,
        email,
        project_name,
        workspace,
        m_type="PROJECT",
        m_status="ACTIVE",
        hourly_rate=None,
        is_manager=False,
    ):
        self.workspace = workspace

        userID = self.connector.get_userid_by_email(email, workspace)

        membership = {}
        membership["membershipStatus"] = m_status
        membership["membershipType"] = m_type
        membership["userId"] = userID  # clockify_user_id
        membership["manager"] = manager  # boolean
        if hourly_rate is not None:
            membership["hourlyRate"] = hourly_rate.rate
        self.memberships.append(membership)
        return True

    def get_manager_email(self):
        mail = ""
        for m_ship in self.memberships:
            if m_ship["manager"]:
                mail = self.connector.get_email_by_id(m_ship["userId"],
                                                      self.workspace)
                break
        return mail

    def get_data(self):
        return self.memberships
