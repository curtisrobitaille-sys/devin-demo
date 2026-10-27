"""Devin Sherrington — Fat Loss Coach. Sales-demo web app.

Self-contained: Flask + sqlite3 only. No email, no push, no third-party APIs.
Seed data is created on first boot (only when the tables are empty).
Run:  python app.py            (uses $PORT or 5000)
  or: gunicorn app:app
"""
import os
import random
import sqlite3
from datetime import date, timedelta

from flask import (Flask, abort, flash, g, redirect, render_template,
                   request, session, url_for)

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "demo.db")

app = Flask(__name__)
app.secret_key = "devin-demo-only-not-a-real-secret"

DEMO_CLIENT_NAME = "Sarah M."  # the client-view identity


# ---------------------------------------------------------------- db helpers
def db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def _close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        );
        CREATE TABLE IF NOT EXISTS checkins (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL REFERENCES clients(id),
            day       TEXT NOT NULL,
            weight    REAL NOT NULL,
            food      INTEGER NOT NULL,
            steps     INTEGER NOT NULL,
            water     INTEGER NOT NULL,
            sleep     REAL NOT NULL,
            energy    INTEGER NOT NULL,
            note      TEXT DEFAULT '',
            UNIQUE (client_id, day)
        );
        """
    )
    conn.commit()
    if conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0:
        seed(conn)
    conn.close()


# ---------------------------------------------------------------- seed data
# (name, start_weight, daily_trend, skip_offsets) — offsets are days-ago skipped
ROSTER = [
    ("Sarah M.",   184.0, -0.45, {0}),          # demo client: not checked in today yet
    ("Jessica T.", 198.0, -0.55, set()),        # 14-day streak, checked in today
    ("Amanda R.",  172.0, -0.30, {7, 8}),
    ("Melissa K.", 205.0, -0.35, {4, 5, 6}),
    ("Nicole B.",  168.0, -0.40, {10, 11}),
    ("Emily S.",   190.0, -0.28, {6, 7}),
    ("Rachel D.",  176.0, -0.50, {12}),
    ("Mike H.",    232.0, -0.33, {3, 4}),
]

NOTES = [
    "Busy day — prepped lunches for the week.",
    "Got my walk in after the kids' bedtime.",
    "Pizza night with the family. Tracked it, no guilt.",
    "Tired this morning but energy picked up by lunch.",
    "Meal prep Sunday paid off today.",
    "Restaurant lunch — made the lighter pick.",
    "Early workout before work. Felt strong.",
    "",
    "Steps were low, meetings all day. Back at it tomorrow.",
    "",
]


def seed(conn):
    today = date.today()
    for idx, (name, start_w, trend, skips) in enumerate(ROSTER):
        cur = conn.execute("INSERT INTO clients (name) VALUES (?)", (name,))
        cid = cur.lastrowid
        rng = random.Random(1000 + idx)
        weight = start_w
        for ago in range(13, -1, -1):  # 14 days ending today
            if ago in skips:
                continue
            day = today - timedelta(days=ago)
            day_index = 13 - ago
            if day_index > 0:
                weight += trend + rng.uniform(-0.35, 0.35)
            steps = int(rng.choice(
                [rng.randint(4500, 7500), rng.randint(7000, 9800),
                 rng.randint(9800, 11500)]))
            conn.execute(
                """INSERT OR REPLACE INTO checkins
                   (client_id, day, weight, food, steps, water, sleep, energy, note)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cid, day.isoformat(), round(weight, 1),
                 rng.randint(5, 9), steps, rng.randint(4, 9),
                 round(rng.uniform(5.8, 8.4), 1), rng.randint(5, 9),
                 rng.choice(NOTES)),
            )
    conn.commit()


# ---------------------------------------------------------------- domain logic
def get_client(name):
    return db().execute("SELECT * FROM clients WHERE name = ?", (name,)).fetchone()


def client_checkins(client_id):
    return db().execute(
        "SELECT * FROM checkins WHERE client_id = ? ORDER BY day ASC",
        (client_id,),
    ).fetchall()


def streak_for(rows):
    """Consecutive checked-in days ending today (or yesterday if today is
    still outstanding — the day isn't over yet)."""
    days = {r["day"] for r in rows}
    today = date.today()
    cursor = today if today.isoformat() in days else today - timedelta(days=1)
    streak = 0
    while cursor.isoformat() in days:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def weight_stats(rows):
    if not rows:
        return None, None, 0.0
    start = rows[0]["weight"]
    now = rows[-1]["weight"]
    return start, now, round(start - now, 1)


def badges_for(rows):
    start, _now, lost = weight_stats(rows)
    streak = streak_for(rows)
    by_day = {r["day"]: r for r in rows}
    perfect = False
    if rows:
        first = date.fromisoformat(rows[0]["day"])
        last = date.fromisoformat(rows[-1]["day"])
        d = first
        run = 0
        while d <= last:
            r = by_day.get(d.isoformat())
            if r and r["steps"] >= 10000:
                run += 1
                if run >= 7:
                    perfect = True
                    break
            else:
                run = 0
            d += timedelta(days=1)
    return [
        {"name": "First check-in", "icon": "✓", "earned": len(rows) > 0,
         "hint": "Log your first daily check-in"},
        {"name": "7-day streak", "icon": "🔥", "earned": streak >= 7,
         "hint": "Check in 7 days in a row"},
        {"name": "Down 5 lbs", "icon": "⚖️", "earned": lost >= 5.0,
         "hint": "Lose your first 5 lbs"},
        {"name": "Perfect week", "icon": "⭐", "earned": perfect,
         "hint": "7 straight days of 10,000+ steps"},
    ]


def sparkline_points(rows, width=340, height=96, pad=10):
    weights = [r["weight"] for r in rows]
    if len(weights) < 2:
        return "", []
    lo, hi = min(weights), max(weights)
    span = (hi - lo) or 1.0
    pts = []
    step = (width - 2 * pad) / (len(weights) - 1)
    for i, w in enumerate(weights):
        x = pad + i * step
        y = pad + (hi - w) / span * (height - 2 * pad)
        pts.append((round(x, 1), round(y, 1)))
    return " ".join(f"{x},{y}" for x, y in pts), pts


def pretty_day(iso):
    d = date.fromisoformat(iso)
    if d == date.today():
        return "Today"
    if d == date.today() - timedelta(days=1):
        return "Yesterday"
    return d.strftime("%a, %b %d")


# ---------------------------------------------------------------- routes
@app.route("/")
def landing():
    session["visited"] = True
    return render_template("landing.html")


@app.route("/client")
def client_home():
    sarah = get_client(DEMO_CLIENT_NAME)
    rows = client_checkins(sarah["id"])
    today_iso = date.today().isoformat()
    done_today = any(r["day"] == today_iso for r in rows)
    start, now, lost = weight_stats(rows)
    week_rows = rows[-7:]
    wins = []
    if lost > 0:
        wins.append(f"Down {lost:.1f} lbs since day one")
    best_steps = max((r["steps"] for r in week_rows), default=0)
    if best_steps >= 10000:
        wins.append(f"Biggest step day this week: {best_steps:,}")
    good_food = sum(1 for r in week_rows if r["food"] >= 8)
    if good_food >= 3:
        wins.append(f"{good_food} strong food days this week")
    avg_energy = (sum(r["energy"] for r in week_rows) / len(week_rows)) if week_rows else 0
    if avg_energy >= 7:
        wins.append("Energy trending up — averaging %.0f/10" % avg_energy)
    return render_template(
        "client_home.html", client=sarah, done_today=done_today,
        streak=streak_for(rows), start=start, now=now, lost=lost, wins=wins,
    )


@app.route("/client/checkin", methods=["GET", "POST"])
def client_checkin():
    sarah = get_client(DEMO_CLIENT_NAME)
    rows = client_checkins(sarah["id"])
    if request.method == "POST":
        f = request.form
        try:
            weight = float(f["weight"])
            food = min(10, max(1, int(f["food"])))
            steps = max(0, int(f["steps"]))
            water = max(0, int(f["water"]))
            sleep = float(f["sleep"])
            energy = min(10, max(1, int(f["energy"])))
        except (KeyError, ValueError):
            flash("A couple of numbers didn't look right — try again.")
            return render_template("checkin.html", client=sarah,
                                   last=rows[-1] if rows else None), 400
        db().execute(
            """INSERT OR REPLACE INTO checkins
               (client_id, day, weight, food, steps, water, sleep, energy, note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (sarah["id"], date.today().isoformat(), weight, food, steps,
             water, sleep, energy, f.get("note", "").strip()[:140]),
        )
        db().commit()
        flash("That's in, Sarah. One more day in the bank — see you tomorrow.")
        return redirect(url_for("client_home"))
    return render_template("checkin.html", client=sarah,
                           last=rows[-1] if rows else None)


@app.route("/client/progress")
def client_progress():
    sarah = get_client(DEMO_CLIENT_NAME)
    rows = client_checkins(sarah["id"])
    start, now, lost = weight_stats(rows)
    points, dots = sparkline_points(rows)
    return render_template(
        "progress.html", client=sarah, rows=list(reversed(rows)),
        start=start, now=now, lost=lost, points=points, dots=dots,
        badges=badges_for(rows), streak=streak_for(rows),
    )


@app.route("/coach")
def coach():
    today_iso = date.today().isoformat()
    roster = []
    total_lost = 0.0
    checked_today = 0
    streaks = []
    for c in db().execute("SELECT * FROM clients ORDER BY id").fetchall():
        rows = client_checkins(c["id"])
        start, now, lost = weight_stats(rows)
        streak = streak_for(rows)
        in_today = any(r["day"] == today_iso for r in rows)
        checked_today += 1 if in_today else 0
        total_lost += max(lost, 0.0)
        streaks.append(streak)
        roster.append({"client": c, "streak": streak, "in_today": in_today,
                       "start": start, "now": now, "lost": lost})
    avg_streak = round(sum(streaks) / len(streaks), 1) if streaks else 0
    return render_template(
        "coach.html", roster=roster, checked_today=checked_today,
        total_clients=len(roster), avg_streak=avg_streak,
        total_lost=round(total_lost, 1),
    )


@app.route("/coach/client/<int:client_id>")
def coach_client(client_id):
    c = db().execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    if c is None:
        abort(404)
    rows = client_checkins(c["id"])
    start, now, lost = weight_stats(rows)
    last7 = list(reversed(rows[-7:]))
    detail = [{**dict(r), "label": pretty_day(r["day"])} for r in last7]
    return render_template(
        "coach_client.html", client=c, detail=detail, streak=streak_for(rows),
        start=start, now=now, lost=lost,
        in_today=any(r["day"] == date.today().isoformat() for r in rows),
    )


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
