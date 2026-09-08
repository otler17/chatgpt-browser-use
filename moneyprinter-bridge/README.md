# MoneyPrinterTurbo bridge bundle

This folder runs the upstream `harry0703/MoneyPrinterTurbo` release image plus a small authenticated HTTP bridge.

## Start on Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\setup.ps1
```

The setup script creates `config.toml` from the upstream example, creates `.env` with a random bridge token, pulls the MoneyPrinterTurbo image, builds the bridge, and starts all services.

Local endpoints:

- WebUI: `http://127.0.0.1:8501`
- Native API/docs: `http://127.0.0.1:8080/docs`
- Bridge/docs: `http://127.0.0.1:8787/docs`

## Bridge request format

Use the token from `.env` as either `Authorization: Bearer <token>` or `X-Bridge-Token: <token>`.

Generate a video from a simple prompt:

```json
{
  "action": "video",
  "payload": {"prompt": "A 30-second vertical video about Tunis at sunrise"},
  "wait": false
}
```

Equivalent native parameters can be passed directly:

```json
{
  "action": "video",
  "payload": {
    "video_subject": "Tunis at sunrise",
    "video_aspect": "9:16",
    "video_count": 1
  }
}
```

Check a task:

```json
{"action":"status","task_id":"TASK_ID"}
```

List tasks:

```json
{"action":"tasks"}
```

Pass through another MoneyPrinterTurbo v1 API operation:

```json
{
  "action": "raw",
  "method": "GET",
  "path": "/api/v1/tasks"
}
```

The raw bridge deliberately only accepts paths under `/api/v1/`; it is not an open proxy.

## Important

MoneyPrinterTurbo still needs the provider keys/settings required by the features you use. Edit `config.toml` before expecting full video generation. Keep the bridge on `127.0.0.1` unless you deliberately add authentication, TLS, firewall rules, and a reverse proxy for remote access.

This bridge lets HTTP clients submit and query MoneyPrinterTurbo jobs. It does **not** turn a ChatGPT conversation into a public inbound webhook by itself; that requires a separately connected tool/plugin or exposed service endpoint.
