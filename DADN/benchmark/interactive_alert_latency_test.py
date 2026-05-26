#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any


DADN_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = DADN_DIR / "experiments" / "results"


def fmean_or_none(values: list[float]) -> float | None:
    return statistics.fmean(values) if values else None


def p95_or_none(values: list[float]) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    return statistics.quantiles(values, n=20, method="inclusive")[18]


def fetch_json(url: str, timeout: float) -> dict[str, Any]:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.load(response)


def poll_stats(stats_url: str, timeout: float) -> dict[str, Any]:
    sample = fetch_json(stats_url, timeout)
    sample["_client_timestamp"] = time.time()
    return sample


def fmt_ms(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.1f} ms"


def fmt_num(value: float | None, digits: int = 2) -> str:
    return "N/A" if value is None else f"{value:.{digits}f}"


def bell(enabled: bool) -> None:
    if enabled:
        print("\a", end="", flush=True)


def alert_key(alert: dict[str, Any]) -> str:
    timestamp = alert.get("timestamp")
    if timestamp is not None:
        return str(timestamp)
    return json.dumps(alert, sort_keys=True, ensure_ascii=False)


def build_events(run_started_at: float, args: argparse.Namespace) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    offset = args.first_event_at
    while offset < args.duration:
        start = run_started_at + offset
        events.append(
            {
                "event_index": len(events) + 1,
                "planned_offset_seconds": round(offset, 3),
                "start_client_timestamp": start,
                "end_client_timestamp": start + args.hold,
                "matched_alerts": [],
            }
        )
        offset += args.event_interval
    return events


def match_alert_to_event(
    alert_timestamp: float,
    events: list[dict[str, Any]],
    match_window: float,
) -> dict[str, Any] | None:
    for event in events:
        start = float(event["start_client_timestamp"])
        if start <= alert_timestamp <= start + match_window:
            return event
    return None


def collect_alert(
    sample: dict[str, Any],
    *,
    seen_alerts: set[str],
    run_started_at: float,
    events: list[dict[str, Any]],
    match_window: float,
) -> dict[str, Any] | None:
    alert = sample.get("last_alert")
    if not alert:
        return None

    key = alert_key(alert)
    if key in seen_alerts:
        return None
    seen_alerts.add(key)

    alert_timestamp = float(alert.get("timestamp") or sample["_client_timestamp"])
    if alert_timestamp < run_started_at:
        return None

    latency = alert.get("latency_ms", sample.get("last_alert_latency_ms"))
    normalized = {
        "key": key,
        "client_seen_at": sample["_client_timestamp"],
        "server_alert_timestamp": alert_timestamp,
        "server_side_latency_ms": float(latency) if latency is not None else None,
        "label": alert.get("label"),
        "raw_label": alert.get("raw_label"),
        "distance": alert.get("distance"),
        "zone": alert.get("zone"),
        "spoken_text": alert.get("spoken_text"),
    }

    event = match_alert_to_event(alert_timestamp, events, match_window)
    if event is not None:
        normalized["matched_event_index"] = event["event_index"]
        normalized["scheduled_trigger_to_alert_ms"] = (
            alert_timestamp - float(event["start_client_timestamp"])
        ) * 1000
        normalized["scheduled_trigger_to_client_seen_ms"] = (
            sample["_client_timestamp"] - float(event["start_client_timestamp"])
        ) * 1000
        event["matched_alerts"].append(normalized)
    else:
        normalized["matched_event_index"] = None
        normalized["scheduled_trigger_to_alert_ms"] = None
        normalized["scheduled_trigger_to_client_seen_ms"] = None

    return normalized


def print_countdown(label: str, seconds: float) -> None:
    print(f"{label} in {max(0, int(round(seconds)))}s", flush=True)


def run_one(args: argparse.Namespace, run_index: int, stats_url: str) -> dict[str, Any]:
    print(f"\n=== Run {run_index}/{args.runs}: warmup {args.warmup:.0f}s ===")
    warmup_end = time.time() + args.warmup
    last_warmup_tick: int | None = None
    while time.time() < warmup_end:
        remaining = warmup_end - time.time()
        tick = int(remaining)
        if tick != last_warmup_tick and tick <= 5:
            print_countdown("Measurement starts", remaining)
            last_warmup_tick = tick
        try:
            poll_stats(stats_url, args.timeout)
        except Exception:
            pass
        time.sleep(min(args.poll_interval, 0.5))

    run_started_at = time.time()
    events = build_events(run_started_at, args)
    run_end = run_started_at + args.duration
    samples: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    seen_alerts: set[str] = set(args.initial_seen_alerts)
    active_event_index: int | None = None
    announced_countdown: tuple[int, int] | None = None

    print(
        f"=== Run {run_index}/{args.runs}: measurement {args.duration:.0f}s, "
        f"{len(events)} planned events ==="
    )

    while time.time() < run_end:
        now = time.time()
        next_event = next(
            (
                event
                for event in events
                if now < float(event["start_client_timestamp"])
            ),
            None,
        )
        current_event = next(
            (
                event
                for event in events
                if float(event["start_client_timestamp"])
                <= now
                < float(event["end_client_timestamp"])
            ),
            None,
        )

        if current_event is not None:
            idx = int(current_event["event_index"])
            if active_event_index != idx:
                active_event_index = idx
                bell(not args.no_beep)
                print(
                    f"[RUN {run_index} EVENT {idx}/{len(events)}] "
                    "PUT OBJECT IN center-lower view, hold ~2s",
                    flush=True,
                )
        elif active_event_index is not None:
            bell(not args.no_beep)
            print(
                f"[RUN {run_index} EVENT {active_event_index}] "
                "REMOVE OBJECT, keep scene empty",
                flush=True,
            )
            active_event_index = None

        if next_event is not None and current_event is None:
            remaining = float(next_event["start_client_timestamp"]) - now
            tick = int(round(remaining))
            countdown_key = (int(next_event["event_index"]), tick)
            if 0 < tick <= 3 and countdown_key != announced_countdown:
                print_countdown(
                    f"Next event {next_event['event_index']}/{len(events)}",
                    remaining,
                )
                announced_countdown = countdown_key

        try:
            sample = poll_stats(stats_url, args.timeout)
            samples.append(sample)
            alert = collect_alert(
                sample,
                seen_alerts=seen_alerts,
                run_started_at=run_started_at,
                events=events,
                match_window=args.match_window,
            )
            if alert is not None:
                alerts.append(alert)
                matched = alert.get("matched_event_index")
                matched_text = f"event {matched}" if matched else "unmatched"
                print(
                    "[ALERT] "
                    f"{alert.get('label')} {alert.get('distance')} "
                    f"{alert.get('zone')} | {fmt_ms(alert.get('server_side_latency_ms'))} "
                    f"| {matched_text}",
                    flush=True,
                )
        except Exception as exc:
            samples.append({"_client_timestamp": time.time(), "_error": str(exc)})

        time.sleep(args.poll_interval)

    if active_event_index is not None:
        print(f"[RUN {run_index} EVENT {active_event_index}] REMOVE OBJECT")

    capture_fps = [
        float(item.get("current_fps") or 0.0)
        for item in samples
        if "_error" not in item
    ]
    inference_fps = [
        float(item.get("inference_fps") or 0.0)
        for item in samples
        if "_error" not in item
    ]
    alert_latencies = [
        float(item["server_side_latency_ms"])
        for item in alerts
        if item.get("server_side_latency_ms") is not None
    ]
    matched_events = [
        event for event in events if event.get("matched_alerts")
    ]

    return {
        "run": run_index,
        "started_at": run_started_at,
        "duration_seconds": args.duration,
        "events": events,
        "samples": samples,
        "alerts": alerts,
        "summary": {
            "planned_events": len(events),
            "matched_events": len(matched_events),
            "missed_events": len(events) - len(matched_events),
            "unmatched_alerts": len([a for a in alerts if a.get("matched_event_index") is None]),
            "alert_events": len(alerts),
            "event_detection_rate": (
                len(matched_events) / len(events) if events else None
            ),
            "avg_capture_fps": fmean_or_none(capture_fps),
            "avg_inference_fps": fmean_or_none(inference_fps),
            "server_side_alert_latency_ms_mean": fmean_or_none(alert_latencies),
            "server_side_alert_latency_ms_p95": p95_or_none(alert_latencies),
        },
    }


def run_manual(args: argparse.Namespace, stats_url: str) -> dict[str, Any]:
    print(f"\n=== Manual trigger mode: {args.events} events ===")
    print("Move the object into view, then press Enter at that exact moment.")
    print("Keep the object visible until the script prints DETECTED or TIMEOUT.")

    samples: list[dict[str, Any]] = []
    alerts: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    seen_alerts: set[str] = set(args.initial_seen_alerts)
    started_at = time.time()

    if args.warmup > 0:
        print(f"\nWarmup {args.warmup:.0f}s: keep scene empty.")
        deadline = time.time() + args.warmup
        while time.time() < deadline:
            try:
                samples.append(poll_stats(stats_url, args.timeout))
            except Exception as exc:
                samples.append({"_client_timestamp": time.time(), "_error": str(exc)})
            time.sleep(min(args.poll_interval, 0.5))

    for event_index in range(1, args.events + 1):
        input(f"\n[EVENT {event_index}/{args.events}] Put object in view, then press Enter...")
        trigger_at = time.time()
        bell(not args.no_beep)

        event = {
            "event_index": event_index,
            "mode": "manual_enter",
            "planned_offset_seconds": None,
            "start_client_timestamp": trigger_at,
            "end_client_timestamp": trigger_at + args.hold,
            "matched_alerts": [],
        }
        events.append(event)

        detected_alert: dict[str, Any] | None = None
        wait_until = trigger_at + args.manual_timeout
        while time.time() < wait_until:
            try:
                sample = poll_stats(stats_url, args.timeout)
                samples.append(sample)
                alert = collect_alert(
                    sample,
                    seen_alerts=seen_alerts,
                    run_started_at=trigger_at,
                    events=[event],
                    match_window=args.manual_timeout,
                )
                if alert is not None:
                    alerts.append(alert)
                    detected_alert = alert
                    break
            except Exception as exc:
                samples.append({"_client_timestamp": time.time(), "_error": str(exc)})
            time.sleep(args.poll_interval)

        if detected_alert is not None:
            print(
                "[DETECTED] "
                f"{detected_alert.get('label')} {detected_alert.get('distance')} "
                f"{detected_alert.get('zone')} | "
                f"trigger->alert {fmt_ms(detected_alert.get('scheduled_trigger_to_alert_ms'))} | "
                f"trigger->client-seen {fmt_ms(detected_alert.get('scheduled_trigger_to_client_seen_ms'))} | "
                f"server-side {fmt_ms(detected_alert.get('server_side_latency_ms'))}",
                flush=True,
            )
        else:
            print("[TIMEOUT] No new alert matched this trigger.", flush=True)

        input("Remove object, keep scene empty, then press Enter for the next event...")

        reset_until = time.time() + args.reset_seconds
        while time.time() < reset_until:
            try:
                samples.append(poll_stats(stats_url, args.timeout))
            except Exception as exc:
                samples.append({"_client_timestamp": time.time(), "_error": str(exc)})
            time.sleep(min(args.poll_interval, 0.5))

    capture_fps = [
        float(item.get("current_fps") or 0.0)
        for item in samples
        if "_error" not in item
    ]
    inference_fps = [
        float(item.get("inference_fps") or 0.0)
        for item in samples
        if "_error" not in item
    ]
    alert_latencies = [
        float(item["server_side_latency_ms"])
        for item in alerts
        if item.get("server_side_latency_ms") is not None
    ]
    trigger_to_alert = [
        float(item["scheduled_trigger_to_alert_ms"])
        for item in alerts
        if item.get("scheduled_trigger_to_alert_ms") is not None
    ]
    trigger_to_seen = [
        float(item["scheduled_trigger_to_client_seen_ms"])
        for item in alerts
        if item.get("scheduled_trigger_to_client_seen_ms") is not None
    ]
    matched_events = [event for event in events if event.get("matched_alerts")]

    return {
        "run": "manual",
        "started_at": started_at,
        "duration_seconds": time.time() - started_at,
        "events": events,
        "samples": samples,
        "alerts": alerts,
        "summary": {
            "planned_events": len(events),
            "matched_events": len(matched_events),
            "missed_events": len(events) - len(matched_events),
            "unmatched_alerts": len([a for a in alerts if a.get("matched_event_index") is None]),
            "alert_events": len(alerts),
            "event_detection_rate": (
                len(matched_events) / len(events) if events else None
            ),
            "avg_capture_fps": fmean_or_none(capture_fps),
            "avg_inference_fps": fmean_or_none(inference_fps),
            "server_side_alert_latency_ms_mean": fmean_or_none(alert_latencies),
            "server_side_alert_latency_ms_p95": p95_or_none(alert_latencies),
            "manual_trigger_to_server_alert_ms_mean": fmean_or_none(trigger_to_alert),
            "manual_trigger_to_server_alert_ms_p95": p95_or_none(trigger_to_alert),
            "manual_trigger_to_client_seen_ms_mean": fmean_or_none(trigger_to_seen),
            "manual_trigger_to_client_seen_ms_p95": p95_or_none(trigger_to_seen),
        },
    }


def write_markdown(summary: dict[str, Any], path: Path) -> None:
    aggregate = summary["aggregate"]
    lines = [
        "# Interactive Alert Latency Test",
        "",
        "This run guides the operator with timed prompts and records alerts from",
        "`/api/stats`. Latency values are server-side alert latency, not full",
        "camera-to-audio end-to-end latency.",
        "",
        "## Protocol",
        "",
        f"- Server URL: `{summary['server_url']}`",
        f"- Mode: `{summary['protocol']['mode']}`",
        f"- Runs: `{summary['protocol']['runs']}`",
        f"- Warmup: `{summary['protocol']['warmup_seconds']}s`",
        f"- Measured duration/run: `{summary['protocol']['duration_seconds']}s`",
        f"- First event at: `{summary['protocol']['first_event_at_seconds']}s`",
        f"- Event interval: `{summary['protocol']['event_interval_seconds']}s`",
        f"- Hold duration: `{summary['protocol']['hold_seconds']}s`",
        f"- Match window: `{summary['protocol']['match_window_seconds']}s`",
        f"- Manual events: `{summary['protocol']['manual_events']}`",
        f"- Manual timeout: `{summary['protocol']['manual_timeout_seconds']}s`",
        "",
        "## Aggregate Summary",
        "",
        "| Metric | Value |",
        "| --- | ---: |",
        f"| Planned events | `{aggregate['planned_events']}` |",
        f"| Matched events | `{aggregate['matched_events']}` |",
        f"| Missed events | `{aggregate['missed_events']}` |",
        f"| Alert events | `{aggregate['alert_events']}` |",
        f"| Event detection rate | `{fmt_num(aggregate['event_detection_rate'], 3)}` |",
        f"| Avg capture FPS | `{fmt_num(aggregate['avg_capture_fps_mean'])}` |",
        f"| Avg inference FPS | `{fmt_num(aggregate['avg_inference_fps_mean'])}` |",
        f"| Server-side alert latency mean | `{fmt_ms(aggregate['server_side_alert_latency_ms_mean'])}` |",
        f"| Server-side alert latency p95 | `{fmt_ms(aggregate['server_side_alert_latency_ms_p95'])}` |",
        f"| Manual trigger to server alert mean | `{fmt_ms(aggregate['manual_trigger_to_server_alert_ms_mean'])}` |",
        f"| Manual trigger to server alert p95 | `{fmt_ms(aggregate['manual_trigger_to_server_alert_ms_p95'])}` |",
        f"| Manual trigger to client-seen alert mean | `{fmt_ms(aggregate['manual_trigger_to_client_seen_ms_mean'])}` |",
        f"| Manual trigger to client-seen alert p95 | `{fmt_ms(aggregate['manual_trigger_to_client_seen_ms_p95'])}` |",
        "",
        "## Per-run Summary",
        "",
        "| Run | Planned | Matched | Missed | Alerts | Capture FPS | Inference FPS | Server latency mean | Trigger-to-alert mean |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for run in summary["runs"]:
        item = run["summary"]
        lines.append(
            "| {run} | `{planned}` | `{matched}` | `{missed}` | `{alerts}` | "
            "`{cap}` | `{inf}` | `{mean}` | `{trigger}` |".format(
                run=run["run"],
                planned=item["planned_events"],
                matched=item["matched_events"],
                missed=item["missed_events"],
                alerts=item["alert_events"],
                cap=fmt_num(item["avg_capture_fps"]),
                inf=fmt_num(item["avg_inference_fps"]),
                mean=fmt_ms(item["server_side_alert_latency_ms_mean"]),
                trigger=fmt_ms(item.get("manual_trigger_to_server_alert_ms_mean")),
            )
        )
    lines.extend(
        [
            "",
            "## Output Files",
            "",
            f"- JSON: `{summary['json_path']}`",
            f"- Markdown: `{summary['markdown_path']}`",
        ]
    )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def aggregate_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    planned = sum(int(run["summary"]["planned_events"]) for run in runs)
    matched = sum(int(run["summary"]["matched_events"]) for run in runs)
    missed = sum(int(run["summary"]["missed_events"]) for run in runs)
    alerts = sum(int(run["summary"]["alert_events"]) for run in runs)
    capture_fps = [
        float(run["summary"]["avg_capture_fps"])
        for run in runs
        if run["summary"].get("avg_capture_fps") is not None
    ]
    inference_fps = [
        float(run["summary"]["avg_inference_fps"])
        for run in runs
        if run["summary"].get("avg_inference_fps") is not None
    ]
    latencies = [
        float(alert["server_side_latency_ms"])
        for run in runs
        for alert in run["alerts"]
        if alert.get("server_side_latency_ms") is not None
    ]
    trigger_to_alert = [
        float(alert["scheduled_trigger_to_alert_ms"])
        for run in runs
        for alert in run["alerts"]
        if alert.get("scheduled_trigger_to_alert_ms") is not None
    ]
    trigger_to_seen = [
        float(alert["scheduled_trigger_to_client_seen_ms"])
        for run in runs
        for alert in run["alerts"]
        if alert.get("scheduled_trigger_to_client_seen_ms") is not None
    ]
    return {
        "planned_events": planned,
        "matched_events": matched,
        "missed_events": missed,
        "alert_events": alerts,
        "event_detection_rate": matched / planned if planned else None,
        "avg_capture_fps_mean": fmean_or_none(capture_fps),
        "avg_inference_fps_mean": fmean_or_none(inference_fps),
        "server_side_alert_latency_ms_mean": fmean_or_none(latencies),
        "server_side_alert_latency_ms_p95": p95_or_none(latencies),
        "manual_trigger_to_server_alert_ms_mean": fmean_or_none(trigger_to_alert),
        "manual_trigger_to_server_alert_ms_p95": p95_or_none(trigger_to_alert),
        "manual_trigger_to_client_seen_ms_mean": fmean_or_none(trigger_to_seen),
        "manual_trigger_to_client_seen_ms_p95": p95_or_none(trigger_to_seen),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Guided live alert benchmark for DADN server-side latency."
    )
    parser.add_argument("--server-url", default="http://127.0.0.1:5000")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--warmup", type=float, default=10.0)
    parser.add_argument("--duration", type=float, default=60.0)
    parser.add_argument("--first-event-at", type=float, default=5.0)
    parser.add_argument("--event-interval", type=float, default=8.0)
    parser.add_argument("--hold", type=float, default=2.0)
    parser.add_argument("--match-window", type=float, default=5.0)
    parser.add_argument("--poll-interval", type=float, default=0.25)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--output-dir", type=Path, default=RESULTS_DIR)
    parser.add_argument("--no-beep", action="store_true")
    parser.add_argument("--manual", action="store_true", help="Press Enter for each obstacle trigger")
    parser.add_argument("--events", type=int, default=21, help="Manual mode event count")
    parser.add_argument("--manual-timeout", type=float, default=8.0, help="Seconds to wait for alert after Enter")
    parser.add_argument("--reset-seconds", type=float, default=2.0, help="Scene-empty delay after each manual event")
    args = parser.parse_args()

    base_url = args.server_url.rstrip("/")
    health_url = base_url + "/health"
    stats_url = base_url + "/api/stats"

    try:
        health = fetch_json(health_url, args.timeout)
        stats = fetch_json(stats_url, args.timeout)
    except Exception as exc:
        raise SystemExit(f"Could not reach DADN server at {base_url}: {exc}") from exc

    initial_seen_alerts: set[str] = set()
    if stats.get("last_alert"):
        initial_seen_alerts.add(alert_key(stats["last_alert"]))
    args.initial_seen_alerts = initial_seen_alerts

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    suffix = "manual-alert-latency" if args.manual else "interactive-alert-latency"
    run_dir = args.output_dir / f"{timestamp}-{suffix}"
    run_dir.mkdir(parents=True, exist_ok=True)

    print("Interactive alert latency test")
    print(f"Server: {base_url}")
    print(f"Health: {health}")
    print("Follow the terminal prompts. Keep scenes empty between events.")

    if args.manual:
        runs = [run_manual(args, stats_url)]
    else:
        runs = [run_one(args, run_idx, stats_url) for run_idx in range(1, args.runs + 1)]

    json_path = run_dir / "interactive_alert_summary.json"
    markdown_path = run_dir / "interactive_alert_summary.md"
    payload = {
        "server_url": base_url,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "health": health,
        "initial_stats": stats,
        "protocol": {
            "mode": "manual_enter" if args.manual else "scheduled_prompt",
            "runs": 1 if args.manual else args.runs,
            "warmup_seconds": args.warmup,
            "duration_seconds": None if args.manual else args.duration,
            "first_event_at_seconds": args.first_event_at,
            "event_interval_seconds": args.event_interval,
            "hold_seconds": args.hold,
            "match_window_seconds": args.match_window,
            "manual_events": args.events if args.manual else None,
            "manual_timeout_seconds": args.manual_timeout if args.manual else None,
            "reset_seconds": args.reset_seconds if args.manual else None,
            "poll_interval_seconds": args.poll_interval,
            "note": (
                "Manual trigger-to-alert approximates object-entry-to-backend-alert "
                "when the operator presses Enter at object entry. It is not full "
                "camera-to-audio latency."
                if args.manual
                else "Server-side alert latency only, not full end-to-end audio latency."
            ),
        },
        "runs": runs,
        "aggregate": aggregate_runs(runs),
        "json_path": str(json_path),
        "markdown_path": str(markdown_path),
    }
    json_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    write_markdown(payload, markdown_path)

    aggregate = payload["aggregate"]
    print("\n=== Aggregate ===")
    print(f"Planned events: {aggregate['planned_events']}")
    print(f"Matched events: {aggregate['matched_events']}")
    print(f"Alert events: {aggregate['alert_events']}")
    print(f"Detection rate: {fmt_num(aggregate['event_detection_rate'], 3)}")
    print(f"Latency mean: {fmt_ms(aggregate['server_side_alert_latency_ms_mean'])}")
    print(f"Latency p95: {fmt_ms(aggregate['server_side_alert_latency_ms_p95'])}")
    print(f"Trigger->alert mean: {fmt_ms(aggregate['manual_trigger_to_server_alert_ms_mean'])}")
    print(f"Trigger->alert p95: {fmt_ms(aggregate['manual_trigger_to_server_alert_ms_p95'])}")
    print(f"[OK] Wrote {json_path}")
    print(f"[OK] Wrote {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
