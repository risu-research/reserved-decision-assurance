# Reproducibility and claim boundaries

This is a public snapshot of a **small deterministic offline research prototype**, not a field study or assurance certificate for deployed AI systems.

## Verified local reproduction

- Python standard library, SQLite, local filesystem; no network, API credentials, or model inference.
- `python -m unittest discover -s tests -q`: 44 tests pass in the local environment.
- `python run_empowerment_study.py`: 210 purpose-built scenario conditions x 3 policies = 630 local executions.
- `python run_signoff_study.py`: 60 scripted local-controller signoff trials, not human-participant trials.
- `python run_evidence_probes.py`: verifies distinctions between SQL state, local file bytes, and unsupported claims.
- `python demo_human_empowerment.py`: small human-reserved/delegated-action example.

## Reference results

| Policy | Executed | Held | Denied | Human-only actions executed |
| --- | ---: | ---: | ---: | ---: |
| Admission-only | 210 | 0 | 0 | 60 |
| Resource/epoch dispatch guard | 120 | 0 | 90 | 60 |
| Reserved decision assurance | 60 | 90 | 60 | 0 |

These values reflect **author-designed scenario labels** and policy rules. A fully informed existing global policy monitor given the same rules and information would make the same decisions. No evidence here of improved real-world human control or superiority to such a monitor.

**What evidence supports:** bounded local transaction execution, purpose-built case-level decisions, scoped file-state observations.

**Not supported:** authenticated human consent, user comprehension, external system effects, causal proof from file hashes alone, safe deployment, statistical generalization, or a new fundamental control algorithm.

The experiment reports 40% fewer *constructed review requests* compared with a blanket-review rule over 150 eligible cases. This is not a measured human time saving.

Source, tests, and data needed to reproduce the reported v0.5 experiments are included.
