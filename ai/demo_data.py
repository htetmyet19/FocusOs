"""Demo data for FocusOs.

  python ai/demo_data.py titles     labelled window titles for the classifier (source = 'demo')
  python ai/demo_data.py activity   two weeks of sessions for a separate "Demo student" user (id 99)
  python ai/demo_data.py all        both
  python ai/demo_data.py reset      remove all demo data again

Everything demo is kept apart from real data: titles have source = 'demo',
activity belongs to user 99 only. Your own sessions are never touched.

Labelling policy (the same rule a human labeller would follow):
  productive   studying or working: lectures, docs, coding, papers, assignments
  distracting  entertainment, social feeds, games, streaming, shopping for fun
  neutral      admin and utilities: email, search, maps, banking, calendar, news
Hard cases are included on purpose (YouTube, Reddit, Wikipedia, Amazon can be
any class depending on the content), because that is where a title
classifier actually earns its keep.

The titles are generated from templates, so a model scored on a random split
would be scored on near-copies of its training data. Every title therefore
records its template (template_group), and title_classifier.py validates with
templates kept apart. Even so: high scores on demo data prove the pipeline
works, not that the model is accurate on real titles. Label real titles too.
"""
import argparse
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from title_classifier import DEFAULT_CONFIG, load_database_config  # noqa: E402

DEMO_USER_ID = 99
DEMO_USER_NAME = "Demo student"
IST = timezone(timedelta(hours=5, minutes=30))   # fixed offset: no tz database needed
LABEL_NOISE = 0.02                               # real hand labels are never perfect
DEMO_CPUS = 8                                    # assumed logical CPUs for demo CPU times

BROWSER_SUFFIX = [" - Google Chrome", " - Google Chrome", " - Brave", " - Microsoft​ Edge",
                  " — Mozilla Firefox", ""]

# ----------------------------------------------------------------- fillers
F = {
    "cs": ["Deadlocks", "CPU Scheduling", "Paging and Segmentation", "Semaphores", "Normalization",
           "B+ Trees", "Transactions and ACID", "Dijkstra's Algorithm", "Dynamic Programming",
           "Binary Search Trees", "Process Synchronization", "Virtual Memory", "Hashing", "Graph Traversal",
           "SQL Joins", "Recursion", "Big O Notation", "Linked Lists", "Heap Sort", "TCP Handshake",
           "Gradient Descent", "Linear Regression", "Neural Networks", "Thread Pools", "Mutex vs Semaphore"],
    "uni": ["MIT OpenCourseWare", "NPTEL", "Stanford Online", "CS50", "Gate Smashers", "Neso Academy",
            "Abdul Bari", "freeCodeCamp.org", "3Blue1Brown"],
    "error": ["Segmentation fault (core dumped)", "undefined reference to `main'", "NullPointerException in Java",
              "TypeError: 'NoneType' object is not subscriptable", "ModuleNotFoundError: No module named 'psycopg'",
              "CMake could not find PostgreSQL", "fatal: not a git repository", "IndexError: list index out of range",
              "React useEffect runs twice", "pandas SettingWithCopyWarning", "mutex lock deadlock in C++",
              "how to free memory in C", "difference between process and thread",
              "SQL GROUP BY with HAVING", "Python virtual environment not activating"],
    "api": ["std::condition_variable", "std::thread", "pthread_mutex_lock", "Array.prototype.map",
            "fetch()", "pandas.DataFrame.groupby", "numpy.linspace", "CREATE INDEX", "GetForegroundWindow",
            "CreateToolhelp32Snapshot", "list comprehensions", "async and await", "flexbox", "useState"],
    "lang": ["C++", "Python", "JavaScript", "Java", "SQL", "Rust", "Go"],
    "repo": ["FocusOs", "os-dbms-project", "ml-assignments", "dsa-practice", "portfolio-site", "lab-reports"],
    "gh_user": ["htet-dev", "priyank-n", "student123", "codewithme", "geu-cs"],
    "problem": ["Two Sum", "Reverse Linked List", "Valid Parentheses", "Merge Intervals", "LRU Cache",
                "Number of Islands", "Course Schedule", "Climbing Stairs", "Top K Frequent Elements",
                "Longest Substring Without Repeating Characters", "Coin Change", "Word Break"],
    "course": ["Machine Learning", "Algorithms Part I", "Operating Systems Fundamentals",
               "Database Management Essentials", "Python for Everybody", "Deep Learning Specialization",
               "Computer Networks", "Discrete Mathematics"],
    "subject": ["Operating Systems", "DBMS", "Computer Networks", "Data Structures", "Discrete Maths",
                "Software Engineering", "Theory of Computation", "Machine Learning", "Compiler Design"],
    "assignment": ["Lab 4 submission", "Assignment 2", "Mid-term project report", "Quiz 3",
                   "Case study upload", "Practical file", "Mini project proposal"],
    "code": ["TCS-501", "TCS-503", "TCS-505", "PCS-502", "TCS-511"],
    "paper": ["deadlock detection in distributed systems", "query optimization survey",
              "attention is all you need", "process scheduling fairness", "index selection for OLTP",
              "transformer models for text classification"],
    "funny": ["Try Not To Laugh Challenge", "Funniest Cat Videos 2026", "Epic Fails Compilation",
              "Best Prank Ever", "Reacting To Weird Internet Videos", "Satisfying Video Compilation",
              "Unboxing the New iPhone", "Minecraft But Every Block Is Random", "My Day Vlog",
              "Top 10 Anime Fights", "Movie Trailer Reaction"],
    "show": ["Stranger Things", "Wednesday", "Money Heist", "The Crown", "Squid Game", "Panchayat",
             "Mirzapur", "Breaking Bad", "Kota Factory", "The Office"],
    "meme_sub": ["memes", "funny", "gaming", "dankmemes", "IndianDankMemes", "pics", "aww", "movies"],
    "study_sub": ["learnprogramming", "cpp_questions", "Python", "computerscience", "SQL", "cscareerquestions"],
    "streamer": ["xQc", "Ninja", "shroud", "Mortal", "Pokimane", "TotalGaming"],
    "product": ["Gaming Mouse RGB", "Bluetooth Headphones", "Smart Watch", "Hoodie Oversized", "Sneakers",
                "Mechanical Keyboard", "Phone Cover", "Perfume Combo"],
    "game": ["Subway Surfers", "Chess Blitz", "Slither.io", "Krunker", "2048", "Wordle Unlimited", "Geometry Dash"],
    "song": ["Kesariya", "Blinding Lights", "Shape of You", "Tum Hi Ho", "Levitating", "Heeriye"],
    "artist": ["Arijit Singh", "The Weeknd", "Ed Sheeran", "Dua Lipa", "AP Dhillon"],
    "team": ["India", "Australia", "England", "Pakistan", "South Africa", "New Zealand", "CSK", "RCB", "MI"],
    "query": ["weather tomorrow", "train timings dehradun to delhi", "nearest atm", "pizza near me",
              "how many days until diwali", "currency converter usd to inr", "time in tokyo",
              "electricity bill payment", "post office near me", "bus pass renewal"],
    "place": ["Clock Tower Dehradun", "Graphic Era University", "Rajpur Road", "ISBT Dehradun",
              "Paltan Bazaar", "Pacific Mall Dehradun", "Dehradun Railway Station"],
    "bank": ["SBI", "HDFC Bank", "ICICI Bank", "Axis Bank", "Kotak"],
    "headline": ["Monsoon update for Uttarakhand", "Budget 2026 highlights", "New metro line announced",
                 "Petrol prices revised", "Exam calendar released"],
    "paper_site": ["The Hindu", "Times of India", "Hindustan Times", "Indian Express"],
    "city": ["Dehradun", "Delhi", "Mumbai", "Bengaluru", "Tokyo", "London"],
    "wiki_general": ["Dehradun", "Taj Mahal", "Virat Kohli", "Mount Everest", "Bollywood", "Tokyo"],
    "name": ["Htet", "Priya", "Rahul", "Aman", "Sneha"],
    "n": [str(i) for i in range(1, 30)],
}

# ----------------------------------------------------------------- templates
# (template id, label, pattern). {key} picks a random filler from F.
TEMPLATES = [
    # productive
    ("p_lecture_yt", "productive", "Lecture {n}: {cs} | {uni} - YouTube"),
    ("p_tutorial_yt", "productive", "{cs} explained in {n} minutes - {uni} - YouTube"),
    ("p_stackoverflow", "productive", "{error} - Stack Overflow"),
    ("p_docs_cpp", "productive", "{api} - cppreference.com"),
    ("p_docs_mdn", "productive", "{api} - JavaScript | MDN"),
    ("p_docs_python", "productive", "{api} — Python 3.13 documentation"),
    ("p_github_pr", "productive", "Pull Request #{n} · {gh_user}/{repo} · GitHub"),
    ("p_github_repo", "productive", "{gh_user}/{repo}: {lang} project for {subject} · GitHub"),
    ("p_leetcode", "productive", "{n}. {problem} - LeetCode"),
    ("p_gfg", "productive", "{cs} - GeeksforGeeks"),
    ("p_coursera", "productive", "{course} | Coursera"),
    ("p_docs_google", "productive", "{subject} notes unit {n} - Google Docs"),
    ("p_overleaf", "productive", "{subject} {assignment} - Overleaf, Online LaTeX Editor"),
    ("p_scholar", "productive", "{paper} - Google Scholar"),
    ("p_chatgpt", "productive", "Explain {cs} with an example - ChatGPT"),
    ("p_w3", "productive", "{lang} {api} - W3Schools"),
    ("p_lms", "productive", "{code}: {assignment} | Student Portal"),
    ("p_kaggle", "productive", "{course} dataset notebook | Kaggle"),
    ("p_pdf", "productive", "{subject} Unit {n} lecture notes.pdf"),
    ("p_postgres_docs", "productive", "PostgreSQL: Documentation: 18: {cs}"),
    ("p_reddit_study", "productive", "How do I understand {cs}? : r/{study_sub}"),
    ("p_wiki_cs", "productive", "{cs} - Wikipedia"),
    # distracting
    ("d_youtube_fun", "distracting", "{funny} - YouTube"),
    ("d_youtube_shorts", "distracting", "#shorts {funny} - YouTube"),
    ("d_netflix", "distracting", "Watch {show} | Netflix"),
    ("d_netflix_episode", "distracting", "{show} - Season {n} Episode {n} | Netflix"),
    ("d_prime", "distracting", "{show} - Prime Video"),
    ("d_instagram", "distracting", "Instagram • Reels"),
    ("d_instagram_profile", "distracting", "{name} (@{name}_{n}) • Instagram photos and videos"),
    ("d_reddit_memes", "distracting", "r/{meme_sub} - Reddit"),
    ("d_reddit_post", "distracting", "this made my day : r/{meme_sub}"),
    ("d_twitch", "distracting", "{streamer} - Twitch"),
    ("d_x_home", "distracting", "Home / X"),
    ("d_facebook", "distracting", "({n}) Facebook"),
    ("d_amazon_shop", "distracting", "Amazon.in : {product}"),
    ("d_myntra", "distracting", "Buy {product} Online | Myntra"),
    ("d_games", "distracting", "{game} - Play Online Free"),
    ("d_cricbuzz", "distracting", "{team} vs {team}, Live Cricket Score - Cricbuzz"),
    ("d_hotstar", "distracting", "Watch {team} vs {team} Live - JioHotstar"),
    ("d_spotify", "distracting", "{song} - song and lyrics by {artist} | Spotify"),
    ("d_9gag", "distracting", "9GAG - Best Funny Memes and Breaking News"),
    # neutral
    ("n_gmail", "neutral", "Inbox ({n}) - {name}.student@gmail.com - Gmail"),
    ("n_outlook", "neutral", "Mail - {name} - Outlook"),
    ("n_search", "neutral", "{query} - Google Search"),
    ("n_maps", "neutral", "{place} - Google Maps"),
    ("n_bank", "neutral", "{bank} NetBanking - Login"),
    ("n_drive", "neutral", "My Drive - Google Drive"),
    ("n_calendar", "neutral", "Google Calendar - Week of {n} November"),
    ("n_news", "neutral", "{headline} | {paper_site}"),
    ("n_weather", "neutral", "Weather in {city} - 10 day forecast"),
    ("n_newtab", "neutral", "New Tab"),
    ("n_settings", "neutral", "Settings"),
    ("n_irctc", "neutral", "IRCTC Next Generation eTicketing System"),
    ("n_wiki_general", "neutral", "{wiki_general} - Wikipedia"),
    ("n_amazon_orders", "neutral", "Your Orders - Amazon.in"),
    ("n_paytm", "neutral", "Electricity Bill Payment - Paytm"),
    ("n_downloads", "neutral", "Downloads"),
]


def _fill(pattern: str, rng: random.Random) -> str:
    out = pattern
    while "{" in out:
        start = out.index("{")
        key = out[start + 1:out.index("}", start)]
        out = out[:start] + rng.choice(F[key]) + out[out.index("}", start) + 1:]
    return out


def generate_titles(per_template: int = 12, seed: int = 7, noise: float = LABEL_NOISE) -> list:
    """[(title, label, template_group)]; deduplicated, with a little label noise."""
    rng = random.Random(seed)
    labels = ["productive", "neutral", "distracting"]
    rows, seen = [], set()
    for tid, label, pattern in TEMPLATES:
        attempts = 0
        made = 0
        while made < per_template and attempts < per_template * 20:
            attempts += 1
            title = _fill(pattern, rng) + rng.choice(BROWSER_SUFFIX)
            if title.lower() in seen:
                continue
            seen.add(title.lower())
            made += 1
            final = label
            if rng.random() < noise:          # a labeller's occasional mistake
                final = rng.choice([l for l in labels if l != label])
            rows.append((title, final, tid))
    return rows


# ----------------------------------------------------------------- demo activity

DESKTOP_APPS = {
    "code.exe": ["main.cpp - FocusOs - Visual Studio Code", "session_manager.cpp - FocusOs - Visual Studio Code",
                 "schema.sql - FocusOs - Visual Studio Code", "app.js - dashboard - Visual Studio Code"],
    "winword.exe": ["DBMS Lab Report.docx - Word", "OS Assignment 3.docx - Word"],
    "windowsterminal.exe": ["Windows PowerShell", "cmake --build build"],
    "explorer.exe": ["Downloads", "Documents"],
    "discord.exe": ["#general | Study Group - Discord", "Friends - Discord"],
    "whatsapp.root.exe": ["WhatsApp"],
    "spotify.exe": ["Spotify Premium"],
}
BUSY_PROCESSES = [("chrome.exe", 4.0), ("code.exe", 2.5), ("msedge.exe", 1.0), ("onedrive.exe", 0.6),
                  ("discord.exe", 1.2), ("spotify.exe", 0.8), ("searchhost.exe", 0.4), ("nvidia app.exe", 0.5)]


def _segments_for_session(rng, start, minutes, focus, chrome_titles):
    """A plausible run of windows: mostly study, some drift, a coffee-break idle."""
    segs, t, end = [], start, start + timedelta(minutes=minutes)
    focus_bias = 0.85 if focus else 0.6        # focus sessions drift less
    while t < end:
        dur = timedelta(seconds=rng.randint(40, 600))
        r = rng.random()
        if r < 0.06 and segs:
            segs.append(("idle", None, None, t, min(t + timedelta(seconds=rng.randint(130, 420)), end)))
        elif r < focus_bias:
            app = rng.choice(["code.exe", "code.exe", "winword.exe", "windowsterminal.exe", "chrome.exe", "chrome.exe"])
            title = rng.choice(chrome_titles["productive"]) if app == "chrome.exe" else rng.choice(DESKTOP_APPS[app])
            segs.append(("act", app, title, t, min(t + dur, end)))
        elif r < focus_bias + 0.12:
            app = rng.choice(["chrome.exe", "explorer.exe"])
            title = rng.choice(chrome_titles["neutral"]) if app == "chrome.exe" else rng.choice(DESKTOP_APPS[app])
            segs.append(("act", app, title, t, min(t + dur / 2, end)))
        else:
            app = rng.choice(["chrome.exe", "chrome.exe", "discord.exe", "whatsapp.root.exe", "spotify.exe"])
            title = rng.choice(chrome_titles["distracting"]) if app == "chrome.exe" else rng.choice(DESKTOP_APPS[app])
            segs.append(("act", app, title, t, min(t + dur / 2, end)))
        t = segs[-1][4]
    return segs


def generate_activity(conn, days: int = 14, seed: int = 21) -> dict:
    rng = random.Random(seed)
    # Titles for the demo browser tabs come from a different seed than the
    # training titles, so the classifier sees new instances.
    pool = {"productive": [], "neutral": [], "distracting": []}
    for title, label, _ in generate_titles(per_template=6, seed=seed + 1000, noise=0.0):
        pool[label].append(title)

    cur = conn.cursor()
    cur.execute("INSERT INTO users (user_id, name) VALUES (%s, %s) ON CONFLICT (user_id) DO UPDATE SET name = EXCLUDED.name",
                (DEMO_USER_ID, DEMO_USER_NAME))
    app_ids = {}

    def app_id(name):
        if name not in app_ids:
            app_ids[name] = cur.execute(
                "INSERT INTO applications (process_name) VALUES (%s) ON CONFLICT (process_name) "
                "DO UPDATE SET process_name = EXCLUDED.process_name RETURNING app_id", (name,)).fetchone()[0]
        return app_ids[name]

    now_ist = datetime.now(IST)
    counts = {"sessions": 0, "activity": 0, "idle": 0, "process": 0, "blocks": 0}
    for back in range(days, -1, -1):
        day = (now_ist - timedelta(days=back)).date()
        if back == 10:
            continue                                   # one missed day: streak restarts after it
        n_sessions = rng.choice([1, 2, 2, 3])
        hours = sorted(rng.sample([9, 10, 11, 14, 15, 16, 19, 20, 21, 22], n_sessions))
        for h in hours:
            start = datetime(day.year, day.month, day.day, h, rng.randint(0, 40), tzinfo=IST)
            focus = rng.random() < 0.5
            planned = rng.choice([25, 50]) if focus else None
            minutes = (planned if rng.random() < 0.7 else rng.randint(8, planned - 3)) if focus else rng.randint(30, 110)
            end = start + timedelta(minutes=minutes)
            if end > now_ist - timedelta(minutes=2):
                continue                               # don't invent the future
            sid = cur.execute(
                "INSERT INTO sessions (user_id, start_time, end_time, focus_mode, planned_minutes) "
                "VALUES (%s, %s, %s, %s, %s) RETURNING session_id",
                (DEMO_USER_ID, start, end, focus, planned)).fetchone()[0]
            counts["sessions"] += 1

            for kind, app, title, s, e in _segments_for_session(rng, start, minutes, focus, pool):
                if kind == "idle":
                    cur.execute("INSERT INTO idle_periods (session_id, start_time, end_time) VALUES (%s, %s, %s)", (sid, s, e))
                    counts["idle"] += 1
                    continue
                cur.execute("INSERT INTO activity_log (session_id, app_id, window_title, start_time, end_time) "
                            "VALUES (%s, %s, %s, %s, %s)", (sid, app_id(app), title, s, e))
                counts["activity"] += 1
                # Focus Mode would have pushed distracting desktop apps away.
                if focus and app in ("discord.exe", "whatsapp.root.exe", "spotify.exe"):
                    cur.execute("INSERT INTO focus_blocks (session_id, blocked_at, app_id, action) VALUES (%s, %s, %s, 'minimised')",
                                (sid, s, app_id(app)))
                    counts["blocks"] += 1

            # Blocked apps also try to pop up on their own (notifications, habit):
            # 0-4 attempts per focus session that Focus Mode pushed away.
            if focus:
                for _ in range(rng.choice([0, 1, 1, 2, 3, 4])):
                    at = start + timedelta(seconds=rng.randint(60, max(61, minutes * 60 - 60)))
                    cur.execute("INSERT INTO focus_blocks (session_id, blocked_at, app_id, action) VALUES (%s, %s, %s, 'minimised')",
                                (sid, at, app_id(rng.choice(["discord.exe", "whatsapp.root.exe", "spotify.exe", "telegram.exe"]))))
                    counts["blocks"] += 1

            # Process snapshots every ~5 minutes: a few busy processes.
            t = start + timedelta(minutes=1)
            while t < end:
                for name, base in rng.sample(BUSY_PROCESSES, 4):
                    cpu = max(0.5, rng.gauss(base, base / 3))
                    cur.execute(
                        "INSERT INTO process_samples (session_id, sampled_at, app_id, pid, parent_pid, thread_count, "
                        "base_priority, priority_class, cpu_percent, cpu_delta_ms, cpu_total_ms, working_set_bytes, is_foreground) "
                        "VALUES (%s,%s,%s,%s,%s,%s,8,'normal',%s,%s,%s,%s,%s)",
                        (sid, t, app_id(name), rng.randint(1000, 30000), rng.randint(500, 9000), rng.randint(8, 60),
                         # cpu_percent is a share of ALL cores: ms = % x interval x cores
                         round(cpu, 2), int(cpu / 100 * 300_000 * DEMO_CPUS), rng.randint(10_000, 900_000),
                         rng.randint(80, 900) * 1024 * 1024, name == "code.exe"))
                    counts["process"] += 1
                t += timedelta(minutes=5)
    return counts


def reset(conn) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM sessions WHERE user_id = %s", (DEMO_USER_ID,))     # cascades to activity etc.
    cur.execute("DELETE FROM user_app_category WHERE user_id = %s", (DEMO_USER_ID,))
    cur.execute("DELETE FROM users WHERE user_id = %s", (DEMO_USER_ID,))
    cur.execute("DELETE FROM title_training_samples WHERE source = 'demo'")


def main() -> None:
    import psycopg
    parser = argparse.ArgumentParser(description="Create or remove FocusOs demo data.")
    parser.add_argument("what", choices=("titles", "activity", "all", "reset"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()

    with psycopg.connect(**load_database_config(args.config)) as conn:
        if args.what in ("reset", "titles", "all"):
            # Re-running replaces the old demo data instead of piling it up.
            if args.what == "reset":
                reset(conn)
                print("Removed all demo data (user 99 and demo training titles).")
                return
            conn.execute("DELETE FROM title_training_samples WHERE source = 'demo'")
            rows = generate_titles()
            conn.cursor().executemany(
                "INSERT INTO title_training_samples (window_title, label, source, template_group) "
                "VALUES (%s, %s, 'demo', %s)", rows)
            by = {}
            for _, label, _ in rows:
                by[label] = by.get(label, 0) + 1
            print(f"Added {len(rows)} demo training titles from {len(TEMPLATES)} templates: {by}")
        if args.what in ("activity", "all"):
            conn.execute("DELETE FROM sessions WHERE user_id = %s", (DEMO_USER_ID,))
            counts = generate_activity(conn)
            print(f"Added demo activity for user {DEMO_USER_ID} ({DEMO_USER_NAME}): {counts}")


if __name__ == "__main__":
    main()
