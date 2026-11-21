# FocusOs test log

What the project looked like before this round of work, every test that was
run while changing it (with the real results, including the failures), and
the final state. Only tests that were actually executed are listed; things
that were not tested are listed separately at the end.

**Test machine:** Windows 11 Pro · MinGW-w64 GCC 16.2.0 · CMake + Ninja (WinLibs) ·
PostgreSQL 18.7 · Python 3.13 (Flask, pandas, psycopg 3, scikit-learn) · Chrome via Playwright for UI checks.
**Date:** 21 November 2026. **Starting point:** commit `ce01e22` ("docs: add README").

---

## 1. Baseline: the project before changes

### Components

| Part | State |
|---|---|
| `monitor/` | C++ activity monitor writing to **MySQL** |
| `tracker/` | C++ tracker writing to **SQLite** (sessions, idle, Focus Mode) |
| `tracker/dashboard/` | Flask dashboard reading the SQLite file |
| `ai/` | TF-IDF + Multinomial Naive Bayes title classifier |
| `db/logic.sql` | MySQL views; no table definitions |
| `prototype/` | First Python version writing CSV |

### What could run

| Check | Result |
|---|---|
| Start the dashboard (`python server.py`) | **Fails:** `ModuleNotFoundError: No module named 'db'`; `db.py` and `metrics.py` were not in the repository |
| Create the database from the repo | **Impossible:** no `CREATE TABLE` for `sessions`, `activity_logs`, `title_training_samples`, `ai_predictions` |
| Build `tracker/` | **Impossible:** no `CMakeLists.txt`, SQLite not provided |
| Build `tracker/` after adding a build file | **Fails with GCC:** `could not convert '<brace-enclosed initializer list>()' to 'ft::SessionManager::Config'` (`Config cfg = {}` default argument; accepted by MSVC, rejected by GCC) |
| C++ compiler on the test PC | None at first; MinGW GCC added later by the user |

### Defects found in the code review

| # | Defect | Effect |
|---|---|---|
| 1 | Dashboard imports missing modules | Dashboard cannot start |
| 2 | Database schema not in the repo | Nobody can set it up |
| 3 | No build file for `tracker/` | Cannot be compiled |
| 4 | `logic.sql` `UPDATE` without `WHERE` | Every run reset AI labels to Neutral; refused by MySQL safe-update mode; app lists disagreed with the C++ rules |
| 5 | Monitor's writer thread exits if the database is down | Main loop keeps queueing forever (unbounded memory), all data lost; no reconnect |
| 6 | `GetWindowTextA` (ANSI) in the tracker | Non-English window titles garbled |
| 7 | Closing the console window / SIGTERM on Windows | Up to 15 s of rows lost, session never closed |
| 8 | Daily view grouped by session start date | Time after midnight counted on the wrong day |
| 9 | Window titles inserted with `innerHTML` unescaped | **Stored XSS**: a web page title could run script in the dashboard; Flask `debug=True` |
| – | Two separate trackers on two databases | Dashboard never showed the MySQL data or AI labels |
| – | Classifier trained without any held-out evaluation | Its accuracy and 70 % threshold were unsupported |
| – | Binaries (`monitor.exe`, `title_model.joblib`) committed | Repository hygiene |

---

## 2. Test log by phase

Each row: what was tested, how, and the observed result. **FAIL → fixed**
means the test exposed a bug that was then fixed and re-tested.

### Phase 1: Fixing the original defects (SQLite era)

| Test | Method | Result |
|---|---|---|
| Dashboard API | Built a SQLite DB from the tracker's own schema, sample data incl. an XSS title, a Burmese title, a session across midnight, an unclosed session; called every endpoint with Flask's test client | **Pass:** all endpoints 200; overrides set/reset; bad label → 400; missing DB → 404 |
| Focus score formula | Compared API value with a hand calculation | **Pass:** 80.3 both (90 productive / 110 active min, 2 switches) |
| XSS escaping | Ran `esc()` on `<img src=x onerror=alert(1)>` | **Pass:** rendered as inert text |
| Classifier evaluation step | Synthetic titles with duplicates | **Pass:** duplicates removed, held-out report printed, insufficient data correctly skipped |
| Python syntax | `py_compile` on all Python files | **Pass** |

### Phase 2: First build with MinGW and a live run

| Test | Method | Result |
|---|---|---|
| Build `tracker/` | CMake + Ninja + GCC 16.2 | **FAIL → fixed:** GCC rejected `Config cfg = {}`; replaced with two constructors; then 0 errors, 0 warnings with `-Wall -Wextra` |
| Static linking | `objdump -p` on the `.exe` | **Pass:** only Windows system DLLs needed |
| Live tracking | 23 s run, window closed | **Pass:** 6 activity rows, session closed with `end_time` |

### Phase 3: PostgreSQL, single tracker, OS features

| Test | Method | Result |
|---|---|---|
| Schema and views | `db/setup.ps1` on PostgreSQL 18.7 | **Pass:** 10 tables, 6 views; second run harmless |
| Password handling | Login via `pgpass.conf` only | **Pass:** no password in the project |
| libpq link | Build against PostgreSQL | **FAIL → fixed:** linked the MSVC static `libpq.a` (duplicate pthread symbols, missing LDAP); switched to the `libpq.lib` import library |
| Unit tests: session logic | `focus_tests.exe` (switch debounce, idle, stop) | **Pass:** 36/36 checks |
| Unit test: bounded buffer | 4 producer threads × 20,000 items, capacity 8, 1 consumer | **Pass:** nothing lost or duplicated, peak depth 8/8, 22,401 producer waits (back-pressure) |
| Live run, timed | `--minutes 0.4 --proc 3` | **Pass:** stopped by itself, 11 batches written, 0 dropped, 0 retries, queue peak 2/64 |
| Console output from 2 threads | Read the run's log | **FAIL → fixed:** lines from two threads interleaved mid-line; added a mutex-guarded logger |
| Ctrl+C from a helper process | `GenerateConsoleCtrlEvent` | Helper failed (exit 1); process was force-killed; process samples were written, session left open (expected for a kill) |
| Classifier on PostgreSQL | Throwaway DB `study_tracker_test` (dropped afterwards) | **Pass:** confident labels applied, low-confidence ones recorded but not applied, re-run found nothing new |
| Category priority | Override Chrome → productive | **Pass:** user override beats AI label (design trade-off documented) |
| Dashboard on PostgreSQL | All endpoints against real data | **Pass** |

### Phase 4: Dashboard redesigns (visual checks with screenshots)

| Finding | Result |
|---|---|
| Short sessions showed "0 % productive" (API rounded to 0.01 h) | **FAIL → fixed:** exact seconds added to the API |
| Background-CPU chart used the "distracting" colour | **Fixed:** OS data drawn in a neutral colour |
| Mobile bottom tab bar appeared at the top | **FAIL → fixed:** `backdrop-filter` made the top bar the containing block of the fixed tab bar |
| Range labels wrapping, "3 h" splitting across lines, "3.0 h" | **Fixed** |
| Dark mode, 390 px width, no horizontal scroll | **Pass** |

### Phase 5: Focus button (dashboard starts/stops the tracker)

| Test | Method | Result |
|---|---|---|
| Cross-site request | POST with `Origin: https://evil.example` | **Pass:** 403 |
| Non-JSON request | POST as `text/plain` | **Pass:** 415 |
| Second tracker | Start from dashboard, then by hand | **Pass:** refused by the named mutex (exit code 2) |
| End now | Named stop event | **Pass:** stopped in 0.14 s, session closed, no process left |
| Path in app name (`../../evil`) | POST to block list | **FAIL → fixed:** was accepted as `evil.exe`; names containing `/` or `\` now rejected |

### Phase 6: Block list limited to installed apps

| Test | Method | Result |
|---|---|---|
| Installed-app scan | Start-menu shortcuts + Store packages | 133 raw entries → filters (Windows tools, uninstallers, helpers, `Get-StartApps`) → **53** blockable apps in 0.7–1.2 s |
| Not installed | Block `discord.exe` | **Pass:** 400 "isn't installed on this PC" |
| Part of Windows | Block `explorer.exe` | **Pass:** 400 "can't be blocked" |
| Page load race | Picker requested apps before the user was known | **FAIL → fixed:** `user=null` request; moved into the main load |
| Search | Typed "sol" | **FAIL → fixed:** matched `pad.console.host.exe`; now matches names, file names only from the start. The test blocked Power Automate by accident; it was unblocked again |

### Phase 7: Portable database (no PostgreSQL install)

| Test | Method | Result |
|---|---|---|
| Portable binaries | `scripts/get_portable_postgres.ps1` | **Pass:** 69.1 MB, PostgreSQL 18.7 |
| First start | `portable_db.py start` | **FAIL → fixed:** Python hung; `postgres` inherited the output pipes. Also an interrupted first run left no database; now repaired on every start |
| True first run | Data folder deleted, start again | **Pass:** created in 2.4 s, 10 tables, 6 views, listens on 127.0.0.1:5544 only |
| Cold start / warm start | Stop, start | **Pass:** ≈0.5 s each |
| Whole app in portable mode | Dashboard + focus session | **Pass:** tracker found the DB via `runtime.ini`; installed DB untouched (3 sessions before and after) |
| Release zip contents | `scripts/make_release.ps1` | **FAIL → fixed:** new files were missing (packed only committed files); then complete, no config/passwords/data, 32.4 MB |
| Fresh unzip + `start.bat` | Unzipped into an empty folder | **FAIL → fixed:** `". was unexpected at this time"` (a `)` inside an `if` block); also a half-finished install would never retry (marker file added). Then: packages installed, DB started, dashboard opened |
| Unzip into Temp | Same, in `%TEMP%` | `start.bat` disappeared after extraction; suspected antivirus (not confirmed); README says to unzip outside Temp |

### Phase 8: Publishing

| Test | Method | Result |
|---|---|---|
| GitHub release | `gh release create v1.0.0` | **FAIL → fixed:** short commit hash rejected as target; used `main` |
| Upload integrity | Downloaded the asset again | **Pass:** SHA-256 identical to the local zip |
| Commit attribution | Checked commit messages on GitHub | Claude trailer removed by history rewrite (run by the user); GitHub API lists 2 contributors |

### Phase 9: Focus-session details and the new AI

| Test | Method | Result |
|---|---|---|
| Schema additions | `schema.sql` applied twice | **Pass:** `focus_blocks`, `planned_minutes`, `session_live` created; idempotent |
| Live stats | 15-min session from the dashboard | **FAIL → fixed:** stayed at "0 s" because the open window is only saved on a switch; added `session_live`, published every 5 s |
| Unit test: live status | New test | **Pass:** 41/41 checks |
| Live panel after fix | Real session | **Pass:** current app shown and timed; ended cleanly, live row deleted |
| Summary and history | Demo user 99 | **Pass:** completed vs ended early, blocked attempts, timeline |
| Layout | Screenshots | **Fixed:** tab label wrapping, horizontal scroll at 1280 px, score alignment, history columns |

**AI model comparison** (614 generated titles, 57 templates; macro-F1):

| Model | Known sites | Unseen sites |
|---|---|---|
| Majority class (baseline) | 0.199 | 0.199 |
| Naive Bayes, words (previous model) | 0.842 | 0.560 |
| **Complement NB, words + chars (chosen)** | **0.884** | **0.699** |
| Logistic regression C=1 | 0.879 | 0.639 |
| Logistic regression C=5 | 0.876 | 0.619 |
| Linear SVM, calibrated | 0.864 | 0.592 |

- First evaluation used one held-out test set of 11 templates: 0.431, too noisy. **Changed to nested grouped cross-validation:** **0.679 ± 0.102** on unseen sites. A plain random split would have reported 0.967.
- Threshold 0.96 → precision 0.90, labels 60 % of productive/distracting titles (unseen sites).
- Applied to activity: 104 browser rows checked, 89 labelled.

### Phase 10: Close blocked apps + Windows notification

| Test | Method | Result |
|---|---|---|
| Build | New notifier thread + close policy | **Pass:** 0 warnings, 41/41 checks |
| Close a blocked app | 1-min session with `--close --block charmap.exe`; Character Map brought to the front | **Pass:** `[focus] closed charmap.exe` (polite `WM_CLOSE` was enough); stored as `closed` in `focus_blocks` |
| Background window | Character Map opened behind another window | Correctly ignored (only the window in front is acted on) |
| Dashboard flag | Start with `on_block: close` | **Pass:** tracker command line contains `--close` |
| Validation | `on_block: "explode"` | **Pass:** rejected with a message |
| Reporting | Session 65 detail | **Pass:** `charmap.exe: closed 1×` |

---

## 3. Final result

| Area | Before | After |
|---|---|---|
| Dashboard | Did not start | Runs; 5 tabs, live focus panel, summaries, history; light/dark; phone layout; glass theme preview |
| Database | No schema in repo; two databases | One PostgreSQL schema (12 tables, 6 views), one-command setup, or a portable database with no install |
| Tracker | Could not be built | Builds with 0 warnings; 4 threads; 41/41 unit tests |
| OS concepts shown | Threads (monitor only) | Bounded buffer, mutexes, atomics, process snapshots, CPU scheduling time, named mutex + event (IPC), Win32 message loop, process termination |
| Security | Stored XSS, debug server | Output escaped, CSRF protection, input validation, no passwords in files |
| AI | Untested Naive Bayes | 6 models compared with grouped and nested validation, data-driven threshold, report |
| Distribution | Manual setup | 32 MB release zip, `start.bat`, published as GitHub release v1.0.0 |

---

## 4. Not tested / known limitations

- **Another computer.** Everything above ran on one PC. Test on a teammate's PC or Windows Sandbox.
- **Closing the tracker window with X** (console close event): not automated; Ctrl+C, `--minutes` and the stop event were tested.
- **Force-close path** (app ignores `WM_CLOSE` for 1.5 s → `TerminateProcess`): implemented, not triggered in a test.
- **Windows notification appearance:** the notify call ran without errors, but the toast itself was not captured on screen by the tester.
- **AI on real browsing:** only generated demo titles were used; label real titles (`source = 'user'`) and retrain to measure real accuracy.
- **Antivirus removing `start.bat` in Temp:** observed once, cause not confirmed.
- **Glass theme on slow laptops:** blur performance not measured.

## 5. How to re-run the tests

```powershell
.\tracker\build\focus_tests.exe                               # C++ unit tests
python ai\title_classifier.py train                           # model comparison, writes ai\model_report.md
powershell -ExecutionPolicy Bypass -File scripts\make_release.ps1   # then follow RELEASING.md step 5
```
