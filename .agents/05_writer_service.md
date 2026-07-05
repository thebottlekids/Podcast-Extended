# Writer Service & IPC Architecture

## Overview

Podly uses a **dual-app architecture** to handle SQLite's single-writer limitation gracefully. This prevents database locks and deadlocks in multi-threaded web environments.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                      Web Application                         │
│                   (Flask - Read-Only)                       │
│                                                              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                  │
│  │  Routes  │  │  Models  │  │Scheduler │                  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘                  │
│       │             │             │                         │
│       └─────────────┴─────────────┘                         │
│                     │                                       │
│              ┌──────▼──────┐                               │
│              │ writer_client│ (IPC Client)                 │
│              └──────┬──────┘                               │
└─────────────────────┼──────────────────────────────────────┘
                      │ IPC Queue (multiprocessing.Manager)
                      ▼
┌─────────────────────────────────────────────────────────────┐
│                    Writer Service                            │
│              (Dedicated Write Process)                      │
│                                                              │
│  ┌────────────┐  ┌──────────────┐  ┌────────────┐          │
│  │   Queue    │─▶│  Executor    │─▶│   SQLite   │          │
│  │   Server   │  │ (Commands)   │  │   Writes   │          │
│  └────────────┘  └──────────────┘  └────────────┘          │
└─────────────────────────────────────────────────────────────┘
```

## Why This Pattern?

SQLite only supports one writer at a time. In a multi-threaded web server:
- Multiple threads trying to write → "database is locked" errors
- Long-running transactions block other operations
- Deadlocks between web threads and background jobs

**Solution:** Centralize all writes through a single dedicated process.

## Components

### WriterClient (`writer/client.py`)
Client library used by web app to send write commands.

**API:**
```python
writer_client.create(model, data)      # Create record
writer_client.update(model, pk, data)  # Update record  
writer_client.delete(model, pk)        # Delete record
writer_client.action(action_name, params)  # Custom action
```

**Features:**
- Automatic connection management
- Synchronous (wait=True) or async (wait=False) operations
- Local fallback for testing
- Reply queue for responses

### WriteCommand (`writer/protocol.py`)
Command structure for IPC communication.

```python
@dataclass
class WriteCommand:
    id: str                    # Command UUID
    type: WriteCommandType     # CREATE|UPDATE|DELETE|ACTION|TRANSACTION
    model: Optional[str]       # Model name (for CRUD)
    data: Dict[str, Any]       # Command data
    reply_queue: Optional[Any] # Queue for response
```

### CommandExecutor (`writer/executor.py`)
Executes commands on the writer side.

**Supported Operations:**
- **Model Operations**: CRUD via SQLAlchemy
- **Actions**: Custom business logic (jobs, feeds, cleanup)
- **Transactions**: Multi-command atomic operations

**Actions Available:**
- `cleanup_action`: Post cleanup
- `dequeue_job`: Job processing
- `feeds_action`: Feed operations
- `jobs_action`: Job management
- `processor_action`: Audio processing
- `system_action`: System operations
- `users_action`: User management

### Writer Service (`writer/service.py`)
Main writer process entry point.

**Startup:**
1. Start IPC server (multiprocessing.Manager)
2. Create Flask app context
3. Initialize executor
4. Enter command loop

**Command Loop:**
```python
while True:
    cmd = queue.get()           # Block for command
    result = executor.process(cmd)  # Execute
    if cmd.reply_queue:
        cmd.reply_queue.put(result)  # Send response
```

### IPC Layer (`ipc.py`)
Low-level inter-process communication.

**Server:**
```python
manager = make_server_manager()  # Port 50001
queue = manager.get_command_queue()
```

**Client:**
```python
manager = make_client_manager()
queue = manager.get_command_queue()
```

## Web App Configuration

Web app is configured as read-only to prevent accidental writes:

```python
# From __init__.py
@event.listens_for(Session, "after_begin")
def receive_after_begin(session, transaction, connection):
    if app_role == "web":
        connection.connection.isolation_level = "DEFERRED"
        session.autoflush = False
        session.info["readonly"] = True

@event.listens_for(Session, "before_flush")
def receive_before_flush(session, ...):
    if session.info.get("readonly"):
        raise RuntimeError("Writes must go through writer service")
```

## Usage Examples

### Creating a Record
```python
# Web app code
from app.writer.client import writer_client

result = writer_client.create(
    "Feed",
    {"title": "My Podcast", "rss_url": "https://example.com/feed.xml"}
)
if result.success:
    feed_id = result.data["id"]
```

### Custom Action
```python
# Trigger job processing
result = writer_client.action("dequeue_job", {
    "run_id": run_id,
    "job_id": job_id
})
```

### Transaction
```python
# Multiple operations atomically
cmd = WriteCommand(
    id=str(uuid.uuid4()),
    type=WriteCommandType.TRANSACTION,
    data={"commands": [cmd1, cmd2, cmd3]}
)
result = writer_client.submit(cmd, wait=True)
```

## Error Handling

- **Timeout**: `submit()` returns a failed `WriteResult(success=False, error="Writer service did not respond (timeout)")`
  after 10s default, instead of raising `TimeoutError` -- most callers only
  check `result.success` and previously didn't catch the raised exception,
  which could crash a job step ungracefully instead of surfacing a clean error.
- **Rollback**: Failed transactions auto-rollback
- **Dead Letter**: Failed commands logged for inspection
- **Local Fallback**: Test mode executes directly

## Mass-Assignment Protection

`execute_model_command` (`writer/model_ops.py`) denies a fixed set of
sensitive fields (`password_hash`, `role`, `is_admin`, `id`, `created_at`)
on both CREATE and UPDATE, regardless of target model. No live caller relies
on setting these through the generic CRUD path today (user/auth writes go
through dedicated named actions, e.g. `users_action`), so this is a safety
net against a future route bug forwarding user-supplied JSON straight into
`writer_client.create()`/`.update()`.

## IPC Authkey

`app/ipc.py`'s `_get_default_authkey()` falls back to a hardcoded string if
`PODLY_IPC_AUTHKEY` isn't set. In the container, `scripts/start_services.sh`
generates a random key once per boot and exports it before starting either
the writer or web process, so both inherit the same real key. The hardcoded
fallback only matters for non-containerized local dev where that entrypoint
script doesn't run.

## Deployment

**Docker Compose:**
```yaml
services:
  web:
    # Main Flask app
  writer:
    # Dedicated writer process
```

Both share same SQLite file via volume mount.

## Important Rules

⚠️ **NEVER use `db.session.commit()` in web app code**
⚠️ **ALWAYS use `writer_client` for database writes**
⚠️ **Read-only sessions will raise errors on flush**
