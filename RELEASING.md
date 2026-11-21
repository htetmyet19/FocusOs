# Releasing FocusOs

A release is a **tag** on one commit (for example `v1.0.1`) plus a GitHub
page with notes and a **downloadable zip**. The zip is attached to the
release page, never committed: `dist\` and `pgsql\` are in `.gitignore` so
the repository stays small.

Run every command from the `FocusOs` folder, on Windows.

## Checklist

### 1. Commit and push the code

The release must match code that is on GitHub.

```powershell
git status                      # nothing left uncommitted?
git push origin main
```

### 2. Build the tracker

```powershell
$env:Path = "C:\mingw64\bin;" + $env:Path     # if gcc/cmake aren't on PATH
cmake --build tracker\build
.\tracker\build\focus_tests.exe                # all checks must pass
```

First time on a new PC: `cmake -S tracker -B tracker\build -G Ninja -DCMAKE_BUILD_TYPE=Release` before the build.

### 3. Get the portable PostgreSQL (once, or after upgrading PostgreSQL)

```powershell
powershell -ExecutionPolicy Bypass -File scripts\get_portable_postgres.ps1
```

Copies a minimal PostgreSQL (~70 MB) into `pgsql\`. It needs a PostgreSQL
installed on this PC, or `-Source <folder>` pointing at an extracted
"Windows x86-64 binaries" zip from enterprisedb.com.

### 4. Build the zip

```powershell
powershell -ExecutionPolicy Bypass -File scripts\make_release.ps1
```

Creates `dist\FocusOs-<date>.zip` with the project files, `pgsql\` and the
built tracker. It leaves out `config.ini`, passwords, caches and your data.

### 5. Test the zip like a new user

1. Unzip it into an **empty folder outside Temp** (for example `Documents\FocusOs-test`).
2. Double-click `start.bat`. The first run installs packages and creates a database.
3. Check: the dashboard opens, **Focus mode → Add apps** lists your apps, a short focus session starts and ends.
4. Run `stop.bat`, then delete the test folder.

Don't skip this: the `start.bat` parenthesis bug in 1.0 was only found this way.

### 6. Publish on GitHub

**Website:** <https://github.com/htetmyet19/FocusOs/releases/new>

1. *Choose a tag*: type the new version (e.g. `v1.0.1`), click **Create new tag**, target `main`.
2. Title: `FocusOs 1.0.1`. Notes: what changed and the quick start (copy from the previous release).
3. Drag in the zip from `dist\` and wait for the upload to finish.
4. **Publish release**.

**Command line** (GitHub CLI, `gh auth login` once):

```powershell
gh release create v1.0.1 dist\FocusOs-<date>.zip --target main --title "FocusOs 1.0.1" --notes-file notes.md
```

Use `--target main` (a branch name or the full commit hash; a short hash is rejected).

### 7. Check the release page

Open it, download the zip once, and make sure the size matches `dist\`.

## Version numbers

`vMAJOR.MINOR.PATCH`:

| Change | Example |
|---|---|
| Bug fixes only | `v1.0.0` → `v1.0.1` |
| New features, nothing breaks | `v1.0.1` → `v1.1.0` |
| Breaking changes (old setups or data need work) | `v1.1.0` → `v2.0.0` |

## Common mistakes

- **Releasing before pushing:** the tag then points at old code.
- **Reusing a version number:** every release needs a new tag. If a release is wrong, publish a new version instead of replacing the file, so two different zips are never both called "1.0".
- **Uploading an old zip:** check the date in the file name.
- **Testing from Temp:** some antivirus programs (we saw it with Norton) remove batch files there; test in a normal folder.
