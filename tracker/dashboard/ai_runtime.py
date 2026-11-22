"""Runs the title classifier inside the dashboard, so nobody has to remember to.

  - every minute, new browser rows in activity_log are classified (the same
    code as `python ai/title_classifier.py classify`)
  - the live focus panel asks predict() about the tab that is open right now

If scikit-learn is missing or no model has been trained yet, everything here
quietly does nothing and the website rules / app defaults still apply.
The model file is one you trained yourself (ai/title_model.joblib, never
downloaded), so loading it with joblib is safe.
"""
import os
import sys
import threading
import time
from pathlib import Path

# FOCUSOS_ROOT: set by desktop.py when packaged as an .exe (the folder holding it).
AI_DIR = Path(os.environ.get("FOCUSOS_ROOT") or Path(__file__).resolve().parents[2]) / "ai"
INTERVAL_SECONDS = 60

_lock = threading.Lock()
_bundle = None
_bundle_mtime = None
_status = {"available": False, "model_name": None, "last_run": None, "last_message": "not started"}


def _classifier_module():
    if str(AI_DIR) not in sys.path:
        sys.path.insert(0, str(AI_DIR))
    import title_classifier   # noqa: E402  (needs scikit-learn)
    return title_classifier


def _load_bundle():
    """Load (or reload after retraining) the saved model; None if unavailable."""
    global _bundle, _bundle_mtime
    try:
        tc = _classifier_module()
    except ImportError:
        _status.update(available=False, last_message="scikit-learn not installed")
        return None
    path = tc.MODEL_PATH
    if not path.exists():
        _status.update(available=False, last_message="no model trained yet")
        return None
    mtime = path.stat().st_mtime
    with _lock:
        if _bundle is None or mtime != _bundle_mtime:
            import joblib
            loaded = joblib.load(path)
            if not isinstance(loaded, dict):
                _status.update(available=False, last_message="old model format, retrain it")
                return None
            _bundle, _bundle_mtime = loaded, mtime
        _status.update(available=True, model_name=_bundle["model_name"])
        return _bundle


def predict(title: str):
    """(label, confidence, applied) for one title, or None if no model.

    applied is False when the model is not confident enough (below its
    saved threshold) or says neutral: then the tab keeps its default.
    """
    bundle = _load_bundle()
    if bundle is None or not title:
        return None
    proba = bundle["model"].predict_proba([title])[0]
    i = int(proba.argmax())
    label, conf = str(bundle["model"].classes_[i]), float(proba[i])
    return label, conf, (label != "neutral" and conf >= bundle["threshold"])


def classify_new_rows(db_params: dict) -> str:
    if _load_bundle() is None:
        return _status["last_message"]
    tc = _classifier_module()
    import contextlib
    import io
    out = io.StringIO()
    with contextlib.redirect_stdout(out):          # the CLI function prints its summary
        tc.classify_browser_titles(db_params, None, recheck=False)
    return out.getvalue().strip()


def status() -> dict:
    bundle = _load_bundle()
    out = dict(_status)
    if bundle is not None:
        out["metrics"] = bundle.get("metrics", {})
        out["trained_at"] = bundle.get("trained_at")
        out["n_samples"] = bundle.get("n_samples")
        out["sources"] = bundle.get("sources")
    out["training"] = _training["running"]
    out["training_message"] = _training["message"]
    return out


def uncertain_titles(rows, limit: int = 12):
    """Active learning: the titles the model is least sure about come first.

    rows: [(title, seconds)] of browser titles not yet labelled by the user.
    Labelling these teaches the model the most per click.
    """
    bundle = _load_bundle()
    if bundle is None or not rows:
        return [{"title": t, "seconds": s, "guess": None, "confidence": None} for t, s in rows[:limit]]
    proba = bundle["model"].predict_proba([t for t, _ in rows])
    classes = bundle["model"].classes_
    out = []
    for (title, secs), p in zip(rows, proba):
        i = int(p.argmax())
        out.append({"title": title, "seconds": secs, "guess": str(classes[i]), "confidence": round(float(p[i]), 3)})
    out.sort(key=lambda r: r["confidence"])
    return out[:limit]


_training = {"running": False, "message": ""}


def retrain_in_background(db_params: dict) -> bool:
    """Retrain on all labelled titles, then re-label every browser row. False if already running."""
    if _training["running"]:
        return False
    _training.update(running=True, message="Training…")

    def job():
        import contextlib
        import io
        try:
            tc = _classifier_module()
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                tc.train_model(db_params, "all")
                tc.classify_browser_titles(db_params, None, recheck=True)
            lines = [l for l in out.getvalue().splitlines() if l.strip()]
            _training["message"] = " ".join(l.strip() for l in lines[-4:])
        except Exception as e:
            _training["message"] = f"Training failed: {e}"
        finally:
            _training["running"] = False

    threading.Thread(target=job, daemon=True, name="ai-retrain").start()
    return True


def start_background(get_db_params) -> None:
    def loop():
        while True:
            try:
                msg = classify_new_rows(get_db_params())
                _status.update(last_run=time.strftime("%H:%M:%S"), last_message=msg)
            except Exception as e:                   # never let the loop die
                _status.update(last_run=time.strftime("%H:%M:%S"), last_message=f"error: {e}")
            time.sleep(INTERVAL_SECONDS)
    threading.Thread(target=loop, daemon=True, name="ai-classifier").start()
