# Implementation and experimental evidence

The [repository](https://github.com/Muhammad-Umair-Ahmad/Autonomous-Troubleshooting-Agents) contains the final agent code, datasets, knowledge snapshots, saved protocols, and raw results. Contact: [i242545@isb.nu.edu.pk](mailto:i242545@isb.nu.edu.pk).

## Run the final agent

Live execution requires Python 3.12+, Docker, Kathará, Ollama, the pinned images, and prepared prerequisite records, including `Implementation/results/prerequisites/images.json`. Environment preparation and image identities are described in the Phase 3 operating guide. Model binaries and installed runtimes are not included. `configs/images.lock.json` preserves the original ARM64 image identities. Docker images must also be installed on the execution host; copying the manifest does not install them.

From `Implementation/`, restore the saved image manifest before running the agent:

```sh
mkdir -p results/prerequisites
cp configs/images.lock.json results/prerequisites/images.json
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-lock.txt
.venv/bin/python -m pip install -e . --no-deps
scripts/neta diagnose --case dev-route--standard --improved --knowledge curated-v1
```

Select another retained model with `--model qwen2.5-coder:3b` or `--model llama3.2:1b`. The default is Qwen 2.5 1.5B. The `--standard` suffix is part of the case identifier. Run one controller at a time.

For the recorded macOS environment, the Phase 3 operating guide documents the optional `DYLD_LIBRARY_PATH=/opt/homebrew/opt/expat/lib` setting. Use `scripts/neta cleanup` for scoped cleanup of registered research labs.

## Evidence locations

Paths below are relative to the repository root.

| Content | Location |
|:--|:--|
| Final agent and CLI | `Implementation/src/neta/` |
| Tests | `Implementation/tests/` |
| Original comparison and robustness means | `Evaluation/Original study/summary.csv` |
| Original execution index | `Evaluation/Original study/runs.csv` |
| Original raw results | `Evaluation/Original raw runs/` — 366 JSON records |
| Paired intervals and tests | `Evaluation/Original study/paired-comparisons.csv` |
| Condition-level robustness | `Evaluation/Original study/robustness-by-condition.csv` |
| Revised results | `Evaluation/Revised study/followup.csv` |
| Revised raw results | `Evaluation/Revised raw runs/` — 21 JSON records |
| Controlled safety outcomes | `Evaluation/Original study/controlled-safety.json` |
| Live isolation and recovery checks | `Evaluation/isolation-proof.json`, `Evaluation/controlled-remediation.json` |
| Triple-fault example | `Evaluation/Revised raw runs/849e2a1ec38c0a8d404d0a52.json` |
| Public cases and evaluator labels | `Implementation/data/public/local-cases.json`, `Implementation/data/private/local-truth.json` |
| Environment and dependency versions | `Implementation/configs/environment.lock.json`, `Implementation/requirements-lock.txt` |
| Upstream source identities | `Implementation/configs/sources.lock.json` |
| Original Kathará image identities | `Implementation/configs/images.lock.json` |
| Original protocol and model identities | `Implementation/configs/experiments.submission.json` |
| Revised protocol | `Evaluation/Revised study/protocol.json` |

## Interpreting the records

The original protocol uses seeds 1000 and 1001 at temperature 0.2. The revised follow-up uses seed 1000 at temperature zero. Records preserve model/image digests, knowledge hashes, and configuration identities. A new run of the final code is separate from replaying an earlier code revision.

The original and revised studies remain separate. Mean F1 uses faulty cases; exact match includes the healthy case. Repair rate includes every faulty execution in its denominator. SADE-local is diagnosis-only, so its repair score is not applicable. Relative improvement from a zero F1 baseline is undefined.

Historical evaluation snapshots are retained in `Evaluation/Original study/frozen-source-and-inputs.tar.gz` and `Evaluation/Revised study/source.tar.gz`. They preserve the original experiment code and inputs. Use the matching saved protocol for historical replay. The current agent code and the experiment runner remain in `Implementation/`.
