# Getting started on Windows

This guide assumes the tools from the setup guide are installed: Git, uv, Node.js and (optionally) Docker.
All commands go in **PowerShell**, from the project folder (for example `D:\dev\smartagri-fog`).

## First run

```powershell
cd D:\dev\smartagri-fog
git pull
.\scripts\setup.ps1
.\scripts\start.ps1
```

`setup.ps1` installs the Python and web packages, builds the interface and creates your `.env` settings file.
`start.ps1` starts the platform and opens <http://127.0.0.1:8000> in your browser. Press **Ctrl+C** in the
terminal to stop it.

The first `setup.ps1` takes a few minutes; later runs are quick.

## Getting a new version

After a pull request is merged on GitHub, stop the running platform with **Ctrl+C**, then:

```powershell
git checkout main
git pull
.\scripts\start.ps1
```

`start.ps1` notices that the code changed and rebuilds the interface before starting (this adds about a minute).
The **Version** row on the Overview page shows the commit the server and the interface were built from, for
example `173f1fe`. It should match the newest commit on GitHub. If the two values differ, the page shows a warning;
press **Ctrl+Shift+R** to reload without the browser cache.

## Try it

1. Open **Algorithm catalogue** and click **Soil-moisture demo signal**. Its badge says *Simulated* and its
   output is labelled *Synthetic data*.
2. Change a parameter, for example **Days** to 60, and click **Start job**. The job page shows live progress,
   then a chart of the generated series.
3. Switch the top bar to **Researcher** mode to see advanced parameters.
4. Open any page marked with a hollow dot in the sidebar. It explains what the page will do and in which
   phase it arrives. Planned pages and algorithms never produce results.
5. Press **Ctrl+K** to jump to any page or algorithm.

## After every update

When a new pull request has been merged on GitHub:

```powershell
git checkout main
git pull
.\scripts\setup.ps1
```

The database upgrades itself automatically when the platform starts, and your data is kept.

## Where your data lives

| What | Default location | Change it in `.env` |
| --- | --- | --- |
| Database | `data\local\smartagri.db` | `SMARTAGRI_DATA_DIR` |
| Job and experiment results | `data\local\results` | `SMARTAGRI_RESULTS_DIR` |

To keep results on another drive, edit `.env`:

```text
SMARTAGRI_RESULTS_DIR=D:\SmartAgriData\results
```

Both folders are excluded from Git. Back them up separately (see the setup guide's 3-2-1 rule).

## Development mode

When working on the code, `.\scripts\dev.ps1` runs the API with automatic reload in a second window and the
web interface at <http://localhost:5173> with instant updates.

Run every automated check (the same ones GitHub runs on pull requests) with `.\scripts\check.ps1`.

## Command line

The same core is available without the browser:

```powershell
uv run smartagri plugins list
uv run smartagri plugins list --kind scheduler
uv run smartagri plugins show data_generator:soil_moisture_demo
uv run smartagri demo --days 10
```

API documentation is generated automatically at <http://127.0.0.1:8000/docs> while the platform runs.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `uv` or `npm` is not recognized | Close all terminals and open a new one; restart the laptop if needed. |
| `running scripts is disabled` | `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` |
| Port 8000 already in use | Another copy is running. Close it, or run `uv run smartagri-api --port 8010`. |
| The page says "API offline" | The terminal running `start.ps1` was closed or crashed. Start it again and read its last lines. |
| The page looks unchanged after an update | Check the Version row on Overview. Run `git log --oneline -1`; if it is old, `git pull` did not run on `main`. |
| Anything else | Copy the full error text from the terminal and send it to Claude. |
