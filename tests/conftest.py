import json
import uuid
from pathlib import Path

import pytest

from travel_agent.agent import TravelAgent
from travel_agent.config import ROOT, Settings
from travel_agent.models import RunRequest
from travel_agent.storage import Store


@pytest.fixture
def factory(tmp_path):
    counter = 0

    def make(**kwargs):
        nonlocal counter
        counter += 1
        dataset = kwargs.pop("dataset", None)
        policies = kwargs.pop("policies", None)
        model = kwargs.pop("model", None)
        settings = Settings(workspace=tmp_path / str(counter), **kwargs)
        store = Store(settings.workspace, dataset, policies)
        return TravelAgent(settings, store=store, model=model)
    return make


def session(agent, user="demo-an"):
    raw = agent.store.create_session(user)
    return agent.store.authenticate("Bearer " + raw["token"]), raw["token"]


def run(agent, message, user="demo-an", caller=None, key=None, **kwargs):
    if caller is None:
        caller, _ = session(agent, user)
    return agent.run(caller, RunRequest(message=message, request_id=key or uuid.uuid4().hex, **kwargs))


def seed_policies():
    return json.loads((ROOT / "data/policies.json").read_text())
