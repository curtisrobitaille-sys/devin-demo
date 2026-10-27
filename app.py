"""Devin Sherrington — Fat Loss Coach. Sales-demo web app.

Self-contained: Flask + sqlite3 only. No email, no push, no third-party APIs.
Seed data is created on first boot (only when the tables are empty).
Run:  python app.py            (uses $PORT or 5000)
  or: gunicorn app:app
"""
import base64
import os
import random
import sqlite3
from datetime import date, datetime, timedelta

from flask import (Flask, Response, abort, flash, g, redirect, render_template,
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
        CREATE TABLE IF NOT EXISTS kudos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id  INTEGER NOT NULL REFERENCES clients(id),
            date       TEXT NOT NULL,
            kind       TEXT DEFAULT '',
            message    TEXT DEFAULT '',
            created_at TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS pauses (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL REFERENCES clients(id),
            date      TEXT NOT NULL,
            UNIQUE (client_id, date)
        );
        CREATE TABLE IF NOT EXISTS challenge (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            goal INTEGER NOT NULL
        );
        CREATE TABLE IF NOT EXISTS challenge_joins (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL REFERENCES clients(id),
            day       TEXT NOT NULL,
            baseline  INTEGER NOT NULL DEFAULT 0,
            UNIQUE (client_id)
        );
        """
    )
    conn.commit()
    if conn.execute("SELECT COUNT(*) FROM clients").fetchone()[0] == 0:
        seed(conn)
    ensure_challenge(conn)
    conn.close()


CHALLENGE_NAME = "TEAM DEVIN — CHECK-IN CHALLENGE"


def ensure_challenge(conn):
    """Create the team challenge the first time the table is seen empty
    (fresh seed or an older database alike). Every roster client except
    the demo client starts out joined with a zero baseline, so their
    check-ins set the team's progress; the goal is set exactly one
    check-in past that progress, so the demo client joining and logging
    today's check-in is what carries the team over the line."""
    if conn.execute("SELECT COUNT(*) FROM challenge").fetchone()[0] > 0:
        return
    today_iso = date.today().isoformat()
    conn.execute(
        """INSERT OR IGNORE INTO challenge_joins (client_id, day, baseline)
           SELECT id, ?, 0 FROM clients WHERE name != ?""",
        (today_iso, DEMO_CLIENT_NAME),
    )
    progress = conn.execute(
        """SELECT COUNT(*) FROM checkins
           WHERE client_id IN (SELECT client_id FROM challenge_joins)"""
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO challenge (name, goal) VALUES (?, ?)",
        (CHALLENGE_NAME, progress + 1),
    )
    conn.commit()


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


def client_pauses(client_id):
    rows = db().execute(
        "SELECT date FROM pauses WHERE client_id = ?", (client_id,)
    ).fetchall()
    return {r["date"] for r in rows}


def kudos_for_day(client_id, day_iso):
    return db().execute(
        "SELECT * FROM kudos WHERE client_id = ? AND date = ? ORDER BY id DESC",
        (client_id, day_iso),
    ).fetchall()


def challenge_state():
    """The team challenge at a glance. Only joined members' check-ins
    count, and only the ones logged from their join onward — each join
    records a baseline (the member's check-in count at that moment), so
    joining never retroactively moves the total."""
    ch = db().execute("SELECT * FROM challenge ORDER BY id LIMIT 1").fetchone()
    if ch is None:
        return None
    joins = db().execute("SELECT * FROM challenge_joins").fetchall()
    total = 0
    for j in joins:
        cnt = db().execute(
            "SELECT COUNT(*) FROM checkins WHERE client_id = ?",
            (j["client_id"],),
        ).fetchone()[0]
        total += max(cnt - j["baseline"], 0)
    today = date.today()
    if today.month == 12:
        last_day = date(today.year, 12, 31)
    else:
        last_day = date(today.year, today.month + 1, 1) - timedelta(days=1)
    goal = ch["goal"]
    return {
        "name": ch["name"],
        "goal": goal,
        "total": total,
        "finished": total >= goal,
        "pct": min(100, round(100 * total / goal)) if goal else 100,
        "joined_ids": {j["client_id"] for j in joins},
        "joined_count": len(joins),
        "finish_label": "Finishes " + last_day.strftime("%b %d"),
    }


def streak_for(rows, paused=frozenset()):
    """Consecutive checked-in days ending today (or yesterday if today is
    still outstanding — the day isn't over yet). A paused day is neutral:
    it neither extends nor breaks the streak."""
    days = {r["day"] for r in rows}
    today = date.today()
    cursor = today
    if (today.isoformat() not in days
            and today.isoformat() not in paused):
        cursor = today - timedelta(days=1)
    streak = 0
    while True:
        iso = cursor.isoformat()
        if iso in days:
            streak += 1
        elif iso in paused:
            pass  # neutral — walk past it without counting or breaking
        else:
            break
        cursor -= timedelta(days=1)
    return streak


def week_streak_for(rows):
    """Consecutive Mon–Sun weeks with 5+ check-ins. The current week only
    counts once it reaches 5; until then the streak from earlier weeks is
    still alive and countable."""
    counts = {}
    for r in rows:
        d = date.fromisoformat(r["day"])
        monday = d - timedelta(days=d.weekday())
        counts[monday] = counts.get(monday, 0) + 1
    today = date.today()
    cursor = today - timedelta(days=today.weekday())
    if counts.get(cursor, 0) < 5:
        cursor -= timedelta(days=7)  # this week is still in play
    streak = 0
    while counts.get(cursor, 0) >= 5:
        streak += 1
        cursor -= timedelta(days=7)
    return streak


def last7_states(rows, paused):
    """States for the last 7 days, oldest first: done / paused / missed."""
    days = {r["day"] for r in rows}
    today = date.today()
    out = []
    for ago in range(6, -1, -1):
        iso = (today - timedelta(days=ago)).isoformat()
        if iso in days:
            out.append("done")
        elif iso in paused:
            out.append("paused")
        else:
            out.append("missed")
    return out


def weight_stats(rows):
    if not rows:
        return None, None, 0.0
    start = rows[0]["weight"]
    now = rows[-1]["weight"]
    return start, now, round(start - now, 1)


def badges_for(rows, paused=frozenset(), team_finisher=False):
    _start, _now, lost = weight_stats(rows)
    streak = streak_for(rows, paused)
    week_counts = {}
    dates = []
    for r in rows:
        d = date.fromisoformat(r["day"])
        dates.append(d)
        monday = d - timedelta(days=d.weekday())
        week_counts[monday] = week_counts.get(monday, 0) + 1
    five_in_week = any(n >= 5 for n in week_counts.values())
    back_at_it = False
    dates.sort()
    for a, b in zip(dates, dates[1:]):
        if (b - a).days - 1 >= 3:  # returned after a gap of 3+ empty days
            back_at_it = True
            break
    badges = [
        {"name": "First check-in", "icon": "✓", "earned": len(rows) > 0,
         "hint": "Log your first daily check-in"},
        {"name": "7-day streak", "icon": "🔥", "earned": streak >= 7,
         "hint": "Check in 7 days in a row"},
        {"name": "Down 5 lbs", "icon": "⚖️", "earned": lost >= 5.0,
         "hint": "Lose your first 5 lbs"},
        {"name": "5 in a week", "icon": "🗓️", "earned": five_in_week,
         "hint": "Check in 5 times in one week (Mon–Sun)"},
        {"name": "30 check-ins", "icon": "🎯", "earned": len(rows) >= 30,
         "hint": "Reach 30 total check-ins"},
        {"name": "100 check-ins", "icon": "💯", "earned": len(rows) >= 100,
         "hint": "Reach 100 total check-ins"},
        {"name": "Back at it", "icon": "🌱", "earned": back_at_it,
         "hint": "Come back after a 3+ day break"},
        {"name": "Team Finisher", "icon": "🏁", "earned": team_finisher,
         "hint": "Cross the finish line in a team challenge"},
    ]
    for b in badges:
        if not b["earned"]:
            b["up_next"] = True
            break
    return badges


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


KUDOS_EMOJI = ["👏", "🔥", "❤️"]
KUDOS_LINES = [
    "Proud of you — strong week.",
    "That's how it's done.",
    "Saw the effort today. It counts.",
]

CELEBRATION_LINES = [
    "Boom. Another day in the bank.",
    "That's how streaks are built — one honest day at a time.",
    "Done. Coach sees it, and it counts.",
    "Small step, done daily, beats big plans someday.",
    "You showed up. That's the whole secret.",
    "One more rep for Future You. She says thanks.",
    "Checked in, locked in. See you tomorrow.",
]


def week_recap(rows):
    """This week (Mon–Sun) at a glance, all computed from the rows."""
    today = date.today()
    monday = today - timedelta(days=today.weekday())
    sunday = monday + timedelta(days=6)
    week = [r for r in rows
            if monday.isoformat() <= r["day"] <= sunday.isoformat()]
    avg_steps = (round(sum(r["steps"] for r in week) / len(week))
                 if week else 0)

    def avg_weight(first, last):
        vals = [r["weight"] for r in rows
                if first.isoformat() <= r["day"] <= last.isoformat()]
        return (sum(vals) / len(vals)) if vals else None

    cur = avg_weight(today - timedelta(days=6), today)
    prev = avg_weight(today - timedelta(days=13), today - timedelta(days=7))
    trend = None
    if cur is not None and prev is not None:
        diff = round(cur - prev, 1)
        if diff < 0:
            trend = {"arrow": "▼", "good": True,
                     "text": f"down {abs(diff):.1f} lbs vs the week before"}
        elif diff > 0:
            trend = {"arrow": "▲", "good": False,
                     "text": f"up {diff:.1f} lbs vs the week before"}
        else:
            trend = {"arrow": "➜", "good": True,
                     "text": "holding steady vs the week before"}
    best = max(rows, key=lambda r: r["steps"]) if rows else None
    return {
        "count": len(week),
        "avg_steps": avg_steps,
        "trend": trend,
        "best_steps": best["steps"] if best else 0,
        "best_day": pretty_day(best["day"]) if best else "",
    }


def month_calendar(rows, paused):
    """Current month as Mon-first weeks of day cells:
    state done / paused / hollow. Returns (label, weeks)."""
    today = date.today()
    days = {r["day"] for r in rows}
    first = today.replace(day=1)
    start = first - timedelta(days=first.weekday())
    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)
    last = next_month - timedelta(days=1)
    end = last + timedelta(days=6 - last.weekday())
    weeks = []
    d = start
    while d <= end:
        week = []
        for _ in range(7):
            if d.month != today.month:
                week.append(None)
            else:
                iso = d.isoformat()
                if iso in days:
                    state = "done"
                elif iso in paused:
                    state = "paused"
                else:
                    state = "hollow"
                week.append({"num": d.day, "state": state,
                             "today": d == today})
            d += timedelta(days=1)
        weeks.append(week)
    return today.strftime("%B %Y"), weeks


# ---------------------------------------------------------------- routes
@app.route("/")
def landing():
    session["visited"] = True
    return render_template("landing.html")


@app.route("/client")
def client_home():
    sarah = get_client(DEMO_CLIENT_NAME)
    rows = client_checkins(sarah["id"])
    paused = client_pauses(sarah["id"])
    today_iso = date.today().isoformat()
    done_today = any(r["day"] == today_iso for r in rows)
    paused_today = today_iso in paused
    streak = streak_for(rows, paused)
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
    if done_today:
        recap_status = "Checked in today — the streak is safe ✓"
    elif paused_today:
        recap_status = f"{streak}-day streak, protected by today's pause"
    else:
        recap_status = f"{streak}-day streak — one check-in keeps it rolling"
    today_kudos = kudos_for_day(sarah["id"], today_iso)
    celebrate = session.pop("celebrate", False)
    celebrate_line = CELEBRATION_LINES[
        date.today().timetuple().tm_yday % len(CELEBRATION_LINES)]
    ch = challenge_state()
    roster_size = db().execute("SELECT COUNT(*) FROM clients").fetchone()[0]
    return render_template(
        "client_home.html", client=sarah, done_today=done_today,
        paused_today=paused_today, streak=streak,
        week_streak=week_streak_for(rows),
        start=start, now=now, lost=lost, wins=wins,
        recap=week_recap(rows), recap_status=recap_status,
        kudos=today_kudos[0] if today_kudos else None,
        celebrate=celebrate, celebrate_line=celebrate_line,
        challenge=ch, roster_size=roster_size,
        sarah_joined=(sarah["id"] in ch["joined_ids"]) if ch else False,
    )


@app.route("/client/join-challenge", methods=["POST"])
def client_join_challenge():
    sarah = get_client(DEMO_CLIENT_NAME)
    already = db().execute(
        "SELECT id FROM challenge_joins WHERE client_id = ?",
        (sarah["id"],),
    ).fetchone()
    if not already:
        baseline = db().execute(
            "SELECT COUNT(*) FROM checkins WHERE client_id = ?",
            (sarah["id"],),
        ).fetchone()[0]
        db().execute(
            """INSERT OR IGNORE INTO challenge_joins (client_id, day, baseline)
               VALUES (?, ?, ?)""",
            (sarah["id"], date.today().isoformat(), baseline),
        )
        db().commit()
        flash("You're in! Every check-in you log now counts toward the team total.")
    return redirect(url_for("client_home"))


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
        session["celebrate"] = True
        flash("That's in, Sarah. One more day in the bank — see you tomorrow.")
        return redirect(url_for("client_home"))
    return render_template("checkin.html", client=sarah,
                           last=rows[-1] if rows else None)


@app.route("/client/pause", methods=["POST"])
def client_pause():
    sarah = get_client(DEMO_CLIENT_NAME)
    today_iso = date.today().isoformat()
    rows = client_checkins(sarah["id"])
    if any(r["day"] == today_iso for r in rows):
        return redirect(url_for("client_home"))  # already in — pause is moot
    existing = db().execute(
        "SELECT id FROM pauses WHERE client_id = ? AND date = ?",
        (sarah["id"], today_iso),
    ).fetchone()
    if existing:
        db().execute("DELETE FROM pauses WHERE id = ?", (existing["id"],))
        flash("Pause lifted — today is open again whenever you're ready.")
    else:
        db().execute(
            "INSERT OR IGNORE INTO pauses (client_id, date) VALUES (?, ?)",
            (sarah["id"], today_iso),
        )
        flash("Paused. Life happens — your streak stays right where it is.")
    db().commit()
    return redirect(url_for("client_home"))


@app.route("/client/progress")
def client_progress():
    sarah = get_client(DEMO_CLIENT_NAME)
    rows = client_checkins(sarah["id"])
    paused = client_pauses(sarah["id"])
    start, now, lost = weight_stats(rows)
    points, dots = sparkline_points(rows)
    month_label, cal_weeks = month_calendar(rows, paused)
    ch = challenge_state()
    team_finisher = bool(
        ch and ch["finished"] and sarah["id"] in ch["joined_ids"])
    return render_template(
        "progress.html", client=sarah, rows=list(reversed(rows)),
        start=start, now=now, lost=lost, points=points, dots=dots,
        badges=badges_for(rows, paused, team_finisher=team_finisher),
        streak=streak_for(rows, paused),
        month_label=month_label, cal_weeks=cal_weeks,
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
        paused = client_pauses(c["id"])
        start, now, lost = weight_stats(rows)
        streak = streak_for(rows, paused)
        in_today = any(r["day"] == today_iso for r in rows)
        checked_today += 1 if in_today else 0
        total_lost += max(lost, 0.0)
        streaks.append(streak)
        roster.append({"client": c, "streak": streak, "in_today": in_today,
                       "paused_today": today_iso in paused,
                       "strip": last7_states(rows, paused),
                       "start": start, "now": now, "lost": lost})
    avg_streak = round(sum(streaks) / len(streaks), 1) if streaks else 0
    return render_template(
        "coach.html", roster=roster, checked_today=checked_today,
        total_clients=len(roster), avg_streak=avg_streak,
        total_lost=round(total_lost, 1),
        challenge=challenge_state(),
    )


@app.route("/coach/client/<int:client_id>")
def coach_client(client_id):
    c = db().execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    if c is None:
        abort(404)
    rows = client_checkins(c["id"])
    paused = client_pauses(c["id"])
    today_iso = date.today().isoformat()
    start, now, lost = weight_stats(rows)
    last7 = list(reversed(rows[-7:]))
    detail = [{**dict(r), "label": pretty_day(r["day"])} for r in last7]
    return render_template(
        "coach_client.html", client=c, detail=detail,
        streak=streak_for(rows, paused),
        start=start, now=now, lost=lost,
        in_today=any(r["day"] == today_iso for r in rows),
        paused_today=today_iso in paused,
        kudos_emoji=KUDOS_EMOJI, kudos_lines=KUDOS_LINES,
        sent_kudos=kudos_for_day(c["id"], today_iso),
    )


@app.route("/coach/client/<int:client_id>/kudos", methods=["POST"])
def coach_kudos(client_id):
    c = db().execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()
    if c is None:
        abort(404)
    kind = request.form.get("kind", "").strip()
    message = request.form.get("message", "").strip()
    if kind in KUDOS_EMOJI:
        message = ""
    elif message in KUDOS_LINES:
        kind = ""
    else:
        abort(400)
    db().execute(
        """INSERT INTO kudos (client_id, date, kind, message, created_at)
           VALUES (?, ?, ?, ?, ?)""",
        (client_id, date.today().isoformat(), kind, message,
         datetime.now().isoformat(timespec="seconds")),
    )
    db().commit()
    flash(f"Kudos sent to {c['name']} — they'll see it on their home screen.")
    return redirect(url_for("coach_client", client_id=client_id))


# ---------------------------------------------------------------- app icons
_ICON_CACHE = {}


def _icon_bytes(filename):
    if filename not in _ICON_CACHE:
        with open(os.path.join(BASE, "icondata", filename), "rb") as f:
            _ICON_CACHE[filename] = base64.b64decode(f.read())
    return _ICON_CACHE[filename]


@app.route("/apple-touch-icon.png")
def apple_touch_icon():
    return Response(_icon_bytes("icon_apple_b64.txt"), mimetype="image/png")


@app.route("/icon-192.png")
def icon_192():
    return Response(_icon_bytes("icon_192_b64.txt"), mimetype="image/png")


@app.route("/icon-512.png")
def icon_512():
    return Response(_icon_bytes("icon_512_b64.txt"), mimetype="image/png")


@app.route("/favicon.png")
def favicon_png():
    return Response(_icon_bytes("icon_192_b64.txt"), mimetype="image/png")


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
