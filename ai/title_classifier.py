import argparse
import configparser
from collections import Counter
from pathlib import Path

import joblib
import psycopg
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import classification_report
from sklearn.model_selection import train_test_split
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

MODEL_NAME = "tfidf_multinomial_nb_v1"


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "tracker" / "config.ini"
MODEL_PATH = PROJECT_ROOT / "ai" / "title_model.joblib"

BROWSER_PROCESSES = (
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
)

VALID_LABELS = {"productive", "distracting", "neutral"}


def load_database_config(config_path: Path) -> dict:
    config = configparser.ConfigParser()

    if not config.read(config_path):
        raise FileNotFoundError(f"Could not read config file: {config_path}")

    database = config["database"]

    # Keyword names are libpq's, which psycopg.connect() passes through.
    params = {
        "host": database.get("host", "localhost"),
        "port": database.getint("port", 5432),
        "user": database.get("user", "focus_user"),
        "dbname": database.get("database", "study_tracker"),
        "connect_timeout": 5,
        "application_name": "focus_title_classifier",
    }
    # No password in the file -> libpq reads %APPDATA%\postgresql\pgpass.conf
    if database.get("password"):
        params["password"] = database["password"]
    return params


def build_model() -> Pipeline:
    return Pipeline([
        (
            "tfidf",
            TfidfVectorizer(
                lowercase=True,
                ngram_range=(1, 2),
                sublinear_tf=True,
            ),
        ),
        ("naive_bayes", MultinomialNB(alpha=0.5)),
    ])


def evaluate_model(titles: list, labels: list, threshold: float = 0.70) -> None:
    """Report held-out accuracy so the confidence threshold is backed by evidence.

    Duplicate titles are removed first; otherwise the same title can land in
    both the training and test split and inflate the score (leakage).
    """
    unique = {}
    for title, label in zip(titles, labels):
        unique.setdefault(title.strip().lower(), (title, label))
    titles_u = [t for t, _ in unique.values()]
    labels_u = [l for _, l in unique.values()]

    counts = Counter(labels_u)
    if len(titles_u) < 20 or min(counts.values()) < 2:
        print(
            "Skipping evaluation: need at least 20 distinct titles and "
            f"2 per label (have {len(titles_u)}, per label {dict(counts)})."
        )
        return

    x_train, x_test, y_train, y_test = train_test_split(
        titles_u, labels_u, test_size=0.25, stratify=labels_u, random_state=42,
    )
    model = build_model().fit(x_train, y_train)

    # Baseline: always predict the most common label.
    majority = Counter(y_train).most_common(1)[0][0]
    baseline = sum(y == majority for y in y_test) / len(y_test)

    print(f"Held-out evaluation on {len(y_test)} titles "
          f"(majority-class baseline accuracy: {baseline:.2f})")
    print(classification_report(y_test, model.predict(x_test), zero_division=0))

    # What the classify step actually does: only act when confident.
    probabilities = model.predict_proba(x_test)
    best = probabilities.argmax(axis=1)
    confident = probabilities.max(axis=1) >= threshold
    if confident.any():
        predicted = model.classes_[best]
        correct = sum(
            p == y for p, y, c in zip(predicted, y_test, confident) if c
        )
        print(f"At threshold {threshold:.2f}: labels {confident.mean():.0%} "
              f"of titles, precision {correct / confident.sum():.2f}")
    else:
        print(f"At threshold {threshold:.2f}: no test title is confident enough.")


def train_model(database_config: dict) -> None:
    with psycopg.connect(**database_config) as connection:
        rows = connection.execute(
            "SELECT window_title, label FROM title_training_samples"
        ).fetchall()

    if len(rows) < 15:
        raise ValueError(
            "Add at least 15 labelled title samples before training "
            "(table title_training_samples, labels: productive / neutral / distracting)."
        )

    titles = [row[0] for row in rows]
    labels = [row[1] for row in rows]

    if not set(labels).issubset(VALID_LABELS) or len(set(labels)) < 2:
        raise ValueError(
            "Training data needs at least two valid category labels."
        )

    evaluate_model(titles, labels)

    # Final model is trained on all labelled data.
    model = build_model()
    model.fit(titles, labels)

    joblib.dump(model, MODEL_PATH)

    print(f"Model trained with {len(rows)} labelled titles.")
    print(f"Saved model: {MODEL_PATH}")


def classify_browser_titles(
    database_config: dict,
    threshold: float,
    recheck: bool = False,
) -> None:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            "No trained model found. Run: python title_classifier.py train"
        )

    # Only load models you trained or otherwise trust.
    model = joblib.load(MODEL_PATH)

    # Browser rows the model has not looked at yet (or all, with --recheck).
    # psycopg sends the Python list as a PostgreSQL array, hence = ANY(%s).
    query = """
        SELECT l.log_id, l.window_title
        FROM activity_log AS l
        JOIN applications AS a ON a.app_id = l.app_id
        WHERE a.process_name = ANY(%s)
          AND l.window_title <> ''
    """
    if not recheck:
        query += """
          AND NOT EXISTS (SELECT 1 FROM ai_predictions p
                          WHERE p.activity_log_id = l.log_id)
        """

    # The with-block commits on success and rolls back on any error, so the
    # labels and their audit rows are saved together or not at all.
    with psycopg.connect(**database_config) as connection:
        cursor = connection.cursor()
        cursor.execute(query, (list(BROWSER_PROCESSES),))
        rows = cursor.fetchall()

        if not rows:
            print("No new browser titles to classify.")
            return

        probabilities = model.predict_proba([row[1] for row in rows])
        labels = model.classes_

        audit_rows = []
        applied = 0

        for (log_id, _title), probability_row in zip(rows, probabilities):
            best_index = probability_row.argmax()
            prediction = str(labels[best_index])
            confidence = float(probability_row[best_index])

            # Only act when confident; a confident "neutral" changes nothing.
            apply = prediction != "neutral" and confidence >= threshold
            applied += apply
            audit_rows.append((log_id, prediction, round(confidence, 4), apply, MODEL_NAME))

        # Record every prediction (also the unapplied ones): the audit trail
        # shows what the model thought and stops rows being re-checked.
        cursor.executemany(
            """
            INSERT INTO ai_predictions
                (activity_log_id, category_id, confidence, applied, model_name)
            VALUES (%s, (SELECT category_id FROM categories WHERE label = %s), %s, %s, %s)
            ON CONFLICT (activity_log_id) DO UPDATE SET
                category_id  = EXCLUDED.category_id,
                confidence   = EXCLUDED.confidence,
                applied      = EXCLUDED.applied,
                model_name   = EXCLUDED.model_name,
                predicted_at = now()
            """,
            audit_rows,
        )

        # One set-based UPDATE from the audit table instead of one per row.
        cursor.execute(
            """
            UPDATE activity_log AS l
            SET ai_category_id = CASE WHEN p.applied THEN p.category_id END
            FROM ai_predictions AS p
            WHERE p.activity_log_id = l.log_id
              AND l.log_id = ANY(%s)
            """,
            ([row[0] for row in rows],),
        )

        print(
            f"Checked {len(rows)} browser segments; "
            f"labelled {applied} with confidence >= {threshold:.0%}."
        )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Train and run the Focus Tracker title classifier."
    )

    parser.add_argument(
        "command",
        choices=("train", "classify"),
        help="Train a model or classify neutral browser titles.",
    )

    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help="Path to tracker/config.ini",
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=0.70,
        help="Minimum AI confidence required for an automatic label.",
    )

    parser.add_argument(
        "--recheck",
        action="store_true",
        help="Classify all browser rows again (e.g. after retraining).",
    )

    args = parser.parse_args()

    if not 0.0 <= args.threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1.")

    database_config = load_database_config(args.config)

    if args.command == "train":
        train_model(database_config)
    else:
        classify_browser_titles(database_config, args.threshold, args.recheck)


if __name__ == "__main__":
    main()