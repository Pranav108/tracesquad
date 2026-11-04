"""In-memory sandbox: mock users built by setup calls, sandbox service versions, sandbox logs.

This is the only mutable state in the service. It lives in memory and resets on restart
or on POST /sandbox/reset.
"""

from typing import Any

from pydantic import BaseModel

from bugmock.errors import ApiError
from bugmock.models import LogEntry
from bugmock.store import DataError, Store, parse_cohort_id


class MockUser(BaseModel):
    mock_user_id: str
    cohort_id: str
    platform: str
    app_version: str
    login: dict[str, str]
    tags: list[str]
    calls: list[dict[str, Any]]


def has_tag(tags: list[str], requirement: str) -> bool:
    return any(tag == requirement or tag.startswith(requirement + ":") for tag in tags)


class Sandbox:
    def __init__(self, store: Store):
        self.store = store
        self.reset()

    def reset(self) -> None:
        self.users: dict[str, MockUser] = {}
        self.logs: list[LogEntry] = []
        self.services: dict[str, str] = dict(self.store.dataset.sandbox_defaults)
        self.published_fixes: set[str] = {f.fix_id for f in self.store.dataset.fixes if f.published}
        self._user_seq = 0
        self._run_seq = 0

    def create_user(self, cohort_id: str) -> MockUser:
        try:
            parts = parse_cohort_id(cohort_id, self.store.dataset.cohort_dimensions)
        except DataError as exc:
            raise ApiError(422, str(exc)) from exc
        self._user_seq += 1
        n = self._user_seq
        params = {"cohort_id": cohort_id}
        user = MockUser(
            mock_user_id=f"MU-{n:04d}",
            cohort_id=cohort_id,
            platform=parts["platform"],
            app_version=parts["app_version"],
            login={"phone": f"+91-90000-0{n:04d}", "otp": "000000"},
            tags=[t.format(**params) for t in self.store.setup_apis["create_user"].adds_tags],
            calls=[{"api": "create_user", "params": params}],
        )
        self.users[user.mock_user_id] = user
        return user

    def get(self, mock_user_id: str) -> MockUser:
        if mock_user_id not in self.users:
            raise ApiError(404, f"mock user '{mock_user_id}' not found")
        return self.users[mock_user_id]

    def apply(self, mock_user_id: str, api_name: str, params: dict[str, Any]) -> MockUser:
        user = self.get(mock_user_id)
        api = self.store.setup_apis.get(api_name)
        if api is None or api_name == "create_user":
            raise ApiError(404, f"setup api '{api_name}' not found; see GET /setup-apis")
        missing = [p for p in api.params if p not in params]
        if missing:
            raise ApiError(422, f"setup api '{api_name}' is missing params: {', '.join(missing)}")
        self._check_values(api_name, list(api.params), params)
        for requirement in api.requires:
            if not has_tag(user.tags, requirement):
                raise ApiError(
                    409, f"missing prerequisite '{requirement}': call {self._provider_of(requirement)} first"
                )
        for tag in (t.format(**params) for t in api.adds_tags):
            if tag not in user.tags:
                user.tags.append(tag)
        user.calls.append({"api": api_name, "params": params})
        return user

    def _check_values(self, api_name: str, names: list[str], params: dict[str, Any]) -> None:
        dims = self.store.dataset.cohort_dimensions
        allowed = {
            "city": list(dims.cities),
            "group": list(dims.groups),
            "plan": [p for p in dims.plans if p != "none"],
            "type": ["upi", "card"],
        }
        for name in names:
            value = params[name]
            if name == "items":
                if not (isinstance(value, list) and value and all(isinstance(i, dict) and "item_id" in i for i in value)):
                    raise ApiError(422, f"setup api '{api_name}': param 'items' must be a non-empty list of {{item_id, qty}}")
            elif not isinstance(value, str) or not value:
                raise ApiError(422, f"setup api '{api_name}': param '{name}' must be a non-empty string")
            elif name in allowed and value not in allowed[name]:
                raise ApiError(
                    422, f"setup api '{api_name}': {name} '{value}' is not one of {', '.join(allowed[name])}"
                )

    def _provider_of(self, requirement: str) -> str:
        for api in self.store.setup_apis.values():
            if any(t.split(":")[0] == requirement for t in api.adds_tags):
                return api.name
        return "the setup api that provides it"

    def deploy(self, service: str, version: str) -> dict[str, str]:
        if service not in self.services:
            raise ApiError(404, f"service '{service}' not found in sandbox; see GET /sandbox/services")
        self.services[service] = version
        return dict(self.services)

    def next_run_id(self) -> str:
        self._run_seq += 1
        return f"RUN-{self._run_seq:04d}"
