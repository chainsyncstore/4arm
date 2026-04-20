# 4ARM Dashboard

A 7-page React dashboard for managing a Spotify streaming farm management platform called 4ARM.

## Features

- **Overview Dashboard** - Real-time stats, instance status, resource monitoring, active songs
- **Instances Management** - Create, start, stop, destroy Android emulator instances
- **Accounts Management** - Spotify account lifecycle management with batch operations
- **Songs Management** - Track songs for streaming with progress tracking
- **Proxies Management** - Proxy pool management with health checking
- **Stream Logs** - Filterable streaming logs with statistics
- **System Settings** - Configuration management for all system parameters

## Tech Stack

- React 18 with TypeScript
- Vite build tool
- TailwindCSS 3 with dark theme
- shadcn/ui component library
- Lucide React icons
- Recharts for charts (optional)
- React Router v6
- TanStack Query (React Query) for API state management
- Native WebSocket for real-time updates
- sonner for toast notifications
- Axios for API client

## Prerequisites

- Node.js 18+ 
- npm or yarn
- Backend API running at `http://localhost:8000`

## Installation

```bash
# Install dependencies
npm install

# Start development server
npm run dev
```

The dashboard will be available at `http://localhost:5173`

## Build for Production

```bash
npm run build
```

## Docker Production Deployment

```bash
# Build Docker image
docker build -t 4arm-dashboard .

# Run with docker-compose (see docker-compose.yml)
docker-compose up -d
```

## Development Proxy Configuration

The Vite dev server proxies API calls to the backend:

- `/api/*` → `http://localhost:8000/api/*`
- `/ws/*` → `ws://localhost:8000/ws/*`

Configured in `vite.config.ts`.

## Project Structure

```
frontend/
├── src/
│   ├── api/           # API client modules
│   ├── components/    # React components
│   │   ├── layout/    # Layout components (Sidebar, Layout)
│   │   ├── shared/    # Shared components (StatusBadge)
│   │   └── ui/        # shadcn/ui components
│   ├── contexts/      # React contexts (WebSocketContext)
│   ├── hooks/         # TanStack Query hooks
│   ├── lib/           # Utilities
│   ├── pages/         # Page components
│   ├── types/         # TypeScript types
│   ├── App.tsx        # Main app component
│   ├── main.tsx       # Entry point
│   └── index.css      # Global styles
├── public/            # Static assets
├── Dockerfile         # Production Docker build
├── nginx.conf         # Nginx configuration
└── package.json
```

## Environment Variables

None required for basic operation. The dashboard expects the backend at `http://localhost:8000` during development.

## Real-time Updates

WebSocket connection at `ws://localhost:8000/ws/dashboard` provides:
- Instance status updates
- Stream completion events
- System alerts

## License

MIT
