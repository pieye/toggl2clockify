"""
API user class
"""


class APIUser:
    """
    Information about an api user.
    """

    def __init__(self, token, username, email, user_id):
        self.token = token
        self.username = username
        self.email = email
        self.is_admin = False
        self.clockify_id = user_id

    def get_token(self):
        """
        returns token
        """
        return self.token

    def match(self, email, username):
        """
        Returns if this user matches email OR username
        """
        if email is not None and email == self.email:
            return True
        if username is not None and username == self.username:
            return True
        return False
