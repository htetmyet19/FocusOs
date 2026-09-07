import argparse
import configparser
from pathlib import Path

import joblib
import mysql.connector
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.naive_bayes import MultinomialNB
from sklearn.pipeline import Pipeline

MODEL_NAME = "tfidf_multinomial_nb_v1"


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = PROJECT_ROOT / "monitor" / "config.ini"
MODEL_PATH = PROJECT_ROOT / "ai" / "title_model.joblib"

BROWSER_PROCESSES = (
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
)

VALID_LABELS = {"Productive", "Distracting", "Neutral"}


def load_database_config(config_path: Path) -> dict:
    config = configparser.ConfigParser()

    if not config.read(config_path):
        raise FileNotFoundError(f"Could not read config file: {config_path}")

    database = config["database"]

    return {
        "host": database["host"],
        "port": database.getint("port"),
        "user": database["user"],
        "password": database["password"],
        "database": database["database"],
    }


def train_model(database_config: dict) -> None:
    connection = mysql.connector.connect(**database_config)

    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT window_title, label FROM title_training_samples"
        )
        rows = cursor.fetchall()

    finally:
        connection.close()

    if len(rows) < 15:
        raise ValueError(
            "Add at least 15 labelled title samples before training."
        )

    titles = [row[0] for row in rows]
    labels = [row[1] for row in rows]

    if not set(labels).issubset(VALID_LABELS) or len(set(labels)) < 2:
        raise ValueError(
            "Training data needs at least two valid category labels."
        )

    model = Pipeline([
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

    model.fit(titles, labels)

    joblib.dump(model, MODEL_PATH)

    print(f"Model trained with {len(rows)} labelled titles.")
    print(f"Saved model: {MODEL_PATH}")


def classify_browser_titles(
    database_config: dict,
    threshold: float,
) -> None:
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            "No trained model found. Run: python title_classifier.py train"
        )

    # Only load models you trained or otherwise trust.
    model = joblib.load(MODEL_PATH)

    placeholders = ", ".join(["%s"] * len(BROWSER_PROCESSES))

    query = f"""
        SELECT id, window_title
        FROM activity_logs
        WHERE LOWER(process_name) IN ({placeholders})
          AND category = 'Neutral'
          AND window_title <> '[No window title]'
    """

    connection = mysql.connector.connect(**database_config)

    try:
        cursor = connection.cursor()
        cursor.execute(query, BROWSER_PROCESSES)
        rows = cursor.fetchall()

        if not rows:
            print("No neutral browser titles need classification.")
            return

        titles = [row[1] for row in rows]
        probabilities = model.predict_proba(titles)
        labels = model.classes_

        updates = []
        prediction_audit_rows = []

        for row, probability_row in zip(rows, probabilities):
            best_index = probability_row.argmax()
            prediction = labels[best_index]
            confidence = float(probability_row[best_index])

            # Keep uncertain results neutral.
            if prediction != "Neutral" and confidence >= threshold:
                updates.append((prediction, row[0]))
                prediction_audit_rows.append((
                    row[0],
                    prediction,
                    confidence,
                    MODEL_NAME,
                ))

        if updates:
            cursor.executemany(
                """
                UPDATE activity_logs
                SET category = %s
                WHERE id = %s
                """,
                updates,
            )

        if prediction_audit_rows:
            cursor.executemany(
                """
                INSERT INTO ai_predictions
                (activity_log_id, predicted_category, confidence, model_name)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    predicted_category = VALUES(predicted_category),
                    confidence = VALUES(confidence),
                    model_name = VALUES(model_name),
                    predicted_at = CURRENT_TIMESTAMP
                """,
                prediction_audit_rows,
            )

        if updates or prediction_audit_rows:
            connection.commit()

        print(
            f"Checked {len(rows)} browser segments; "
            f"AI classified {len(updates)} with confidence ≥ {threshold:.0%}."
        )

    finally:
           connection.close()


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
        help="Path to monitor/config.ini",
    )

    parser.add_argument(
        "--threshold",
        type=float,
        default=0.70,
        help="Minimum AI confidence required for an automatic label.",
    )

    args = parser.parse_args()

    if not 0.0 <= args.threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1.")

    database_config = load_database_config(args.config)

    if args.command == "train":
        train_model(database_config)
    else:
        classify_browser_titles(database_config, args.threshold)


if __name__ == "__main__":
    main()