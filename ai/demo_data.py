"""Demo training titles for the FocusOs title classifier.

  python ai/demo_data.py titles     labelled window titles for the classifier (source = 'demo')
  python ai/demo_data.py reset      remove the demo titles again

Demo titles are kept apart from your own labels (source = 'demo' vs 'user').
FocusOs is single-user, so no fake activity is generated: it would mix with
your real sessions. Your own sessions are never touched.

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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from title_classifier import DEFAULT_CONFIG, load_database_config  # noqa: E402

LABEL_NOISE = 0.02                               # real hand labels are never perfect

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
    # added in v2 of the demo data: topics the first model had never seen
    "video_game": ["GTA 6", "GTA 5", "Minecraft", "Valorant", "BGMI", "Free Fire", "Fortnite", "Elden Ring",
                   "Call of Duty", "Roblox", "FIFA 26", "Clash of Clans"],
    "streamer2": ["Shinelayz", "Techno Gamerz", "Total Gaming", "CarryMinati", "Mortal", "Dynamo Gaming"],
    "song2": ["Kesariya", "Pasoori", "Apna Bana Le", "Espresso", "Die With A Smile", "Husn"],
    "artist2": ["Arijit Singh", "Sabrina Carpenter", "Bruno Mars", "Anuv Jain", "Diljit Dosanjh"],
    "sport": ["IPL 2026", "Premier League", "Champions League", "World Cup qualifiers", "Pro Kabaddi"],
    "exam": ["GATE CSE", "semester exam", "end-term exam", "placement interview", "UGC NET"],
    "skill": ["Python", "Data Structures", "SQL", "Operating Systems", "Machine Learning", "Java", "React"],
    "admin_task": ["reset password", "update address", "download marksheet", "pay hostel fee",
                   "check application status", "renew library card"],
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
    # v2: broader coverage (gaming, streams, music, sport, more study videos, more admin)
    ("d_game_stream", "distracting", "{video_game} Marathon Stream & Giveaway - YouTube"),
    ("d_gameplay", "distracting", "{video_game} Gameplay Part {n} - {streamer2} - YouTube"),
    ("d_game_live", "distracting", "{streamer2} is live! {video_game} rank push - YouTube"),
    ("d_trailer", "distracting", "{video_game} Official Trailer {n} - YouTube"),
    ("d_music_video", "distracting", "{song2} (Official Music Video) - {artist2} - YouTube"),
    ("d_lyrics", "distracting", "{song2} Lyrics | {artist2} - YouTube"),
    ("d_sport_highlights", "distracting", "{sport} Highlights: {team} vs {team} - YouTube"),
    ("p_full_course", "productive", "{skill} Full Course for Beginners ({n} Hours) - YouTube"),
    ("p_crash_course", "productive", "{skill} Crash Course - Learn in One Video - YouTube"),
    ("p_exam_prep", "productive", "{exam} preparation: {cs} previous year questions - YouTube"),
    ("p_solved", "productive", "{cs} solved examples | {exam} - YouTube"),
    ("n_how_to_admin", "neutral", "How to {admin_task} - Google Search"),
    ("n_portal_admin", "neutral", "{admin_task} - University ERP"),
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


def reset(conn) -> None:
    cur = conn.cursor()
    cur.execute("DELETE FROM title_training_samples WHERE source = 'demo'")
    # Older versions also created a separate demo user (id 99) with fake
    # activity; FocusOs is single-user now, so remove it if it is still there.
    cur.execute("DELETE FROM sessions WHERE user_id = 99")      # cascades to activity etc.
    cur.execute("DELETE FROM user_app_category WHERE user_id = 99")
    cur.execute("DELETE FROM site_rules WHERE user_id = 99")
    cur.execute("DELETE FROM users WHERE user_id = 99")


def main() -> None:
    import psycopg
    parser = argparse.ArgumentParser(description="Create or remove FocusOs demo training titles.")
    parser.add_argument("what", choices=("titles", "reset"))
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args()

    with psycopg.connect(**load_database_config(args.config)) as conn:
        if args.what == "reset":
            reset(conn)
            print("Removed all demo data (demo training titles, and the old demo user if present).")
            return
        # Re-running replaces the old demo titles instead of piling them up.
        conn.execute("DELETE FROM title_training_samples WHERE source = 'demo'")
        rows = generate_titles()
        conn.cursor().executemany(
            "INSERT INTO title_training_samples (window_title, label, source, template_group) "
            "VALUES (%s, %s, 'demo', %s)", rows)
        by = {}
        for _, label, _ in rows:
            by[label] = by.get(label, 0) + 1
        print(f"Added {len(rows)} demo training titles from {len(TEMPLATES)} templates: {by}")


if __name__ == "__main__":
    main()
