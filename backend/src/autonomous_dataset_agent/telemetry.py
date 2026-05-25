from __future__ import annotations

from collections import Counter
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .contracts import (
    EvaluationReport,
    LabelRecord,
    ObservabilityConfig,
    SampleRecord,
)
from .governance import stable_checksum
from .utils import write_json


SEVERITY_TAXONOMY = ("debug", "info", "warning", "error", "critical")

TELEMETRY_CONTRACT: dict[str, object] = {
    "schema_version": 1,
    "primary_correlation_key": "job_id",
    "required_correlation_fields": ["job_id", "stage", "run_id", "trace_id", "span_id"],
    "metric_families": {
        "stage": [
            "stage_latency_ms",
            "stage_throughput_items_total",
            "stage_failures_total",
            "stage_retries_total",
            "stage_queue_depth",
        ],
        "class_quality": [
            "class_acceptance_rate",
            "class_ap_drift",
            "label_confidence_bucket_total",
        ],
        "cost": [
            "run_cost_units_total",
            "stage_cost_units_total",
            "budget_spend_ratio",
        ],
    },
    "structured_log_envelope": {
        "schema_version": "int",
        "timestamp": "iso8601-or-deterministic-sequence",
        "severity": list(SEVERITY_TAXONOMY),
        "service": "string",
        "job_id": "string",
        "run_id": "string",
        "stage": "string",
        "trace_id": "string",
        "span_id": "string",
        "event_name": "string",
        "message": "string",
        "attributes": "object",
    },
    "alert_policies": [
        "stuck_run",
        "repeated_stage_failures",
        "class_regression_drift_anomaly",
        "budget_anomaly",
    ],
}


def validate_telemetry_envelope(envelope: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required = [
        "schema_version",
        "timestamp",
        "severity",
        "service",
        "job_id",
        "run_id",
        "stage",
        "trace_id",
        "span_id",
        "event_name",
        "message",
        "attributes",
    ]
    for field_name in required:
        if field_name not in envelope:
            errors.append(f"missing:{field_name}")
    if envelope.get("severity") not in SEVERITY_TAXONOMY:
        errors.append("invalid:severity")
    if not envelope.get("job_id"):
        errors.append("invalid:job_id")
    if not isinstance(envelope.get("attributes", {}), dict):
        errors.append("invalid:attributes")
    return errors


def build_observability_artifacts(
    *,
    job_id: str,
    reports_dir: Path,
    stage_telemetry: list[dict[str, object]],
    accepted_samples: list[SampleRecord],
    label_records: list[LabelRecord],
    evaluation_report: EvaluationReport,
    class_quality_report: dict[str, object],
    iteration_comparison: dict[str, object],
    budgets: dict[str, int],
    label_calls_used: int,
    queue_depth: int = 0,
    config: ObservabilityConfig | None = None,
) -> dict[str, object]:
    resolved_config = config or ObservabilityConfig()
    traces = _build_otel_trace_hooks(job_id, stage_telemetry, resolved_config)
    metrics = _build_metric_records(
        job_id=job_id,
        stage_telemetry=stage_telemetry,
        accepted_samples=accepted_samples,
        label_records=label_records,
        evaluation_report=evaluation_report,
        class_quality_report=class_quality_report,
        iteration_comparison=iteration_comparison,
        budgets=budgets,
        label_calls_used=label_calls_used,
        queue_depth=queue_depth,
    )
    logs = _build_log_envelopes(job_id, stage_telemetry, traces, resolved_config)
    alerts = build_alert_policy_definitions(resolved_config)
    alert_evaluation = evaluate_alerts(
        metrics=metrics,
        stage_telemetry=stage_telemetry,
        config=resolved_config,
    )
    dashboard = build_grafana_dashboard_definition(resolved_config)

    prometheus_text = render_prometheus_metrics(metrics, resolved_config.prometheus_namespace)

    paths = {
        "telemetry_contract": str(reports_dir / "telemetry_contract.json"),
        "otel_traces": str(reports_dir / "otel_traces.json"),
        "prometheus_metrics": str(reports_dir / "prometheus_metrics.prom"),
        "loki_log_envelopes": str(reports_dir / "loki_log_envelopes.json"),
        "grafana_dashboard": str(reports_dir / "grafana_dashboard.json"),
        "alert_policies": str(reports_dir / "alert_policies.json"),
        "alert_evaluation": str(reports_dir / "alert_evaluation.json"),
    }

    write_json(Path(paths["telemetry_contract"]), TELEMETRY_CONTRACT)
    write_json(Path(paths["otel_traces"]), traces)
    Path(paths["prometheus_metrics"]).write_text(prometheus_text, encoding="utf-8")
    write_json(Path(paths["loki_log_envelopes"]), {"schema_version": 1, "job_id": job_id, "entries": logs})
    write_json(Path(paths["grafana_dashboard"]), dashboard)
    write_json(Path(paths["alert_policies"]), alerts)
    write_json(Path(paths["alert_evaluation"]), alert_evaluation)

    return {
        "schema_version": 1,
        "enabled": resolved_config.enabled,
        "job_id": job_id,
        "service": resolved_config.service_name,
        "correlation_key": "job_id",
        "otel": {
            "trace_count": len(traces["spans"]),
            "exporter_endpoint_configured": bool(resolved_config.otel_exporter_endpoint),
            "sink_status": "not_configured" if not resolved_config.otel_exporter_endpoint else "configured",
        },
        "prometheus": {
            "metric_count": len(metrics),
            "scrape_artifact": paths["prometheus_metrics"],
        },
        "loki": {
            "log_count": len(logs),
            "log_artifact": paths["loki_log_envelopes"],
        },
        "grafana": {
            "dashboard_artifact": paths["grafana_dashboard"],
            "alert_policy_artifact": paths["alert_policies"],
        },
        "alerts": alert_evaluation["summary"],
        "artifact_paths": paths,
    }


def build_alert_policy_definitions(config: ObservabilityConfig) -> dict[str, object]:
    return {
        "schema_version": 1,
        "policies": [
            {
                "name": "stuck_run",
                "severity": "critical",
                "condition": f"running stage age exceeds {config.stuck_run_seconds}s",
                "promql": f"max_over_time(ada_stage_running_seconds[5m]) > {config.stuck_run_seconds}",
                "escalation": "operator_page",
            },
            {
                "name": "repeated_stage_failures",
                "severity": "error",
                "condition": f"stage failures >= {config.repeated_stage_failure_threshold}",
                "promql": f"increase(ada_stage_failures_total[15m]) >= {config.repeated_stage_failure_threshold}",
                "escalation": "operator_page",
            },
            {
                "name": "class_regression_drift_anomaly",
                "severity": "warning",
                "condition": f"class AP drift <= -{config.class_regression_ap_delta}",
                "promql": f"ada_class_ap_drift <= -{config.class_regression_ap_delta}",
                "escalation": "reviewer_queue",
            },
            {
                "name": "budget_anomaly",
                "severity": "warning",
                "condition": f"budget spend ratio >= {config.budget_spend_ratio}",
                "promql": f"ada_budget_spend_ratio >= {config.budget_spend_ratio}",
                "escalation": "admin_review",
            },
        ],
    }


def evaluate_alerts(
    *,
    metrics: list[dict[str, object]],
    stage_telemetry: list[dict[str, object]],
    config: ObservabilityConfig,
) -> dict[str, object]:
    triggered: list[dict[str, object]] = []
    failure_count = sum(1 for item in stage_telemetry if item.get("status") == "failed")
    if failure_count >= config.repeated_stage_failure_threshold:
        triggered.append({"name": "repeated_stage_failures", "severity": "error", "value": failure_count})

    for item in stage_telemetry:
        if item.get("status") == "running" and float(item.get("duration_ms", 0)) / 1000 > config.stuck_run_seconds:
            triggered.append({"name": "stuck_run", "severity": "critical", "stage": item.get("stage")})

    for metric in metrics:
        if metric["name"] == "class_ap_drift" and float(metric["value"]) <= -config.class_regression_ap_delta:
            triggered.append(
                {
                    "name": "class_regression_drift_anomaly",
                    "severity": "warning",
                    "class_name": metric["labels"].get("class_name"),
                    "value": metric["value"],
                }
            )
        if metric["name"] == "budget_spend_ratio" and float(metric["value"]) >= config.budget_spend_ratio:
            triggered.append({"name": "budget_anomaly", "severity": "warning", "value": metric["value"]})

    return {
        "schema_version": 1,
        "status": "triggered" if triggered else "clear",
        "triggered": triggered,
        "summary": {
            "status": "triggered" if triggered else "clear",
            "triggered_count": len(triggered),
            "critical_count": sum(1 for item in triggered if item["severity"] == "critical"),
            "warning_count": sum(1 for item in triggered if item["severity"] == "warning"),
            "error_count": sum(1 for item in triggered if item["severity"] == "error"),
        },
    }


def render_prometheus_metrics(metrics: list[dict[str, object]], namespace: str = "ada") -> str:
    lines = [
        "# HELP ada_run_telemetry Deterministic run, stage, class, and cost telemetry.",
        "# TYPE ada_run_telemetry gauge",
    ]
    for metric in sorted(metrics, key=lambda item: (str(item["name"]), str(item.get("labels", {})))):
        labels = metric.get("labels", {})
        label_text = ",".join(
            f'{key}="{_escape_prometheus_label(str(value))}"'
            for key, value in sorted(labels.items())
        )
        metric_name = f"{namespace}_{metric['name']}"
        lines.append(f"{metric_name}{{{label_text}}} {metric['value']}")
    return "\n".join(lines) + "\n"


def build_grafana_dashboard_definition(config: ObservabilityConfig) -> dict[str, object]:
    return {
        "schema_version": 1,
        "title": "Autonomous Dataset Agent - Operations",
        "tags": ["autonomous-dataset-agent", "self-hosted"],
        "timezone": "utc",
        "panels": [
            {"title": "Stage latency by job_id", "type": "timeseries", "query": "ada_stage_latency_ms"},
            {"title": "Queue depth", "type": "stat", "query": "ada_stage_queue_depth"},
            {"title": "Stage failures and retries", "type": "timeseries", "query": "ada_stage_failures_total"},
            {"title": "Class AP drift", "type": "barchart", "query": "ada_class_ap_drift"},
            {"title": "Label confidence distribution", "type": "heatmap", "query": "ada_label_confidence_bucket_total"},
            {"title": "Run and stage cost signals", "type": "stat", "query": "ada_run_cost_units_total"},
        ],
        "alert_policy_source": "alert_policies.json",
        "log_source": "loki_log_envelopes.json",
        "service": config.service_name,
    }


def _build_metric_records(
    *,
    job_id: str,
    stage_telemetry: list[dict[str, object]],
    accepted_samples: list[SampleRecord],
    label_records: list[LabelRecord],
    evaluation_report: EvaluationReport,
    class_quality_report: dict[str, object],
    iteration_comparison: dict[str, object],
    budgets: dict[str, int],
    label_calls_used: int,
    queue_depth: int,
) -> list[dict[str, object]]:
    metrics: list[dict[str, object]] = []
    for stage in stage_telemetry:
        stage_name = str(stage.get("stage", "unknown"))
        status = str(stage.get("status", "unknown"))
        labels = {"job_id": job_id, "stage": stage_name, "status": status}
        metrics.append({"name": "stage_latency_ms", "value": int(stage.get("duration_ms", 0)), "labels": labels})
        metrics.append({"name": "stage_throughput_items_total", "value": _stage_throughput(stage_name, accepted_samples, label_records), "labels": labels})
        metrics.append({"name": "stage_failures_total", "value": 1 if status == "failed" else 0, "labels": labels})
        metrics.append({"name": "stage_retries_total", "value": max(0, int(stage.get("attempt", 1)) - 1), "labels": labels})
        metrics.append({"name": "stage_queue_depth", "value": queue_depth, "labels": labels})
        metrics.append({"name": "stage_cost_units_total", "value": _stage_cost(stage_name, label_calls_used), "labels": labels})

    accepted_by_class = Counter(class_name for sample in accepted_samples for class_name in sample.class_names)
    before_distribution = class_quality_report.get("before_distribution", {})
    for class_name in sorted(set(accepted_by_class) | set(evaluation_report.per_class_metrics)):
        before_count = 0
        if isinstance(before_distribution, dict):
            before_count = int(before_distribution.get(class_name, 0) or 0)
        accepted_count = int(accepted_by_class.get(class_name, 0))
        denominator = before_count or accepted_count or 1
        labels = {"job_id": job_id, "class_name": class_name}
        metrics.append({"name": "class_acceptance_rate", "value": round(accepted_count / denominator, 6), "labels": labels})
        metrics.append({"name": "class_ap_drift", "value": _class_ap_drift(class_name, iteration_comparison, evaluation_report), "labels": labels})

    confidence_buckets = _confidence_buckets(label_records)
    for class_name, buckets in sorted(confidence_buckets.items()):
        for bucket, count in sorted(buckets.items()):
            metrics.append(
                {
                    "name": "label_confidence_bucket_total",
                    "value": count,
                    "labels": {"job_id": job_id, "class_name": class_name, "bucket": bucket},
                }
            )

    max_label_calls = max(1, int(budgets.get("max_label_calls", 1)))
    metrics.append({"name": "run_cost_units_total", "value": label_calls_used, "labels": {"job_id": job_id}})
    metrics.append({"name": "budget_spend_ratio", "value": round(label_calls_used / max_label_calls, 6), "labels": {"job_id": job_id, "budget": "label_calls"}})
    return metrics


def _build_otel_trace_hooks(
    job_id: str,
    stage_telemetry: list[dict[str, object]],
    config: ObservabilityConfig,
) -> dict[str, object]:
    trace_id = stable_checksum({"job_id": job_id, "service": config.service_name})[:32]
    spans = []
    for index, stage in enumerate(stage_telemetry, start=1):
        span = {
            "trace_id": trace_id,
            "span_id": stable_checksum({"job_id": job_id, "stage": stage.get("stage"), "attempt": stage.get("attempt", 1)})[:16],
            "parent_span_id": None,
            "name": f"pipeline.{stage.get('stage')}",
            "kind": "internal",
            "status": stage.get("status"),
            "attributes": {
                "job_id": job_id,
                "stage": stage.get("stage"),
                "attempt": stage.get("attempt", 1),
                "duration_ms": stage.get("duration_ms", 0),
                "sequence": index,
            },
        }
        spans.append(span)
    return {
        "schema_version": 1,
        "service": config.service_name,
        "job_id": job_id,
        "trace_id": trace_id,
        "exporter_endpoint": config.otel_exporter_endpoint,
        "spans": spans,
    }


def _build_log_envelopes(
    job_id: str,
    stage_telemetry: list[dict[str, object]],
    traces: dict[str, object],
    config: ObservabilityConfig,
) -> list[dict[str, object]]:
    spans = traces.get("spans", [])
    span_by_stage = {
        str(span["attributes"]["stage"]): span
        for span in spans
        if isinstance(span, dict) and isinstance(span.get("attributes"), dict)
    }
    entries = []
    for sequence, stage in enumerate(stage_telemetry, start=1):
        stage_name = str(stage.get("stage", "unknown"))
        span = span_by_stage.get(stage_name, {})
        status = str(stage.get("status", "unknown"))
        severity = "error" if status == "failed" else "info"
        envelope = {
            "schema_version": config.log_schema_version,
            "timestamp": f"sequence:{sequence:04d}",
            "severity": severity,
            "service": config.service_name,
            "job_id": job_id,
            "run_id": job_id,
            "stage": stage_name,
            "trace_id": traces.get("trace_id", ""),
            "span_id": span.get("span_id", stable_checksum({"job_id": job_id, "stage": stage_name})[:16]),
            "event_name": f"stage.{status}",
            "message": f"Stage {stage_name} {status}.",
            "attributes": {
                "duration_ms": stage.get("duration_ms", 0),
                "attempt": stage.get("attempt", 1),
            },
        }
        errors = validate_telemetry_envelope(envelope)
        if errors:
            envelope["validation_errors"] = errors
        entries.append(envelope)
    return entries


def _stage_throughput(stage_name: str, samples: list[SampleRecord], labels: list[LabelRecord]) -> int:
    if stage_name in {"critic", "frame_extraction"}:
        return len(samples)
    if stage_name == "labeling":
        return len(labels)
    return 1


def _stage_cost(stage_name: str, label_calls_used: int) -> int:
    if stage_name == "labeling":
        return label_calls_used
    if stage_name in {"source_resolution", "frame_extraction", "training", "evaluation"}:
        return 1
    return 0


def _class_ap_drift(
    class_name: str,
    iteration_comparison: dict[str, object],
    evaluation_report: EvaluationReport,
) -> float:
    class_deltas = iteration_comparison.get("class_deltas")
    if isinstance(class_deltas, dict):
        raw = class_deltas.get(class_name, {})
        if isinstance(raw, dict):
            delta = raw.get("delta")
            if isinstance(delta, dict) and delta.get("ap") is not None:
                return round(float(delta["ap"]), 6)
            for key in ("ap_delta", "delta_ap"):
                if raw.get(key) is not None:
                    return round(float(raw[key]), 6)
    return round(float(evaluation_report.per_class_metrics.get(class_name, {}).get("ap", 0.0)), 6)


def _confidence_buckets(label_records: list[LabelRecord]) -> dict[str, dict[str, int]]:
    buckets: dict[str, dict[str, int]] = {}
    for record in label_records:
        for box in record.boxes:
            class_buckets = buckets.setdefault(box.class_name, {"0.00-0.50": 0, "0.50-0.75": 0, "0.75-0.90": 0, "0.90-1.00": 0})
            confidence = box.confidence
            if confidence < 0.5:
                class_buckets["0.00-0.50"] += 1
            elif confidence < 0.75:
                class_buckets["0.50-0.75"] += 1
            elif confidence < 0.9:
                class_buckets["0.75-0.90"] += 1
            else:
                class_buckets["0.90-1.00"] += 1
    return buckets


def _escape_prometheus_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def observability_config_to_dict(config: ObservabilityConfig) -> dict[str, object]:
    return asdict(config)
