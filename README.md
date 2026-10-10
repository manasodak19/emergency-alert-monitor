<div align="center">

<br>

# ◈ EMERGENCY ALERT MONITOR

### When the signal matters, silence is not an option.

**A real-time backend reliability watchdog for emergency alert systems.**
Accept alerts. Watch the logs. Catch the failure before it becomes the story.

<br>

[![Python](https://img.shields.io/badge/Python-3.x-111827?style=for-the-badge&logo=python&logoColor=FFD43B)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0.3-111827?style=for-the-badge&logo=flask&logoColor=white)](https://flask.palletsprojects.com/)
[![SQLite](https://img.shields.io/badge/SQLite-persistent%20storage-111827?style=for-the-badge&logo=sqlite&logoColor=74B9FF)](https://www.sqlite.org/)
[![Tests](https://img.shields.io/badge/Tests-pytest-111827?style=for-the-badge&logo=pytest&logoColor=9FE870)](https://pytest.org/)

<br>

**[GET STARTED](#-get-started)** &nbsp;·&nbsp;
**[API](#-the-api)** &nbsp;·&nbsp;
**[SIMULATE AN INCIDENT](#-pull-the-alarm)** &nbsp;·&nbsp;
**[CONTRIBUTING](#-the-crew)**

<br>

</div>

---

<div align="center">

```text
  ┌──────────────────┐       ┌───────────────────┐       ┌────────────────────┐
  │  ALERT INGRESS   │──────▶│  LOG + METRICS    │──────▶│  ANOMALY DETECTION │
  │  Flask REST API  │       │  Structured logs  │       │  Rule-based checks │
  └──────────────────┘       └───────────────────┘       └─────────┬──────────┘
           │                                                        │
           ▼                                                        ▼
  ┌──────────────────┐                                  ┌────────────────────┐
  │   SQLite store   │                                  │  LIVE DASHBOARD    │
  │   Alerts + history│                                  │  Status + signals  │
  └──────────────────┘                                  └────────────────────┘
```

</div>

## ◉ The mission

Emergency systems are only as dependable as the infrastructure behind them. **Emergency Alert Monitor** is a Flask-based monitoring service that receives alerts, persists them in SQLite, records structured operational logs, calculates reliability metrics, and flags suspicious activity with configurable rules.

It also includes safe, on-demand failure simulations—so you can see the monitoring pipeline react without taking down real infrastructure.

> **Heads up:** This is a monitoring and demonstration project. It does not dispatch real-world emergency notifications.

## ✦ At a glance

| Capability | What it does |
|:--|:--|
| **Alert intake** | Validates incoming JSON, assigns a UUID, and stores the alert in SQLite |
| **Live operations dashboard** | Displays system health, metrics, anomalies, and recent activity; refreshes every 3 seconds |
| **Log intelligence** | Aggregates log levels, operational error categories, response times, and severity scores |
| **Anomaly detection** | Classifies metrics as `NORMAL`, `WARNING`, or `ANOMALY` using configurable thresholds |
| **Incident simulations** | Generates realistic database, broadcast, notification, HTTP, sensor, and outage events |
| **Controlled DB failure** | Simulates a temporary database outage for alert writes, with an explicit recovery endpoint |
| **Persistent records** | Stores alerts and anomaly history in a local SQLite database |

## ◉ Get started

### 1 · Create an environment

```powershell
git clone https://github.com/manasodak19/emergency-alert-monitor.git
cd emergency-alert-monitor

py -m venv .venv
.\.venv\Scripts\Activate.ps1
```

If PowerShell blocks virtual-environment activation, allow it for the current terminal session:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

### 2 · Install dependencies

```powershell
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 3 · Start the monitor

```powershell
python app.py
```

The service starts at **http://localhost:5000**. Open **http://localhost:5000/dashboard** for the live dashboard.

> The database is initialized automatically. By default, SQLite writes to `data/alerts.db`; set `ALERT_DB_PATH` to use a different location.

### 4 · Run the tests

```powershell
python -m pytest
```

## ◉ The API

All responses are JSON unless the route serves the dashboard page.

| Method | Endpoint | Purpose |
|:--|:--|:--|
| `GET` | `/` | Service welcome and running status |
| `GET` | `/health` | Health check |
| `POST` | `/alert` | Validate and save an alert |
| `GET` | `/metrics` | Return log metrics; optional `?window=<seconds>` |
| `GET` | `/anomalies` | Run threshold checks; optional `?window=<seconds>` |
| `GET` | `/dashboard` | Open the live monitoring dashboard |
| `GET` | `/api/status` | Dashboard status and metrics payload |
| `GET` | `/api/alerts?limit=20` | Retrieve recent stored alerts (`limit` is clamped to 1–100) |

### Send an alert

```powershell
curl.exe -X POST http://localhost:5000/alert `
  -H "Content-Type: application/json" `
  -d '{ "type": "weather", "message": "Severe storm warning", "location": "North District" }'
```

Required fields: `type`, `message`, and `location`.

### Inspect the signal

```powershell
curl.exe http://localhost:5000/health
curl.exe "http://localhost:5000/metrics?window=300"
curl.exe "http://localhost:5000/anomalies?window=300"
curl.exe "http://localhost:5000/api/alerts?limit=10"
```

## ◉ Pull the alarm

Simulation routes are `POST`-only and live under `/simulate`. Where supported, pass a `count` in the query string or JSON body; generated counts are capped at 50.

| Endpoint | Scenario |
|:--|:--|
| `/simulate/database-failure` | Generates database errors and activates a 60-second simulated write outage |
| `/simulate/database-recover` | Immediately ends the simulated database outage |
| `/simulate/broadcast-failure` | Generates broadcast-channel delivery failures |
| `/simulate/notification-delay` | Generates delayed notification batches and SLA breaches |
| `/simulate/http-500` | Generates HTTP 500 error logs |
| `/simulate/sensor-malfunction` | Generates out-of-range sensor readings |
| `/simulate/full-outage` | Generates a cascading system-outage event |

Try a simulation:

```powershell
curl.exe -X POST "http://localhost:5000/simulate/broadcast-failure?count=8"
curl.exe -X POST http://localhost:5000/simulate/full-outage
```

Watch the dashboard at **http://localhost:5000/dashboard**, or inspect `/metrics` and `/anomalies` to see the resulting signal.

To test database recovery, trigger `/simulate/database-failure`, then send an alert. Alert writes will fail while the simulation is active. Restore writes immediately with:

```powershell
curl.exe -X POST http://localhost:5000/simulate/database-recover
```

## ◉ Under the hood

```text
emergency-alert-monitor/
├── anomaly_detection/   Rule-based metric checks
├── config/              Database settings and anomaly thresholds
├── dashboard/           Dashboard HTML, CSS, and live-refresh JavaScript
├── database/            SQLite setup and alert persistence
├── logging_system/      Structured logger, parser, and metric aggregation
├── routes/              Dashboard and incident-simulation routes
├── tests/               Dashboard, database, and anomaly tests
├── app.py               Flask app and core API
└── requirements.txt     Project dependencies
```

**Logs** are written to `logs/app.log` and mirrored to the console. The log format is designed for the project's parser. **Runtime data** lives under `data/`; generated logs and the SQLite database are excluded from Git.

Thresholds and human-readable anomaly reasons live in [`config/config.py`](config/config.py). Metrics are grouped into a time window when `?window=<seconds>` is provided.

## ◉ The crew

The project team collaborates through one shared integration branch and four member branches:

| Branch | Teammate |
|:--|:--|
| `main` | Integration |
| `manas` | Manas |
| `anushka` | Anushka |
| `atharva` | Atharva |
| `shreya` | Shreya |

To start work on your branch:

```powershell
git switch manas
```

Replace `manas` with your branch name. Push your work with `git push -u origin <branch-name>`, then open a pull request into `main`.

## ◉ Built for the moment before

**Detect early. Respond clearly. Keep the signal alive.**

<div align="center">

*Emergency Alert Monitor · Group 4*

</div>
