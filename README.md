# Nudge

Free, self-hosted sales follow-up for small business owners. Add your leads, generate a three-step email sequence, then copy it, export it, or optionally send it through your own email server.

No signup. No license. One Docker app and a SQLite file on a machine you control. Plan on about 15 minutes.

## What you get

- A simple web page for leads (name, email, company, last touch date, notes), including CSV import
- A 3-step follow-up per lead (subject + body), spaced Day 0 / Day 3 / Day 7 from last touch (or today if last touch is empty)
- Copy each step, copy all, or export as a `.txt` file. You do not need email sending set up to use this
- Optional SMTP send for one step or all unsent steps, using **your** mail server
- Mark leads contacted, skipped, or replied

Sequences come from templates (no AI). The sign-off uses `FROM_NAME` / `FROM_EMAIL` when you set them, otherwise `Your name`.

## What you need

- A small VPS (about 1GB RAM is enough)
- **Ubuntu 22.04 or 24.04** is the documented install. Debian 13 is covered with a different Docker package set below. Amazon Linux is not documented in this README yet
- Port 8080 open to you (and to the internet only if you want the UI reachable from outside)

## 15-minute install (Ubuntu 22.04 / 24.04)

### 1. Install Docker Engine and Compose

This recipe is for Ubuntu. Do not run it unchanged on Debian or Amazon Linux.

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo ${UBUNTU_CODENAME:-$VERSION_CODENAME}) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo usermod -aG docker "$USER"
```

Log out and back in (or run `newgrp docker`) so `docker` works without `sudo`.

### 2. Clone, configure, start

```bash
git clone https://github.com/aidendify/nudge-followup.git
cd nudge-followup
cp .env.example .env
# optional: set FROM_NAME, FROM_EMAIL, SMTP_* in .env
# leave MARKETING_URL empty
docker compose up --build -d
```

The app listens on port 8080. Data lives in a Docker volume (`nudge-data`) at `/data/nudge.db` inside the container.

If the image build fails with a 502 from debian.org while installing `curl`, wait a minute and run `docker compose up --build -d` again.

### 3. Smoke test

1. Health check (SMTP does not need to be configured):

   ```bash
   curl -sf http://localhost:8080/health
   ```

   You should get HTTP 200 and JSON like:

   ```json
   {"smtp_configured":false,"status":"ok"}
   ```

   Key order may vary. `smtp_configured` is `true` only when `SMTP_HOST` is set.

2. In a browser, open http://localhost:8080 (or `http://YOUR_SERVER_IP:8080`). Click **Import CSV** and choose `sample-leads.csv` from this repo. Do not `curl -L` the import URL. It redirects and then rejects the upload.

3. Open a lead, click **Generate sequence**, then copy a step or **Export as .txt**. SMTP is not required for this.

## Debian 13

Use Debian's `docker.io` and `docker-compose` packages, not the Ubuntu `docker-ce` recipe above.

```bash
sudo apt-get update
sudo apt-get install -y git ca-certificates docker.io docker-compose
sudo usermod -aG docker "$USER"
sudo systemctl enable --now docker
```

Log out and back in (or `newgrp docker`), then:

```bash
git clone https://github.com/aidendify/nudge-followup.git
cd nudge-followup
cp .env.example .env
docker-compose up --build -d
```

Smoke test is the same as Ubuntu (health JSON, browser CSV import, generate a sequence).

## Amazon Linux

Amazon Linux install steps are not in this README yet. Use Ubuntu 22.04/24.04 or Debian 13 for now.

## Configuration

Copy `.env.example` to `.env` before starting. Do not commit `.env`.

| Variable | Purpose |
| --- | --- |
| `PORT` | Documented as 8080. The container always binds to `0.0.0.0:8080`. |
| `DATABASE_PATH` | SQLite file. Compose overrides this to `/data/nudge.db`. |
| `SECRET_KEY` | Change this on any VPS that is reachable from the internet. |
| `FROM_NAME`, `FROM_EMAIL` | Sequence sign-off and SMTP From header. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_TLS` | Optional send. If `SMTP_HOST` is unset, send buttons are hidden. |
| `MARKETING_URL` | If set, a footer link **Powered by Nudge** points here. Leave empty for no footer. |

SMTP passwords are never written to application logs.

## CSV import

Use **Import CSV** in the browser. Header row required. Columns recognized (case-insensitive):

- `name` (required)
- `email` (required)
- `company`
- `last_touch` or `last touch date`
- `notes`

Rows missing a name or a valid email are skipped. Unparseable dates are skipped. The import message reports how many rows were imported vs skipped.

Do not import by running `curl -L` against the import URL. Follow the redirect and the server returns 405. If you must use curl, POST the file to the import endpoint without following a GET redirect onto a POST-only route. The browser button is the supported path.

## Sequence templates

| Step | Send on | Subject |
| --- | --- | --- |
| 1 | Day 0 | `Quick follow-up, {first_name}` |
| 2 | Day 3 | `Checking in with {company_or_you}` |
| 3 | Day 7 | `Last note from me, {first_name}` |

If a sequence already exists, it is shown; generating again replaces it (including clearing send timestamps).

## Healthcheck

`GET /health` returns HTTP 200 even when SMTP is unset:

```json
{"status":"ok","smtp_configured":false}
```

## Troubleshooting

- **Image build 502 from debian.org:** retry `docker compose up --build -d` (or `docker-compose` on Debian).
- **CSV import via curl fails:** use the browser **Import CSV** button.
- **Export `.txt` Content-Type shows charset twice:** cosmetic; the file is fine.

## Local development (optional)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export DATABASE_PATH=./nudge.db
python app.py
```

Then open http://localhost:8080. This path is for hacking on the code. The supported install is Docker Compose.

## What this is not

Nudge does not scrape inboxes, host a license server, take payments, or run as multi-tenant SaaS. It is a single Compose service you run yourself.
