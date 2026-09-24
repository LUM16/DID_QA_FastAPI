"""Compare a preserved effort-prediction CSV with completed Neo4j actuals."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Any, Iterable

from neo4j_client import get_driver, load_env


COMPLETED_ACTUALS_QUERY = """
UNWIND $assignments AS item
MATCH (p:Person)-[:WORKS_ON]->(d:Delivery)
WHERE p.Name = item.person
  AND toString(d.DID) = item.did
  AND toLower(toString(d.DID_Status)) = 'completed'
WITH DISTINCT item, p, d
OPTIONAL MATCH (p)-[time:TIME_ON]->(:DIDN_Month)-[:BELONGS_TO]->(d)
RETURN item.person AS person,
       item.did AS did,
       substring(toString(d.Actual_Delivery_Date), 0, 10) AS completed_date,
       coalesce(sum(toFloat(time.Hour)), 0.0) AS actual_hours,
       count(time) AS actual_time_record_count
"""

REQUIRED_SNAPSHOT_COLUMNS = {
    "person",
    "did",
    "predicted_at",
    "as_of_date",
    "model_version",
    "p50_hours",
    "p80_hours",
    "p90_hours",
}


def read_prediction_snapshot(path: Path) -> list[dict[str, str]]:
    """Read and validate an immutable prediction snapshot CSV."""
    with path.open(encoding="utf-8-sig", newline="") as snapshot_file:
        reader = csv.DictReader(snapshot_file)
        columns = set(reader.fieldnames or [])
        missing = sorted(REQUIRED_SNAPSHOT_COLUMNS - columns)
        if missing:
            raise ValueError(
                f"Prediction snapshot is missing required columns: {', '.join(missing)}."
            )
        rows = [dict(row) for row in reader]
    if not rows:
        raise ValueError("Prediction snapshot contains no rows.")
    return rows


def _read_completed_actuals(assignments: list[dict[str, str]]) -> list[dict[str, Any]]:
    load_env()
    driver = get_driver()
    database = __import__("os").environ.get("NEO4J_DATABASE", "neo4j")
    with driver.session(database=database) as session:
        return [
            record
            for record in session.execute_read(
                lambda tx: tx.run(
                    COMPLETED_ACTUALS_QUERY, {"assignments": assignments}
                ).data()
            )
        ]


def load_completed_actuals(
    assignments: Iterable[dict[str, str]], batch_size: int = 500
) -> dict[tuple[str, str], dict[str, Any]]:
    """Return final recorded hours for snapshot pairs now marked completed."""
    unique_assignments = list(
        {
            (str(item["person"]), str(item["did"]))
            for item in assignments
            if item.get("person") and item.get("did")
        }
    )
    actuals: dict[tuple[str, str], dict[str, Any]] = {}
    for start in range(0, len(unique_assignments), batch_size):
        batch = [
            {"person": person, "did": did}
            for person, did in unique_assignments[start : start + batch_size]
        ]
        for row in _read_completed_actuals(batch):
            actuals[(str(row["person"]), str(row["did"]))] = row
    return actuals


def _number(value: Any, column: str) -> float:
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Expected numeric {column}, got {value!r}.") from exc


def comparison_metrics(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Calculate point-forecast error and calibrated-interval coverage."""
    if not rows:
        return {
            "mae_hours": 0.0,
            "median_absolute_error_hours": 0.0,
            "wape": 0.0,
            "mean_error_hours": 0.0,
            "p80_coverage": 0.0,
            "p90_coverage": 0.0,
        }
    actual = [_number(row["actual_hours"], "actual_hours") for row in rows]
    p50 = [_number(row["p50_hours"], "p50_hours") for row in rows]
    p80 = [_number(row["p80_hours"], "p80_hours") for row in rows]
    p90 = [_number(row["p90_hours"], "p90_hours") for row in rows]
    errors = [actual_value - predicted for actual_value, predicted in zip(actual, p50)]
    absolute_errors = [abs(error) for error in errors]
    return {
        "mae_hours": sum(absolute_errors) / len(absolute_errors),
        "median_absolute_error_hours": float(median(absolute_errors)),
        "wape": sum(absolute_errors) / sum(actual) if sum(actual) else 0.0,
        "mean_error_hours": sum(errors) / len(errors),
        "p80_coverage": sum(
            actual_value <= bound for actual_value, bound in zip(actual, p80)
        )
        / len(actual),
        "p90_coverage": sum(
            actual_value <= bound for actual_value, bound in zip(actual, p90)
        )
        / len(actual),
    }


def write_markdown_report(
    path: Path,
    snapshot_path: Path,
    snapshot_rows: int,
    completed_rows: list[dict[str, Any]],
    metrics: dict[str, float],
) -> None:
    """Write a portable summary of the validation run."""
    path.parent.mkdir(parents=True, exist_ok=True)
    completed_with_no_time = sum(
        int(row["actual_time_record_count"]) == 0 for row in completed_rows
    )
    lines = [
        "# Effort Prediction Validation Report",
        "",
        f"- Generated at: `{datetime.now().astimezone().isoformat()}`",
        f"- Prediction snapshot: `{snapshot_path}`",
        f"- Snapshot Person x DID rows: **{snapshot_rows:,}**",
        f"- Now completed and compared: **{len(completed_rows):,}**",
        f"- Not yet completed or no longer matchable: **{snapshot_rows - len(completed_rows):,}**",
        f"- Completed rows with no TIME_ON record: **{completed_with_no_time:,}**",
        "",
        "## Prediction vs Actual",
        "",
        f"- MAE: **{metrics['mae_hours']:.1f} hours**",
        f"- Median absolute error: **{metrics['median_absolute_error_hours']:.1f} hours**",
        f"- WAPE: **{metrics['wape']:.1%}**",
        f"- Mean error (Actual - P50): **{metrics['mean_error_hours']:.1f} hours**",
        f"- P80 coverage: **{metrics['p80_coverage']:.1%}**",
        f"- P90 coverage: **{metrics['p90_coverage']:.1%}**",
        "",
        "A positive mean error means the model tended to underestimate actual effort.",
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def validate_prediction_snapshot(
    snapshot_path: Path, comparison_path: Path, report_path: Path
) -> dict[str, Any]:
    """Create completed-DID comparisons and a Markdown validation report."""
    snapshot_rows = read_prediction_snapshot(snapshot_path)
    actuals = load_completed_actuals(snapshot_rows)
    completed_rows = []
    for snapshot in snapshot_rows:
        actual = actuals.get((snapshot["person"], snapshot["did"]))
        if actual is None:
            continue
        row = dict(snapshot)
        actual_hours = _number(actual["actual_hours"], "actual_hours")
        p50_hours = _number(snapshot["p50_hours"], "p50_hours")
        row.update(
            {
                "completed_date": actual.get("completed_date"),
                "actual_hours": round(actual_hours, 1),
                "actual_time_record_count": actual["actual_time_record_count"],
                "error_hours": round(actual_hours - p50_hours, 1),
                "absolute_error_hours": round(abs(actual_hours - p50_hours), 1),
                "p80_covered": actual_hours <= _number(snapshot["p80_hours"], "p80_hours"),
                "p90_covered": actual_hours <= _number(snapshot["p90_hours"], "p90_hours"),
            }
        )
        completed_rows.append(row)
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(snapshot_rows[0]) + [
        "completed_date",
        "actual_hours",
        "actual_time_record_count",
        "error_hours",
        "absolute_error_hours",
        "p80_covered",
        "p90_covered",
    ]
    with comparison_path.open("w", encoding="utf-8-sig", newline="") as comparison_file:
        writer = csv.DictWriter(comparison_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(completed_rows)
    metrics = comparison_metrics(completed_rows)
    write_markdown_report(
        report_path, snapshot_path, len(snapshot_rows), completed_rows, metrics
    )
    return {
        "snapshot_rows": len(snapshot_rows),
        "completed_rows": len(completed_rows),
        "comparison_output": str(comparison_path.resolve()),
        "report_output": str(report_path.resolve()),
        "metrics": metrics,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="Prediction snapshot CSV.")
    parser.add_argument(
        "--output", type=Path, required=True, help="Completed prediction comparison CSV."
    )
    parser.add_argument("--report", type=Path, required=True, help="Markdown report.")
    args = parser.parse_args()
    result = validate_prediction_snapshot(args.input, args.output, args.report)
    print(
        "Validated {completed_rows:,} of {snapshot_rows:,} snapshot rows.\n"
        "Comparison CSV: {comparison_output}\n"
        "Markdown report: {report_output}".format(**result)
    )


if __name__ == "__main__":
    main()
