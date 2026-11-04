import pytest
from fastapi.testclient import TestClient

from bugmock.api import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as c:
        yield c
