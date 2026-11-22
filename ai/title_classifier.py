"""FocusOs window-title classifier: productive / neutral / distracting.

  python ai/title_classifier.py train      compare models, validate honestly, save the best + a report
  python ai/title_classifier.py classify   label browser rows the model hasn't seen yet
  python ai/title_classifier.py classify --recheck    re-label every browser row (after retraining)

How the model is chosen and scored (see ai/model_report.md after training)
  1. Titles are cleaned: browser suffixes (" - Google Chrome", ...) removed,
     numbers folded to 0, lower-cased.
  2. Two questions, two kinds of cross-validation:
       known sites   new titles from sites/patterns seen in training
                     (folds grouped by exact title: no duplicates across folds)
       unseen sites  titles from sites/patterns never seen in training
                     (folds grouped by template: much harder)
     Real use is in between. A plain random split is also shown, only to
     make visible how much near-duplicate titles inflate a careless score.
  3. The headline estimate uses NESTED grouped CV: in each outer fold the
     model is chosen on the training part only, then scored on the held-out
     templates, so the choice of model never sees its own test data.
  4. The final model is the candidate with the best unseen-site score,
     refitted on all data.
  5. The confidence threshold is the lowest one that keeps precision >= 90%
     on its cross-validated predictions: below it, rows stay unlabelled.

Why not a transformer (e.g. sentence embeddings)? It may understand meaning
better, but needs PyTorch (~500 MB), which would break the 32 MB portable
release, and it needs far more labelled data to show its advantage. A linear
model on word + character n-grams is the strong, standard baseline for short
texts and runs in milliseconds on a laptop.
"""
import argparse
import configparser
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import joblib
import numpy as np
import psycopg
from sklearn.base import clone
from sklearn.calibration import CalibratedClassifierCV
from sklearn.dummy import DummyClassifier
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (accuracy_score, classification_report, confusion_matrix, f1_score,
                             log_loss)
from sklearn.model_selection import GroupKFold, StratifiedKFold, cross_val_predict
from sklearn.naive_bayes import ComplementNB, MultinomialNB
from sklearn.pipeline import FeatureUnion, Pipeline
from sklearn.preprocessing import FunctionTransformer
from sklearn.svm import LinearSVC

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "tracker" / "config.ini"
MODEL_PATH = PROJECT_ROOT / "ai" / "title_model.joblib"
REPORT_PATH = PROJECT_ROOT / "ai" / "model_report.md"

LABELS = ["productive", "neutral", "distracting"]
VALID_LABELS = set(LABELS)
BROWSER_PROCESSES = ("chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe")
TARGET_PRECISION = 0.90       # for the confidence threshold
RANDOM_STATE = 42

# ----------------------------------------------------------------- database


def load_database_config(config_path: Path) -> dict:
    """Same rule as the dashboard: no config.ini or mode = portable -> FocusOs's own database."""
    parser = configparser.ConfigParser()
    found = bool(parser.read(config_path))
    db = parser["database"] if parser.has_section("database") else {}
    mode = str(db.get("mode", "server" if found else "portable")).strip().lower()
    if mode == "portable":
        app_dir = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "FocusOs"
        params = {"host": "127.0.0.1", "port": 5544, "user": "focus_user", "dbname": "study_tracker",
                  "passfile": str(app_dir / "pgpass.conf")}   # see portable_db.PGPASS
    else:
        params = {"host": db.get("host", "localhost"), "port": int(db.get("port", 5432)),
                  "user": db.get("user", "focus_user"), "dbname": db.get("database", "study_tracker")}
        if db.get("password"):
            params["password"] = db["password"]   # otherwise libpq reads pgpass.conf
    return {**params, "connect_timeout": 5, "application_name": "focus_title_classifier"}


# ----------------------------------------------------------------- preprocessing

from title_features import _clean_all, clean_title  # noqa: E402,F401  (importable: see title_features.py)


def _features() -> FeatureUnion:
    # Words catch meaning ("lecture", "netflix"); character n-grams catch
    # site names, typos and word pieces ("stackoverflow", "leetcode").
    return FeatureUnion([
        ("words", TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True, min_df=1)),
        ("chars", TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), sublinear_tf=True, min_df=2)),
    ])


def _pipe(clf, features=None) -> Pipeline:
    return Pipeline([
        ("clean", FunctionTransformer(_clean_all)),
        ("features", features if features is not None else _features()),
        ("clf", clf),
    ])


def candidates() -> dict:
    words_only = TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)
    return {
        "Majority class (baseline)": _pipe(DummyClassifier(strategy="most_frequent"), words_only),
        "Naive Bayes, words (previous model)": _pipe(MultinomialNB(alpha=0.5), TfidfVectorizer(ngram_range=(1, 2), sublinear_tf=True)),
        "Complement NB, words + chars": _pipe(ComplementNB(alpha=0.3)),
        "Logistic regression, words + chars (C=1)": _pipe(LogisticRegression(C=1.0, max_iter=3000, class_weight="balanced")),
        "Logistic regression, words + chars (C=5)": _pipe(LogisticRegression(C=5.0, max_iter=3000, class_weight="balanced")),
        "Linear SVM, words + chars (calibrated)": _pipe(CalibratedClassifierCV(
            LinearSVC(C=0.5, class_weight="balanced"), method="sigmoid", cv=3)),
    }


# ----------------------------------------------------------------- training


def _load_samples(conn, source: str):
    sql = "SELECT window_title, label, source, COALESCE(template_group, '') FROM title_training_samples"
    params = ()
    if source != "all":
        sql += " WHERE source = %s"
        params = (source,)
    rows = conn.execute(sql, params).fetchall()
    titles = [r[0] for r in rows]
    labels = [r[1] for r in rows]
    # Group = template for demo titles; for your own labels the cleaned title,
    # so exact duplicates can never sit on both sides of a split.
    groups = [r[3] if r[3] else "t:" + clean_title(r[0]) for r in rows]
    return titles, labels, groups, Counter(r[2] for r in rows)


def _threshold_for_precision(proba, y_true, classes, target):
    """Lowest confidence at which confident, non-neutral labels are >= target precise."""
    best = np.max(proba, axis=1)
    pred = np.array(classes)[np.argmax(proba, axis=1)]
    acting = pred != "neutral"
    for thr in np.round(np.arange(0.40, 0.991, 0.01), 2):
        mask = acting & (best >= thr)
        if mask.sum() >= 5 and (pred[mask] == np.array(y_true)[mask]).mean() >= target:
            return float(thr)
    return 0.99


def _coverage_precision(proba, y_true, classes, thr):
    best = np.max(proba, axis=1)
    pred = np.array(classes)[np.argmax(proba, axis=1)]
    mask = (pred != "neutral") & (best >= thr)
    non_neutral_truth = np.array(y_true) != "neutral"
    precision = float((pred[mask] == np.array(y_true)[mask]).mean()) if mask.any() else float("nan")
    # Share of truly productive/distracting rows that got a (correct or wrong) label.
    coverage = float((mask & non_neutral_truth).sum() / max(non_neutral_truth.sum(), 1))
    return precision, coverage


def _proba_fixed(proba):
    """Clip away exact zeros and re-normalise, so log loss is defined."""
    p = np.clip(proba, 1e-6, 1.0)
    return p / p.sum(axis=1, keepdims=True)


def _cv_scores(pipe, X, y, groups, n_splits):
    """Out-of-fold probabilities and macro-F1 / accuracy / log loss for one candidate."""
    k = min(n_splits, len(set(groups)))
    proba = cross_val_predict(clone(pipe), X, y, groups=groups, cv=GroupKFold(n_splits=k), method="predict_proba")
    classes = sorted(set(y))
    pred = np.array(classes)[np.argmax(proba, axis=1)]
    return proba, classes, {
        "macro_f1": f1_score(y, pred, average="macro"),
        "accuracy": accuracy_score(y, pred),
        "log_loss": log_loss(y, _proba_fixed(proba), labels=classes),
    }


def _nested_unseen(X, y, g, names):
    """Nested grouped CV: choose the model inside each outer fold, score it on held-out templates."""
    outer = GroupKFold(n_splits=min(5, len(set(g))))
    scores, chosen = [], []
    for train_idx, test_idx in outer.split(X, y, g):
        inner = {n: _cv_scores(candidates()[n], X[train_idx], y[train_idx], g[train_idx], 4)[2]["macro_f1"]
                 for n in names}
        pick = max(inner, key=inner.get)
        model = clone(candidates()[pick]).fit(X[train_idx], y[train_idx])
        scores.append(f1_score(y[test_idx], model.predict(X[test_idx]), average="macro"))
        chosen.append(pick)
    return float(np.mean(scores)), float(np.std(scores)), Counter(chosen)


def train_model(database_config: dict, source: str = "all") -> None:
    with psycopg.connect(**database_config) as conn:
        titles, labels, groups, sources = _load_samples(conn, source)
    _fit_and_save(titles, labels, groups, sources, MODEL_PATH, write_report=True)


def train_release_model(out_path: Path) -> None:
    """The model shipped in the release zip: trained ONLY on the generated demo
    titles (in memory, fixed seed), never on anyone's real window titles,
    because a TF-IDF model stores words from its training titles."""
    from demo_data import generate_titles
    rows = generate_titles()
    titles = [t for t, _, _ in rows]
    labels = [l for _, l, _ in rows]
    groups = [g for _, _, g in rows]
    _fit_and_save(titles, labels, groups, Counter({"demo": len(rows)}), Path(out_path), write_report=False)


def _fit_and_save(titles, labels, groups, sources, model_path: Path, write_report: bool) -> None:
    if len(titles) < 30 or not set(labels) <= VALID_LABELS or len(set(labels)) < 2:
        raise ValueError("Need at least 30 labelled titles with at least two of: productive, neutral, distracting. "
                         "Add your own to title_training_samples, or run: python ai/demo_data.py titles")
    X, y, g = np.array(titles, dtype=object), np.array(labels), np.array(groups)
    title_groups = np.array(["t:" + clean_title(t) for t in titles])
    n_groups = len(set(groups))
    print(f"{len(X)} labelled titles in {n_groups} groups; sources: {dict(sources)}; labels: {dict(Counter(labels))}")

    # 1. Every candidate, both questions.
    names = list(candidates().keys())
    results, oof_unseen = {}, {}
    for name in names:
        proba_u, classes, unseen = _cv_scores(candidates()[name], X, y, g, 5)
        _, _, known = _cv_scores(candidates()[name], X, y, title_groups, 5)
        results[name] = {"unseen": unseen, "known": known}
        oof_unseen[name] = (proba_u, classes)
        print(f"  {name:45s} unseen sites F1 {unseen['macro_f1']:.3f} | known sites F1 {known['macro_f1']:.3f}")

    real_names = [n for n in names if not n.startswith("Majority")]
    best_name = max(real_names, key=lambda n: results[n]["unseen"]["macro_f1"])
    best_pipe = candidates()[best_name]

    # 2. Unbiased headline estimate: nested grouped CV over the whole selection procedure.
    nested_mean, nested_std, chosen = _nested_unseen(X, y, g, real_names)

    # 3. For contrast only: what a plain random split would claim.
    naive = cross_val_predict(clone(best_pipe), X, y, cv=StratifiedKFold(5, shuffle=True, random_state=RANDOM_STATE))
    naive_f1 = f1_score(y, naive, average="macro")

    # 4. Threshold and error analysis from the winner's unseen-site predictions (conservative).
    proba, classes = oof_unseen[best_name]
    threshold = _threshold_for_precision(proba, y, classes, TARGET_PRECISION)
    prec, cov = _coverage_precision(proba, y, classes, threshold)
    pred = np.array(classes)[np.argmax(proba, axis=1)]
    report = classification_report(y, pred, labels=LABELS, zero_division=0)
    cm = confusion_matrix(y, pred, labels=LABELS)
    errors = sorted([(float(np.max(p)), t, truth, pr) for p, t, truth, pr in zip(proba, X, y, pred) if truth != pr],
                    reverse=True)[:12]

    # 5. Final model on all data.
    final = clone(best_pipe).fit(X, y)
    joblib.dump({
        "model": final, "model_name": best_name, "threshold": threshold,
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "n_samples": int(len(X)), "sources": dict(sources),
        "metrics": {"unseen_sites_f1": results[best_name]["unseen"]["macro_f1"],
                    "known_sites_f1": results[best_name]["known"]["macro_f1"],
                    "nested_unseen_f1_mean": nested_mean, "nested_unseen_f1_std": nested_std,
                    "random_split_f1": naive_f1, "precision_at_threshold": prec, "coverage_at_threshold": cov},
    }, model_path)

    if write_report:
        _write_report(results, best_name, nested_mean, nested_std, chosen, naive_f1, threshold, prec, cov,
                      report, cm, errors, len(X), n_groups, sources, Counter(labels))
    print(f"\nChosen: {best_name}")
    print(f"  known sites F1 {results[best_name]['known']['macro_f1']:.3f} | unseen sites F1 "
          f"{results[best_name]['unseen']['macro_f1']:.3f} | nested estimate {nested_mean:.3f} +/- {nested_std:.3f} "
          f"| random split would claim {naive_f1:.3f}")
    print(f"  threshold {threshold:.2f}: precision {prec:.2f}, labels {cov:.0%} of productive/distracting rows (unseen sites)")
    print(f"Saved {model_path}" + (f" and {REPORT_PATH.name}" if write_report else ""))


def _write_report(results, best, nested_mean, nested_std, chosen, naive_f1, thr, prec, cov,
                  report, cm, errors, n, n_groups, sources, label_counts):
    demo = sources.get("demo", 0)
    lines = [
        "# Title classifier: model report",
        "",
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} by `python ai/title_classifier.py train`.",
        "",
        f"**Data:** {n} labelled titles in {n_groups} groups ({dict(sources)}); labels {dict(label_counts)}.",
    ]
    if demo:
        lines += ["",
                  f"> **{demo} of the titles are generated demo data.** These numbers show that the pipeline works "
                  "and that the evaluation is honest; they are *not* an estimate of accuracy on your real browsing. "
                  "Label real titles (`source = 'user'`) and retrain with `--source user` to measure that."]
    lines += [
        "",
        "## Two questions",
        "",
        "- **Known sites:** a new title from a site or pattern the model has seen examples of "
        "(cross-validation grouped by exact title, so no duplicate is on both sides). The common case.",
        "- **Unseen sites:** a title from a site or pattern it has never seen "
        "(cross-validation grouped by template). The hard case.",
        "",
        "Real use falls in between: most browsing is on a handful of familiar sites, plus the occasional new one.",
        "",
        "## Model comparison (macro-F1, 5-fold grouped cross-validation)",
        "",
        "| Model | Known sites | Unseen sites | Log loss (unseen) |",
        "|---|---|---|---|",
    ]
    for name, r in sorted(results.items(), key=lambda kv: -kv[1]["unseen"]["macro_f1"]):
        mark = " **(chosen)**" if name == best else ""
        lines.append(f"| {name}{mark} | {r['known']['macro_f1']:.3f} | {r['unseen']['macro_f1']:.3f} | "
                     f"{r['unseen']['log_loss']:.3f} |")
    picks = ", ".join(f"{k} ({v}x)" for k, v in chosen.most_common())
    lines += [
        "",
        f"**Headline estimate for unseen sites (nested grouped CV): macro-F1 {nested_mean:.3f} +/- {nested_std:.3f}.** "
        f"The model was chosen inside each outer fold without seeing that fold's templates (choices: {picks}), "
        "so this number is not inflated by picking the winner on its own test data.",
        "",
        f"For contrast, a plain random split would report **{naive_f1:.3f}** for the chosen model. "
        "The gap is what near-duplicate titles do to a careless evaluation.",
        "",
        "## Chosen model on unseen sites",
        "",
        f"- Confidence threshold **{thr:.2f}**: the lowest that keeps precision at least {TARGET_PRECISION:.0%}. "
        f"At it, the model labels **{cov:.0%}** of productive/distracting titles with precision **{prec:.2f}**; "
        "everything else keeps its app's default category. Being unsure and staying quiet is the intended behaviour.",
        "",
        "```",
        report.rstrip(),
        "```",
        "",
        "Confusion matrix (rows = true, columns = predicted):",
        "",
        "| | productive | neutral | distracting |",
        "|---|---|---|---|",
    ]
    for lab, row in zip(LABELS, cm):
        lines.append(f"| **{lab}** | " + " | ".join(str(v) for v in row) + " |")
    lines += ["", "## Most confident mistakes (unseen sites)", "",
              "| Confidence | Title | True | Predicted |", "|---|---|---|---|"]
    for conf, title, truth, pred in errors:
        lines.append(f"| {conf:.2f} | {str(title).replace('|', '/')} | {truth} | {pred} |")
    lines += [
        "",
        "Some mistakes are deliberate label noise: the demo data flips about 2% of labels, like a tired human labeller.",
        "",
        "## What this means",
        "",
        "- The model is reliable on sites it has examples of, and much weaker on sites it has never seen: a title "
        "classifier can only learn the vocabulary it is shown. More *different* sites in the training data helps "
        "far more than more titles from the same site.",
        "- Only the window title is used. A title like \"YouTube\" on its own carries no information about the video.",
        "- The label policy (what counts as productive) is a choice; the model learns whatever the labels say.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ----------------------------------------------------------------- classify


def classify_browser_titles(database_config: dict, threshold, recheck: bool = False) -> None:
    if not MODEL_PATH.exists():
        raise FileNotFoundError("No trained model found. Run: python ai/title_classifier.py train")
    bundle = joblib.load(MODEL_PATH)          # only load model files you trained yourself
    if not isinstance(bundle, dict):
        raise ValueError("Old model format. Retrain: python ai/title_classifier.py train")
    model, model_name = bundle["model"], bundle["model_name"]
    thr = bundle["threshold"] if threshold is None else threshold

    query = """
        SELECT l.log_id, l.window_title
        FROM activity_log AS l
        JOIN applications AS a ON a.app_id = l.app_id
        WHERE a.process_name = ANY(%s)
          AND l.window_title <> ''
    """
    if not recheck:
        query += " AND NOT EXISTS (SELECT 1 FROM ai_predictions p WHERE p.activity_log_id = l.log_id)"

    # One transaction: labels and their audit rows are saved together or not at all.
    with psycopg.connect(**database_config) as connection:
        cursor = connection.cursor()
        cursor.execute(query, (list(BROWSER_PROCESSES),))
        rows = cursor.fetchall()
        if not rows:
            print("No new browser titles to classify.")
            return

        proba = model.predict_proba([r[1] for r in rows])
        classes = model.classes_
        audit, applied = [], 0
        for (log_id, _), p in zip(rows, proba):
            i = int(np.argmax(p))
            prediction, confidence = str(classes[i]), float(p[i])
            apply = prediction != "neutral" and confidence >= thr
            applied += apply
            audit.append((log_id, prediction, round(confidence, 4), apply, model_name[:60]))

        cursor.executemany(
            """
            INSERT INTO ai_predictions (activity_log_id, category_id, confidence, applied, model_name)
            VALUES (%s, (SELECT category_id FROM categories WHERE label = %s), %s, %s, %s)
            ON CONFLICT (activity_log_id) DO UPDATE SET
                category_id = EXCLUDED.category_id, confidence = EXCLUDED.confidence,
                applied = EXCLUDED.applied, model_name = EXCLUDED.model_name, predicted_at = now()
            """, audit)
        cursor.execute(
            """
            UPDATE activity_log AS l
            SET ai_category_id = CASE WHEN p.applied THEN p.category_id END
            FROM ai_predictions AS p
            WHERE p.activity_log_id = l.log_id AND l.log_id = ANY(%s)
            """, ([r[0] for r in rows],))
        print(f"Checked {len(rows)} browser segments with '{model_name}'; "
              f"labelled {applied} at confidence >= {thr:.2f}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Train and run the FocusOs title classifier.")
    parser.add_argument("command", choices=("train", "train-release", "classify", "info"))
    parser.add_argument("--out", type=Path, default=None,
                        help="train-release: where to write the demo-only model (needs no database).")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Path to tracker/config.ini")
    parser.add_argument("--source", choices=("all", "user", "demo"), default="all",
                        help="Which labelled titles to train on (default: all).")
    parser.add_argument("--threshold", type=float, default=None,
                        help="Override the saved confidence threshold (0-1).")
    parser.add_argument("--recheck", action="store_true", help="Classify all browser rows again.")
    args = parser.parse_args()

    if args.threshold is not None and not 0.0 <= args.threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1.")
    if args.command == "train-release":
        if args.out is None:
            raise ValueError("train-release needs --out <path>")
        train_release_model(args.out)
        return
    if args.command == "info":
        b = joblib.load(MODEL_PATH)
        print(json.dumps({k: v for k, v in b.items() if k != "model"}, indent=2, default=str))
        return

    database_config = load_database_config(args.config)
    if args.command == "train":
        train_model(database_config, args.source)
    else:
        classify_browser_titles(database_config, args.threshold, args.recheck)


if __name__ == "__main__":
    main()
