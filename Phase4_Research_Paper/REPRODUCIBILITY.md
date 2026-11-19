# Experimental reproduction and evidence

The [project repository](https://github.com/Muhammad-Umair-Ahmad/Autonomous-Troubleshooting-Agents) contains the Phase 3 code, datasets, snapshots, protocols, and raw runs alongside the paper. Contact: [i242545@isb.nu.edu.pk](mailto:i242545@isb.nu.edu.pk).

## Evidence locations in the Phase 3 parent folder

| Paper content | Evidence |
|---|---|
| Original comparative and robustness means | `Evaluation/Original study/summary.csv` and `runs.csv` |
| All original outcomes | `Evaluation/Original raw runs/` (366 JSON records) |
| Paired intervals and tests | `Evaluation/Original study/paired-comparisons.csv` |
| Condition-level robustness | `Evaluation/Original study/robustness-by-condition.csv` |
| Revised diagnoses, repair totals and runtime | `Evaluation/Revised study/followup.csv` and `Evaluation/Revised raw runs/` (21 JSON records) |
| Controlled safety table | `Evaluation/Original study/controlled-safety.json` (eight specified-plan executions) |
| Live isolation and recovery checks | `Evaluation/isolation-proof.json` and `Evaluation/controlled-remediation.json` |
| Triple-fault qualitative example | `Evaluation/Revised raw runs/849e2a1ec38c0a8d404d0a52.json` |
| Dataset and private fault truth | `Implementation/data/public/local-cases.json` and `Implementation/data/private/local-truth.json` |
| Environment and dependency versions | `Implementation/configs/environment.lock.json` and `Implementation/requirements-lock.txt` |
| Source identities | `Implementation/configs/sources.lock.json` |
| Original protocol and model identities | `Implementation/configs/experiments.submission.json` |
| Revised protocol | `Evaluation/Revised study/protocol.json` |
| Exact historical code/input snapshots | `Evaluation/Original study/frozen-source-and-inputs.tar.gz` and `Evaluation/Revised study/source.tar.gz` |

## Fresh development run

From `Implementation/`, with Docker, Kathara, the pinned images, prepared prerequisite records (including `results/prerequisites/images.json`), and the named Ollama models available:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install -e . --no-deps
scripts/neta diagnose --case dev-route--standard --improved --knowledge curated-v1
```

Choose another retained model with `--model qwen2.5-coder:3b` or `--model llama3.2:1b`. The standard case suffix is part of the identifier. Run only one controller at a time. Network/model binaries and Python environments are not bundled with the artifact. Where needed on the recorded macOS host, the Phase 3 operating guide documents `DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib`.

Fresh CLI execution is a development check. Historical replay requires extracting the matching study archive in a separate working directory and using its saved matrix, source identities, model/image digests, and knowledge snapshot hashes. Original seeds are 1000 and 1001 at temperature 0.2; the revised follow-up uses seed 1000 at temperature zero. Model identity and quantization are frozen in the manifest, not merely specified by mutable tags.

Scoped cleanup is `scripts/neta cleanup`; it targets registered research labs. The optional upstream Linux lifecycle route is documented in the Phase 3 report and is separate from local agent-score reproduction. Downloaded Lima binaries are not versioned in this repository; use a suitable local installation if that optional route is required.

## Paper audit and figure regeneration

From the Phase 3 parent folder:

```sh
python3 Phase4_Research_Paper/build_evidence.py
sh Phase4_Research_Paper/source/build.sh
```

The audit checks all original mean F1, exact match, total time, and token summaries against the raw records; verifies the revised 21 exact diagnoses and 18 faulty-case repairs; checks final restoration; and records local absolute/relative F1 gains. Plots use those actual saved means. Statistical intervals are the saved group-bootstrap results, not newly invented run-level intervals.

The per-model final runtime means are taken from the revised saved records. The healthy case is excluded from the repair denominator. SADE-local is diagnosis-only and its repair value is N/A. Relative improvement from a zero F1 baseline is undefined.
