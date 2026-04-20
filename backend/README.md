# 4ARM Backend API

Phase 2: FastAPI backend for the Spotify streaming farm management platform.

## Setup (Windows Development)

### 1. Install Python Dependencies

```bash
cd backend
pip install -r requirements.txt
```

### 2. Start PostgreSQL and Redis

```bash
cd ..  # Go to project root
docker-compose -f docker-compose.dev.yml up -d
```

### 3. Configure Environment

Copy `.env.example` to `.env` and adjust if needed:

```bash
cp .env.example .env
```

### 4. Run Database Migrations (Optional)

```bash
cd backend
alembic upgrade head
```

Or let the app auto-create tables on startup.

### 5. Start the Server

```bash
uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

- API docs: `http://localhost:8000/docs`
- Health check: `http://localhost:8000/health`
- WebSocket: `ws://localhost:8000/ws/dashboard`

## Project Structure

```
backend/
├── app/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Pydantic settings (.env)
│   ├── database.py          # SQLAlchemy async setup
│   ├── models/              # SQLAlchemy ORM models
│   ├── schemas/             # Pydantic request/response models
│   ├── routers/             # API endpoint modules
│   ├── services/            # Business logic (with mocks for Windows)
│   └── ws/                  # WebSocket handlers
├── alembic/                 # Database migrations
├── tests/                   # Pytest test suite
├── requirements.txt
├── Dockerfile
└── .env.example
```

## Key Design Decisions

### Proxy-Per-Account
- Each account has a 1:1 relationship with a proxy (`account.proxy_id`)
- When an account is assigned to an instance, the proxy service dynamically reconfigures the redsocks sidecar
- On Windows dev, Docker operations are mocked (logs instead of actual container operations)

### Song-Based Work Model
- No Client/Job entities
- Users add songs directly with `total_target_streams` and `daily_rate`
- The scheduler respects these limits automatically

### Mock Mode
On Windows development machine:
- `MOCK_DOCKER=true`: Instance manager logs mock operations instead of calling Docker
- `MOCK_ADB=true`: ADB service logs mock operations
- System endpoints use `psutil` for real resource metrics

## API Endpoints

### Instances
- `GET /api/instances` - List instances
- `POST /api/instances` - Create instance
- `POST /api/instances/{id}/start` - Start instance
- `POST /api/instances/{id}/stop` - Stop instance
- `POST /api/instances/{id}/restart` - Restart instance
- `DELETE /api/instances/{id}` - Destroy instance
- `POST /api/instances/{id}/assign-account` - Assign account

### Accounts
- `GET /api/accounts` - List accounts
- `POST /api/accounts` - Create account
- `POST /api/accounts/import` - CSV import
- `GET /api/accounts/{id}` - Get account
- `PATCH /api/accounts/{id}` - Update account
- `POST /api/accounts/{id}/link-proxy` - Link proxy
- `POST /api/accounts/{id}/set-cooldown` - Set cooldown

### Proxies
- `GET /api/proxies` - List proxies
- `POST /api/proxies` - Create proxy
- `POST /api/proxies/import` - CSV import
- `POST /api/proxies/{id}/test` - Test proxy
- `POST /api/proxies/test-all` - Test all proxies

### Songs
- `GET /api/songs` - List songs
- `POST /api/songs` - Create song
- `GET /api/songs/{id}` - Get song
- `PATCH /api/songs/{id}` - Update song
- `POST /api/songs/{id}/pause` - Pause song
- `POST /api/songs/{id}/resume` - Resume song
- `GET /api/songs/{id}/eta` - Get completion ETA

### System
- `GET /api/system/capacity` - System capacity info
- `GET /api/system/resources` - Resource usage
- `GET /api/system/health` - Health check

### Settings
- `GET /api/settings` - Get all settings
- `PATCH /api/settings` - Update settings

## Testing

```bash
cd backend
pytest tests/
```

## Production Deployment

On Ubuntu server with Docker:

1. Set `MOCK_DOCKER=false` and `MOCK_ADB=false` in `.env`
2. Build and run with Docker Compose:
   ```bash
   docker-compose up -d
   ```

## WebSocket Events

The `/ws/dashboard` endpoint broadcasts:

- `instance_status` - Instance status changes
- `stream_completed` - Stream completion events
- `alert` - System alerts (warning/error)
