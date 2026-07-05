from __future__ import annotations

from typing import Any

from app.writer.protocol import WriteCommand, WriteCommandType, WriteResult

# Fields no generic CREATE/UPDATE command may ever set, regardless of model.
# Today every live caller of writer_client.create()/update() passes fixed,
# hardcoded field dicts from trusted internal code (auth/user management goes
# through separate named actions, not this generic path) -- this denylist is
# a safety net so a future route bug that forwards user-supplied JSON straight
# into writer_client.create()/update() can't escalate privileges or tamper
# with credentials via mass assignment.
_SENSITIVE_FIELDS = frozenset({"password_hash", "role", "is_admin", "id", "created_at"})


def execute_model_command(
    *,
    cmd: WriteCommand,
    model_cls: Any,
    db_session: Any,
) -> WriteResult:
    if cmd.type == WriteCommandType.CREATE:
        safe_data = {k: v for k, v in cmd.data.items() if k not in _SENSITIVE_FIELDS}
        obj = model_cls(**safe_data)
        db_session.add(obj)
        db_session.flush()
        data = {"id": obj.id} if hasattr(obj, "id") else None
        return WriteResult(cmd.id, True, data=data)

    if cmd.type == WriteCommandType.UPDATE:
        pk = cmd.data.get("id")
        if not pk:
            return WriteResult(cmd.id, False, error="Missing 'id' in data for UPDATE")

        obj = db_session.get(model_cls, pk)
        if not obj:
            return WriteResult(
                cmd.id, False, error=f"Record not found: {cmd.model} {pk}"
            )

        for k, v in cmd.data.items():
            if k not in _SENSITIVE_FIELDS and hasattr(obj, k):
                setattr(obj, k, v)
        return WriteResult(cmd.id, True)

    if cmd.type == WriteCommandType.DELETE:
        pk = cmd.data.get("id")
        if not pk:
            return WriteResult(cmd.id, False, error="Missing 'id' in data for DELETE")

        obj = db_session.get(model_cls, pk)
        if obj:
            db_session.delete(obj)
        return WriteResult(cmd.id, True)

    return WriteResult(cmd.id, False, error="Unknown command type")
