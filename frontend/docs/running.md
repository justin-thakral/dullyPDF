# Running the UI

## From repo root

```bash
npm run start sandbox
```

This uses the existing start script and launches the sandbox UI dev server.

## From the sandbox UI folder

```bash
cd "sandbox UI"
npm install
npm run start
```

Vite will use the next available port (typically `http://localhost:5174` if `5173` is already in use).

## Optional overrides

- Use `npm run build` to produce a production build.
- Use `npm run preview` to serve the production bundle locally.
