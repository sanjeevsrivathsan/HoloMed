from ..models.user import User

def get_demo_user() -> User:
    # A placeholder for the actual implementation
    return User(id=1, email="test_user@example.com")

def create_demo_user() -> User:
    return User(id=1, email="test_user@example.com")
