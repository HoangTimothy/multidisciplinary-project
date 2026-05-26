# DADN Dataset Artifacts

This folder contains the public benchmark subset that is used for offline
configuration tuning and report-ready correctness measurements.

## Public benchmark subset

- Images: `datasets/dadn_public/subset/images`
- Full labels: `datasets/dadn_public/subset/labels.json`
- Group-only labels: `datasets/dadn_public/subset/labels_group.json`

The full labels file includes `expected_alert`, `expected_group`,
`expected_zone`, and `expected_distance`.

The group-only file is useful when a benchmark only needs:
- `person`
- `vehicle`
- `static_obstacle`

## Usage

Use the public subset as the dataset input for:

- `python DADN/experiments/run_tuning_sweep.py`
- `python DADN/benchmark/record_metrics.py`

Do not treat this dataset as i.i.d. with the live ESP32-CAM stream. It is an
offline benchmark artifact, not a runtime deployment trace.
