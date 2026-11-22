"""Title cleaning used inside the saved model.

This lives in its own module on purpose: a saved scikit-learn pipeline stores
a *reference* to this function. If it were defined in the script that trains
the model, the reference would be "__main__._clean_all", and the model could
not be loaded from any other program (the dashboard, for example).
"""
import re

_SUFFIX = re.compile(
    r"\s*[-—|]\s*(google chrome|mozilla firefox|brave|microsoft\W*edge|opera|personal - microsoft\W*edge)\s*$",
    re.IGNORECASE)
_MORE_PAGES = re.compile(r"\s+and \d+ more pages?", re.IGNORECASE)


def clean_title(title: str) -> str:
    """'Lecture 5: Deadlocks | NPTEL - YouTube - Google Chrome' -> 'lecture 0: deadlocks | nptel - youtube'"""
    t = (title or "").replace("​", "")
    t = _MORE_PAGES.sub("", t)
    for _ in range(2):                       # e.g. "... - YouTube - Google Chrome"
        t = _SUFFIX.sub("", t)
    t = re.sub(r"\d+", "0", t.lower())
    return re.sub(r"\s+", " ", t).strip()


def _clean_all(titles):
    return [clean_title(t) for t in titles]
