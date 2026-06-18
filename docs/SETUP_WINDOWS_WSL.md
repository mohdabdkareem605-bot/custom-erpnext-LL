# Windows and WSL Development Setup

## Current machine status

At the time this repository was scaffolded:

- Git is installed.
- WSL is not installed.
- Docker is not installed.
- Bench is not installed.
- Native Node.js and Python development runtimes are not installed.

## 1. Install WSL 2

Open **PowerShell as Administrator**:

```powershell
wsl --install -d Ubuntu-24.04
```

Restart Windows when requested, open Ubuntu, and create the Linux user.

## 2. Keep source here, keep the bench in Linux

This app source remains at:

```text
C:\Users\MohammedAbdulKareem\Downloads\Lifeline-ERPNEXT
```

Inside WSL the same directory is:

```text
/mnt/c/Users/MohammedAbdulKareem/Downloads/Lifeline-ERPNEXT
```

Create the Frappe bench under the Linux home directory, for example:

```text
~/frappe-bench
```

Do not create the complete bench under `/mnt/c`; database, Redis, file watching
and filesystem permissions are more reliable in the WSL Linux filesystem.

## 3. Install system dependencies

After WSL is installed, follow the official Frappe v15 installation guide for
Ubuntu. Install MariaDB, Redis, Python 3.12 development tools, Node.js 20, Yarn,
wkhtmltopdf, Git and build dependencies.

## 4. Create the bench and site

The repository includes an assisted script:

```bash
cd /mnt/c/Users/MohammedAbdulKareem/Downloads/Lifeline-ERPNEXT
chmod +x scripts/setup_bench.sh
./scripts/setup_bench.sh
```

The script intentionally asks for site/database passwords interactively. Do not
commit passwords to `.env` or shell scripts.

## 5. Daily development

From Ubuntu:

```bash
cd ~/frappe-bench
bench start
```

Open:

```text
http://lifeline.localhost:8000
```

After changing Python, JavaScript or DocType definitions:

```bash
bench --site lifeline.localhost migrate
bench build --app lifeline_tpa
bench --site lifeline.localhost clear-cache
```

