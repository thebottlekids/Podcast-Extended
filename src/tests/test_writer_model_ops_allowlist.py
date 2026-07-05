"""
Tests that the generic writer CREATE/UPDATE path can't be used to mass-assign
sensitive fields (password_hash, role, is_admin, id, created_at).

Regression coverage: execute_model_command() previously did
`model_cls(**cmd.data)` / `setattr(obj, k, v)` for any key present on the
model with no allow/deny list. No live caller exploits this today (auth/user
management goes through dedicated named writer actions, not this generic
path), but a future route bug that forwards user-supplied JSON straight into
writer_client.create()/update() would otherwise be able to escalate
privileges or tamper with credentials.
"""

from typing import Generator

import pytest
from flask import Flask

from app.extensions import db
from app.models import User
from app.writer.model_ops import execute_model_command
from app.writer.protocol import WriteCommand, WriteCommandType


@pytest.fixture
def app() -> Generator[Flask, None, None]:
    app = Flask(__name__)
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    with app.app_context():
        db.init_app(app)
        db.create_all()
        yield app


def test_update_ignores_sensitive_fields(app: Flask) -> None:
    with app.app_context():
        user = User(username="alice", password_hash="original-hash", role="user")
        db.session.add(user)
        db.session.commit()

        cmd = WriteCommand(
            id="cmd-1",
            type=WriteCommandType.UPDATE,
            model="User",
            data={
                "id": user.id,
                "feed_allowance": 5,  # legitimate field, should be applied
                "role": "admin",  # privilege escalation attempt, must be ignored
                "password_hash": "attacker-controlled",  # must be ignored
            },
        )

        result = execute_model_command(cmd=cmd, model_cls=User, db_session=db.session)

        assert result.success is True
        refreshed = db.session.get(User, user.id)
        assert refreshed is not None
        assert refreshed.feed_allowance == 5
        assert refreshed.role == "user"
        assert refreshed.password_hash == "original-hash"


def test_create_ignores_sensitive_fields() -> None:
    cmd = WriteCommand(
        id="cmd-2",
        type=WriteCommandType.CREATE,
        model="User",
        data={
            "username": "bob",
            "password_hash": "should-be-set",
            "role": "admin",
            "created_at": "2000-01-01T00:00:00",
        },
    )

    captured: dict = {}

    class FakeModel:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)
            self.id = 1

    class FakeSession:
        def add(self, _obj: object) -> None:
            pass

        def flush(self) -> None:
            pass

    result = execute_model_command(
        cmd=cmd, model_cls=FakeModel, db_session=FakeSession()
    )

    assert result.success is True
    assert captured == {"username": "bob"}
