# Remote Benchmark Report - 2026-05-26

This file records the benchmark results reported from the Raspberry Pi /
ESP32-CAM remote run. It separates measured metrics from metrics that still
need a dedicated test, so the formal report does not over-claim.

## Environment

| Item | Value |
| --- | --- |
| Commit | `7f2824d` on branch `demo` |
| Python | DADN `3.11.15` in venv, ESP32 `3.13.5` via PlatformIO |
| Model family | EfficientDet-Lite0 int8 |
| ESP32 IP | `192.168.1.10` |
| Raspberry Pi IP | `192.168.1.12` |
| Wi-Fi SSID | `Sunny` |
| Serial port | `/dev/ttyUSB0` (CH340) |
| Server | Flask + Waitress at `http://127.0.0.1:5000` |
| ESP32 stream | `http://192.168.1.10:8081/stream` |

## Dataset

| Artifact | Value |
| --- | --- |
| Images | `datasets/dadn_public/subset/images/` |
| Labels | `datasets/dadn_public/subset/labels.json` |
| Image count | `500` |
| Source | COCO `250` + BDD FiftyOne `250` |
| Groups | `person=174`, `vehicle=293`, `static_obstacle=33` |

## Tuning Sweep

Selected config:

```text
sweep_lite0_s040_r10
EfficientDet-Lite0 int8
score_threshold = 0.40
max_results = 10
```

Selection reason:

```text
All eligible configs met risk/alert correctness >= 0.75.
The selected config had the lowest p95 latency among configs within 0.03
balanced_score of the best config.
```

| Metric | Value |
| --- | ---: |
| `risk_alert_correctness` | `0.856` |
| `alert_correctness` | `0.448` |
| `avg_latency_ms` | `198.7 ms` |
| `p95_latency_ms` | `207.2 ms` |
| `balanced_score` | `0.716` |

Full ranking:

| Config | Risk | Alert | Avg ms | P95 ms | Score | Decision |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `sweep_lite0_s025_r25_hard` | `0.878` | `0.420` | `200.4` | `209.4` | `0.735` | Eligible |
| `sweep_lite0_s035_r15` | `0.862` | `0.440` | `199.7` | `208.5` | `0.722` | Eligible |
| `sweep_lite0_s035_r15_pre_smooth` | `0.862` | `0.440` | `200.7` | `210.7` | `0.720` | Eligible |
| `sweep_lite0_s040_r10` | `0.856` | `0.448` | `198.7` | `207.2` | `0.716` | Winner |
| `sweep_lite0_s045_r08` | `0.842` | `0.448` | `197.4` | `205.8` | `0.705` | Eligible |
| `sweep_lite2_s045_r08` | `0.908` | `0.480` | `571.6` | `591.3` | `0.700` | Eligible but slower |
| `sweep_lite0_s050_r05_baseline` | `0.816` | `0.438` | `196.9` | `204.5` | `0.691` | Eligible |
| `sweep_ssd_s045_r05_faster` | `0.756` | `0.406` | `225.2` | `235.1` | `0.631` | Eligible |

Interpretation:

- `risk_alert_correctness` is the primary safety metric for obstacle warning.
- `alert_correctness` is stricter because it also depends on detailed label
  agreement such as group/zone/distance. It should remain a diagnostic metric.
- The aggressive `s025_r25_hard` config has higher risk correctness, but it
  should not be promoted without a negative-scene false-alert test.

## Runtime Baseline

Deployed config: `sweep_lite0_s040_r10` on live ESP32-CAM stream at QVGA.

| Metric | Value |
| --- | ---: |
| `avg_capture_fps_mean` | `31.68 FPS` |
| `avg_capture_fps_std` | `0.68 FPS` |
| `avg_inference_fps_mean` | `4.32 FPS` |
| `avg_inference_fps_std` | `0.16 FPS` |
| `server_side_alert_latency_ms_mean` | `N/A` |
| `server_side_alert_latency_ms_p95` | `N/A` |
| `alert_events` | `0` |

The baseline runtime run did not contain an obstacle that triggered an alert, so
server-side alert latency is intentionally reported as `N/A`.

## ESP32-CAM Resolution Sweep

| Resolution | Size | Flash | Avg capture FPS | Avg inference FPS | Alert latency mean | Alert events | Status |
| --- | --- | --- | ---: | ---: | ---: | ---: | --- |
| QVGA | `320x240` | OK | `31.14` | `4.42` | `N/A` | `0` | ok |
| VGA | `640x480` | OK | `20.85` | `4.07` | `N/A` | `0` | ok |
| SVGA | `800x600` | OK | `13.71` | `2.67` | `215.1 ms` | `1` | ok |
| XGA | `1024x768` | OK | `8.61` | `1.66` | `200.7 ms` | `26` | ok |
| SXGA | `1280x1024` | OK | `2.83` | `0.54` | `N/A` | `0` | ok |
| UXGA | `1600x1200` | OK | `2.04` | `0.39` | `N/A` | `0` | ok |

Notes:

- Stream discovery used serial logs for all resolutions.
- All resolutions flashed successfully after PlatformIO was installed in the
  DADN Python 3.11 environment.
- QVGA and VGA are the practical real-time candidates.
- SXGA and UXGA drop below 5 FPS capture and are unsuitable for real-time
  obstacle warning with the current pipeline.
- SVGA and XGA produced alert events, so only those runs yielded server-side
  alert latency measurements.

## Measured vs Not Measured

| Metric | Status | Note |
| --- | --- | --- |
| `risk_alert_correctness` | Measured | `0.856` from tuning sweep |
| `alert_correctness` | Measured | `0.448` from tuning sweep |
| `avg_latency_ms` | Measured | `198.7 ms` from tuning sweep |
| `p95_latency_ms` | Measured | `207.2 ms` from tuning sweep |
| `balanced_score` | Measured | `0.716` from tuning sweep |
| `avg_capture_fps_mean` | Measured | `31.68 FPS` on runtime baseline QVGA |
| `avg_inference_fps_mean` | Measured | `4.32 FPS` on runtime baseline QVGA |
| `server_side_alert_latency_ms` | Partially measured | `200-215 ms` only in SVGA/XGA resolution runs with alert events |
| `alert_events` | Measured | `0` in baseline, `1-26` in selected resolution runs |
| `false_alert_rate` | Not measured | Requires negative-scene benchmark |
| `TTS latency` | Not measured | Requires a dedicated audio/browser timing test |
| full camera-to-audio end-to-end latency | Not measured | Requires real camera event plus audio timing instrumentation |

## End-to-end Latency Plan

There are three useful latency levels. They should not be mixed in the report.

| Level | Can be mocked? | What it measures |
| --- | --- | --- |
| Offline inference latency | Yes | Model/pipeline time on a stored image or video frame |
| Server-side alert latency | Partially | From backend frame processing to alert creation |
| Full camera-to-audio end-to-end latency | No, not fully | From a real object entering camera view to audible alert |

Mocking is useful for repeatability:

- Replay a fixed video or image sequence into the server to trigger alerts.
- Use it to validate that alert timestamps and server-side latency logging work.
- Use it to compare configs under identical input.

Mocking is not enough for the final end-to-end claim:

- It skips camera exposure, ESP32 JPEG encoding, Wi-Fi transport, browser audio
  policy, and speaker playback.
- The final end-to-end latency should use a real object entering the camera
  frame and a visible/audible timing reference.

Recommended next run:

1. Keep `sweep_lite0_s040_r10`.
2. Use QVGA first, then VGA if more image detail is needed.
3. Place a clear object/person in front of the camera for 20-30 repeated events.
4. Record both the object entering the frame and the audio output in one video.
5. Report full end-to-end latency as an approximate empirical measurement,
   separate from `server_side_alert_latency_ms`.

## Remaining Tests Runbook

Use this section for the next live run. These tests are not included in the
2026-05-26 numbers above unless a new result path is added.

### Server-side alert latency with a real obstacle

This is ready to run with the guided script. Prefer manual mode because the
operator can press Enter exactly when the object enters the camera view. This
produces an approximate object-entry-to-backend-alert latency in addition to the
server-side backend latency.

```bash
python DADN/benchmark/interactive_alert_latency_test.py \
  --server-url http://127.0.0.1:5000 \
  --manual \
  --events 21 \
  --warmup 10 \
  --hold 2 \
  --manual-timeout 8 \
  --reset-seconds 2 \
  --poll-interval 0.25
```

Protocol:

1. Use the selected config `sweep_lite0_s040_r10`.
2. Start with QVGA; repeat with VGA if more image detail is needed.
3. During the `--warmup 10` period, keep the camera scene empty.
4. For each event, move the object/person into the center-lower camera view and
   press Enter at the same moment.
5. Keep the object visible until the script prints `DETECTED` or `TIMEOUT`.
6. Remove the object, press Enter to continue, and keep the scene empty for the
   reset interval.
7. Run 21 events if possible. This is enough to compute mean/p95 without making
   the demo too long.
8. If `alert_events` is still `0`, report latency as `N/A`; do not invent a
   value.

Report fields:

- `avg_capture_fps_mean`
- `avg_inference_fps_mean`
- `server_side_alert_latency_ms_mean`
- `server_side_alert_latency_ms_p95`
- `manual_trigger_to_server_alert_ms_mean`
- `manual_trigger_to_server_alert_ms_p95`
- `manual_trigger_to_client_seen_ms_mean`
- `manual_trigger_to_client_seen_ms_p95`
- `alert_events`
- `planned_events`
- `matched_events`
- `event_detection_rate`

Expected output:

- `DADN/experiments/results/<timestamp>-manual-alert-latency/interactive_alert_summary.json`
- `DADN/experiments/results/<timestamp>-manual-alert-latency/interactive_alert_summary.md`

Metric interpretation:

- `manual_trigger_to_server_alert_ms`: from pressing Enter to the server alert
  timestamp. This approximates object-entry-to-backend-alert latency if the
  operator presses Enter exactly when the object enters the frame.
- `manual_trigger_to_client_seen_ms`: from pressing Enter to the polling script
  seeing the alert. This includes polling delay and is a conservative companion
  number.
- `server_side_alert_latency_ms`: backend queue/process latency only.
- None of these is full camera-to-audio latency; audio latency still requires a
  video/audio timing test.

### False-positive / negative-scene benchmark

This is ready if a real negative-scene image set is captured first. The capture
script defaults to `expected_alert=false` when `--expected-alert` is not passed.

Capture negative frames:

```bash
python DADN/experiments/capture_real_camera_frames.py \
  --camera-url http://192.168.1.10:8081/stream \
  --output DADN/experiments/results/real_negative_qvga/images \
  --labels-out DADN/experiments/results/real_negative_qvga/labels.json \
  --frames 120 \
  --interval-seconds 0.5 \
  --failure-type real_negative_scene
```

Then benchmark the selected config:

```bash
python DADN/benchmark/benchmark_inference.py \
  --dataset DADN/experiments/results/real_negative_qvga/images \
  --labels DADN/experiments/results/real_negative_qvga/labels.json \
  --config DADN/experiments/configs/balanced_lite0_int8.json \
  --min-frames 100 \
  --min-labeled-frames 100
```

Protocol:

1. Keep the same camera, Wi-Fi, resolution, and server config as the runtime
   benchmark.
2. Capture scenes where no warning should be spoken: empty corridor, wall,
   table/floor, distant harmless objects, and normal background clutter.
3. Do not include a close person/object in the negative set.
4. Report `false_alert_rate` from the benchmark summary. If the summary has no
   labeled negative frames, mark the metric invalid.

### Full camera-to-audio end-to-end latency

There is no fully automatic script for this yet because the metric depends on
physical timing: object enters camera view, ESP32 capture/encode, Wi-Fi,
backend inference, browser/TTS, and speaker playback.

Recommended manual protocol:

1. Run the server and dashboard with QVGA and `sweep_lite0_s040_r10`.
2. Use one phone camera to record both the ESP32-CAM field of view and the
   speaker/browser audio.
3. Trigger 20-30 object-entry events.
4. For each event, measure the time difference between first visible object
   entry and first audible alert.
5. Report mean, median, and p95, and label the number as approximate empirical
   full end-to-end latency.

Do not mix this value with `server_side_alert_latency_ms`.
