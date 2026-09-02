"""Nudge: self-hosted sales follow-up agent."""

from __future__ import annotations

import csv
import io
import os
import re
import sqlite3
import smtplib
from datetime import date, datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import formataddr
from pathlib import Path

from flask import (
    Flask,
    Response,
    abort,
    flash,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

APP_ROOT = Path(__file__).resolve().parent
DEFAULT_DB = APP_ROOT / "nudge.db"

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024
app.secret_key = os.environ.get("SECRET_KEY", "nudge-self-hosted-change-me")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def database_path() -> str:
    raw = _env("DATABASE_PATH")
    if raw:
        return raw
    return str(DEFAULT_DB)


def smtp_configured() -> bool:
    return bool(_env("SMTP_HOST"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def get_db() -> sqlite3.Connection:
    db = getattr(g, "_db", None)
    if db is None:
        path = database_path()
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        db = sqlite3.connect(path, timeout=15, check_same_thread=False)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys = ON")
        db.execute("PRAGMA journal_mode = WAL")
        g._db = db
    return db


@app.teardown_appcontext
def close_db(_exc: BaseException | None) -> None:
    db = getattr(g, "_db", None)
    if db is not None:
        db.close()


def init_db() -> None:
    with app.app_context():
        db = get_db()
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS leads (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                email TEXT NOT NULL,
                company TEXT,
                last_touch TEXT,
                notes TEXT,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sequences (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                lead_id INTEGER NOT NULL,
                step INTEGER NOT NULL,
                send_on TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                sent_at TEXT,
                FOREIGN KEY (lead_id) REFERENCES leads(id) ON DELETE CASCADE,
                UNIQUE (lead_id, step)
            );
            CREATE INDEX IF NOT EXISTS idx_leads_status ON leads(status);
            """
        )
        db.commit()


@app.context_processor
def inject_globals() -> dict:
    return {
        "marketing_url": _env("MARKETING_URL"),
        "smtp_configured": smtp_configured(),
        "from_name": _env("FROM_NAME"),
        "from_email": _env("FROM_EMAIL"),
    }


def first_name(name: str) -> str:
    parts = (name or "").strip().split()
    return parts[0] if parts else "there"


def signoff_block() -> str:
    name = _env("FROM_NAME")
    email = _env("FROM_EMAIL")
    if name and email:
        return f"{name}\n{email}"
    if name:
        return name
    if email:
        return email
    return "Your name"


def parse_iso_date(value: str | None) -> date | None:
    raw = (value or "").strip()
    if not raw:
        return None
    raw = raw.replace("/", "-")
    try:
        return date.fromisoformat(raw[:10])
    except ValueError:
        pass
    for fmt in ("%m-%d-%Y", "%d-%m-%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:10], fmt).date()
        except ValueError:
            continue
    return None


def sequence_base_date(lead: sqlite3.Row) -> date:
    parsed = parse_iso_date(lead["last_touch"])
    return parsed or date.today()


def build_sequence_steps(lead: sqlite3.Row) -> list[dict]:
    fn = first_name(lead["name"])
    company = (lead["company"] or "").strip()
    notes = (lead["notes"] or "").strip()
    company_or_you = company if company else "you"
    company_at = f" at {company}" if company else ""
    notes_sentence = ""
    if notes:
        notes_sentence = (
            f" I still have a note from our last conversation: {notes.rstrip('.')}."
        )
    sign = signoff_block()
    base = sequence_base_date(lead)

    if company:
        close_wish = f"I wish you and the team at {company} a smooth few weeks ahead."
        checkin_who = company
    else:
        close_wish = "I wish you a smooth few weeks ahead."
        checkin_who = "you"

    step1_body = (
        f"Hi {fn},\n\n"
        f"I wanted to send a quick, polite follow-up after we last connected{company_at}. "
        f"I know inboxes fill up fast, and I did not want our conversation to slip away.{notes_sentence} "
        f"If now is still a reasonable time, I would be glad to continue and keep this simple. "
        f"I can answer questions, share a short recap, or wait until the timing is better for you. "
        f"Thank you for considering this — I appreciate your time.\n\n"
        f"Best regards,\n{sign}"
    )
    step2_body = (
        f"Hi {fn},\n\n"
        f"I am checking in with {checkin_who} in case a follow-up would still be useful. "
        f"Since we last spoke, I have been thinking about how to make the next step as easy as possible for you. "
        f"The value I hoped to offer is a clear path forward: a short conversation, a tailored suggestion, "
        f"or help with whatever is sitting on your plate. "
        f"If it would help, I can send a one-page recap or jump on a brief call this week. "
        f"There is no urgency on my side; I just want to be available if {company_or_you} could use a hand. "
        f"What would be most useful from here?\n\n"
        f"Warmly,\n{sign}"
    )
    step3_body = (
        f"Hi {fn},\n\n"
        f"This will be my last note for now so I do not clutter your inbox. "
        f"I remain grateful for the time you already gave this, and the door stays open if you want to pick it up later. "
        f"If the timing was simply off, that is completely okay. "
        f"Whenever you are ready, reply to this email and I will gladly continue the conversation{company_at}. "
        f"{close_wish} "
        f"Thank you again.\n\n"
        f"All the best,\n{sign}"
    )

    return [
        {
            "step": 1,
            "send_on": (base + timedelta(days=0)).isoformat(),
            "subject": f"Quick follow-up, {fn}",
            "body": step1_body,
        },
        {
            "step": 2,
            "send_on": (base + timedelta(days=3)).isoformat(),
            "subject": f"Checking in with {company_or_you}",
            "body": step2_body,
        },
        {
            "step": 3,
            "send_on": (base + timedelta(days=7)).isoformat(),
            "subject": f"Last note from me, {fn}",
            "body": step3_body,
        },
    ]


EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def valid_email(value: str) -> bool:
    return bool(EMAIL_RE.match((value or "").strip()))


def get_lead(lead_id: int) -> sqlite3.Row | None:
    return get_db().execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()


def get_sequence(lead_id: int) -> list[sqlite3.Row]:
    return get_db().execute(
        "SELECT * FROM sequences WHERE lead_id = ? ORDER BY step ASC",
        (lead_id,),
    ).fetchall()


def save_sequence(lead_id: int, steps: list[dict], replace: bool = False) -> None:
    db = get_db()
    if replace:
        db.execute("DELETE FROM sequences WHERE lead_id = ?", (lead_id,))
    for step in steps:
        db.execute(
            """
            INSERT INTO sequences (lead_id, step, send_on, subject, body, sent_at)
            VALUES (?, ?, ?, ?, ?, NULL)
            """,
            (lead_id, step["step"], step["send_on"], step["subject"], step["body"]),
        )
    db.commit()


def sequence_export_text(lead: sqlite3.Row, steps: list[sqlite3.Row]) -> str:
    last_touch = lead["last_touch"] or "(none — used today as Day 0)"
    lines = [
        f"Nudge follow-up sequence for {lead['name']} <{lead['email']}>" ,
        f"Company: {lead['company'] or '(none)'}",
        f"Last touch: {last_touch}",
        f"Status: {lead['status']}",
        "",
    ]
    for step in steps:
        sent = f"sent {step['sent_at']}" if step["sent_at"] else "not sent"
        lines.extend(
            [
                f"--- Step {step['step']} (send on {step['send_on']}, {sent}) ---",
                f"Subject: {step['subject']}",
                "",
                step["body"],
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def send_smtp(to_email: str, subject: str, body: str) -> None:
    host = _env("SMTP_HOST")
    if not host:
        raise RuntimeError("SMTP is not configured.")
    from_email = _env("FROM_EMAIL")
    if not from_email:
        raise RuntimeError("FROM_EMAIL is required to send mail.")
    port = int(_env("SMTP_PORT") or "587")
    user = _env("SMTP_USER")
    password = os.environ.get("SMTP_PASSWORD", "")
    tls_raw = _env("SMTP_TLS") or "true"
    use_tls = tls_raw.lower() in {"1", "true", "yes", "on"}
    from_name = _env("FROM_NAME")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, from_email)) if from_name else from_email
    msg["To"] = to_email
    msg.set_content(body)

    with smtplib.SMTP(host, port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls()
        if user:
            smtp.login(user, password)
        smtp.send_message(msg)


def normalize_csv_header(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().lower().replace("_", " ").replace("-", " "))


HEADER_MAP = {
    "name": "name",
    "full name": "name",
    "email": "email",
    "e mail": "email",
    "company": "company",
    "organization": "company",
    "last touch": "last_touch",
    "last touch date": "last_touch",
    "lasttouch": "last_touch",
    "last touchdate": "last_touch",
    "notes": "notes",
    "note": "notes",
}


def map_csv_row(row: dict) -> dict | None:
    mapped: dict[str, str] = {}
    for key, value in row.items():
        field = HEADER_MAP.get(normalize_csv_header(key or ""))
        if field:
            mapped[field] = (value or "").strip()
    name = mapped.get("name", "")
    email = mapped.get("email", "")
    if not name or not valid_email(email):
        return None
    last_touch_raw = mapped.get("last_touch", "")
    parsed = parse_iso_date(last_touch_raw) if last_touch_raw else None
    return {
        "name": name,
        "email": email,
        "company": mapped.get("company", ""),
        "last_touch": parsed.isoformat() if parsed else ("" if not last_touch_raw else None),
        "notes": mapped.get("notes", ""),
    }


def insert_lead(data: dict, status: str = "new") -> int:
    db = get_db()
    cur = db.execute(
        """
        INSERT INTO leads (name, email, company, last_touch, notes, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            data["name"],
            data["email"],
            data.get("company") or None,
            data.get("last_touch") or None,
            data.get("notes") or None,
            status,
            utc_now_iso(),
        ),
    )
    db.commit()
    return int(cur.lastrowid)


@app.get("/health")
def health() -> Response:
    return jsonify({"status": "ok", "smtp_configured": smtp_configured()})


@app.get("/")
def index() -> str:
    status = (request.args.get("status") or "").strip().lower()
    db = get_db()
    if status in {"new", "contacted", "skipped", "replied"}:
        leads = db.execute(
            "SELECT * FROM leads WHERE status = ? ORDER BY id DESC",
            (status,),
        ).fetchall()
    else:
        status = ""
        leads = db.execute("SELECT * FROM leads ORDER BY id DESC").fetchall()
    counts_rows = db.execute(
        "SELECT status, COUNT(*) AS n FROM leads GROUP BY status"
    ).fetchall()
    counts = {row["status"]: row["n"] for row in counts_rows}
    counts["all"] = sum(counts.values())
    return render_template("index.html", leads=leads, status=status, counts=counts)


@app.post("/leads")
def create_lead():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    company = (request.form.get("company") or "").strip()
    last_touch_raw = (request.form.get("last_touch") or "").strip()
    notes = (request.form.get("notes") or "").strip()
    if not name or not valid_email(email):
        flash("Name and a valid email are required.", "error")
        return redirect(url_for("index"))
    parsed = parse_iso_date(last_touch_raw) if last_touch_raw else None
    if last_touch_raw and parsed is None:
        flash("Last touch must be an ISO date (YYYY-MM-DD).", "error")
        return redirect(url_for("index"))
    lead_id = insert_lead(
        {
            "name": name,
            "email": email,
            "company": company,
            "last_touch": parsed.isoformat() if parsed else "",
            "notes": notes,
        }
    )
    flash("Lead added.", "ok")
    return redirect(url_for("lead_detail", lead_id=lead_id))


@app.post("/leads/import")
def import_leads():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose a CSV file to import.", "error")
        return redirect(url_for("index"))
    raw = upload.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        flash("CSV is missing a header row.", "error")
        return redirect(url_for("index"))
    imported = 0
    skipped = 0
    for row in reader:
        mapped = map_csv_row(row)
        if mapped is None or mapped.get("last_touch") is None:
            skipped += 1
            continue
        insert_lead(mapped)
        imported += 1
    flash(f"Imported {imported} lead(s), skipped {skipped} row(s).", "ok")
    return redirect(url_for("index"))


@app.get("/leads/<int:lead_id>")
def lead_detail(lead_id: int) -> str:
    lead = get_lead(lead_id)
    if lead is None:
        abort(404)
    steps = get_sequence(lead_id)
    return render_template("lead.html", lead=lead, steps=steps)


@app.post("/leads/<int:lead_id>/generate")
def generate_sequence(lead_id: int):
    lead = get_lead(lead_id)
    if lead is None:
        abort(404)
    existing = get_sequence(lead_id)
    if existing:
        flash("A sequence already exists. Use regenerate to replace it.", "ok")
        return redirect(url_for("lead_detail", lead_id=lead_id))
    save_sequence(lead_id, build_sequence_steps(lead), replace=False)
    flash("Generated a 3-step follow-up sequence.", "ok")
    return redirect(url_for("lead_detail", lead_id=lead_id))


@app.post("/leads/<int:lead_id>/regenerate")
def regenerate_sequence(lead_id: int):
    lead = get_lead(lead_id)
    if lead is None:
        abort(404)
    save_sequence(lead_id, build_sequence_steps(lead), replace=True)
    flash("Sequence regenerated. Previous send timestamps were cleared.", "ok")
    return redirect(url_for("lead_detail", lead_id=lead_id))


@app.get("/leads/<int:lead_id>/export.txt")
def export_sequence(lead_id: int):
    lead = get_lead(lead_id)
    if lead is None:
        abort(404)
    steps = get_sequence(lead_id)
    if not steps:
        flash("Generate a sequence before exporting.", "error")
        return redirect(url_for("lead_detail", lead_id=lead_id))
    safe = re.sub(r"[^a-zA-Z0-9]+", "-", lead["name"]).strip("-").lower() or "lead"
    text = sequence_export_text(lead, steps)
    return Response(
        text,
        mimetype="text/plain; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="nudge-{safe}-sequence.txt"'},
    )


@app.post("/leads/<int:lead_id>/status")
def update_status(lead_id: int):
    lead = get_lead(lead_id)
    if lead is None:
        abort(404)
    status = (request.form.get("status") or "").strip().lower()
    if status not in {"new", "contacted", "skipped", "replied"}:
        flash("Unknown status.", "error")
        return redirect(url_for("lead_detail", lead_id=lead_id))
    db = get_db()
    db.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))
    db.commit()
    flash(f"Marked as {status}.", "ok")
    return redirect(url_for("lead_detail", lead_id=lead_id))


def _send_steps(lead: sqlite3.Row, steps: list[sqlite3.Row]) -> tuple[int, str | None]:
    if not smtp_configured():
        return 0, "SMTP is not configured. Copy or export the sequence instead."
    sent = 0
    db = get_db()
    for step in steps:
        if step["sent_at"]:
            continue
        try:
            send_smtp(lead["email"], step["subject"], step["body"])
        except Exception as exc:  # noqa: BLE001 — surface SMTP errors in the UI
            app.logger.warning("SMTP send failed for lead_id=%s step=%s: %s", lead["id"], step["step"], type(exc).__name__)
            return sent, f"SMTP send failed on step {step['step']}: {exc}"
        db.execute(
            "UPDATE sequences SET sent_at = ? WHERE id = ?",
            (utc_now_iso(), step["id"]),
        )
        sent += 1
    if sent:
        db.execute("UPDATE leads SET status = ? WHERE id = ? AND status = ?", ("contacted", lead["id"], "new"))
    db.commit()
    return sent, None


@app.post("/leads/<int:lead_id>/send")
def send_unsent(lead_id: int):
    lead = get_lead(lead_id)
    if lead is None:
        abort(404)
    steps = get_sequence(lead_id)
    if not steps:
        flash("Generate a sequence before sending.", "error")
        return redirect(url_for("lead_detail", lead_id=lead_id))
    sent, err = _send_steps(lead, steps)
    if err:
        flash(err, "error")
    elif sent == 0:
        flash("Nothing to send — every step was already sent.", "ok")
    else:
        flash(f"Sent {sent} email(s).", "ok")
    return redirect(url_for("lead_detail", lead_id=lead_id))


@app.post("/leads/<int:lead_id>/steps/<int:step>/send")
def send_one_step(lead_id: int, step: int):
    lead = get_lead(lead_id)
    if lead is None:
        abort(404)
    row = get_db().execute(
        "SELECT * FROM sequences WHERE lead_id = ? AND step = ?",
        (lead_id, step),
    ).fetchone()
    if row is None:
        flash("That step does not exist yet.", "error")
        return redirect(url_for("lead_detail", lead_id=lead_id))
    sent, err = _send_steps(lead, [row])
    if err:
        flash(err, "error")
    elif sent == 0:
        flash("That step was already sent.", "ok")
    else:
        flash(f"Sent step {step}.", "ok")
    return redirect(url_for("lead_detail", lead_id=lead_id))


@app.errorhandler(404)
def not_found(_e):
    return render_template("404.html"), 404


init_db()


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(_env("PORT") or "8080"))
