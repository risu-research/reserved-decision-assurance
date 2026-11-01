# Reserved Decision Assurance

A small, offline prototype for checking whether a scheduled action still respects a decision a person has kept for themselves.

An agent may schedule a task while it is allowed to run. By the time the task executes, permission may have been withdrawn, resources may have changed, or the person may already have made the decision. A record saying that the task ran also tells us less than we might want to know about its effects.

This repository tests those situations with ordinary Python programs, SQLite transactions, and local files. It does not call an AI model, use an external API, or require credentials.

## Try it

Python 3.11 or later is required. No packages need to be installed.

```bash
python demo_human_empowerment.py
python -m unittest discover -s tests -q
python run_empowerment_study.py
python run_signoff_study.py
python run_evidence_probes.py
```

The demo shows a task held for a simulated human decision, a routine task allowed to proceed, and a held task executed after a test-controller approval. The study scripts regenerate the files in `results/`.

## What the checker does

A local caller supplies a decision-right specification when the job is scheduled. The specification records which decision is reserved, the authority source, the expected kind of effect, and the limits of what can be verified. The scheduled job is bound to that specification.

When the job becomes due, the checker reads the current state again. It can:

- **Delegate** a permitted task that preserves the person's reserved choice.
- **Hold for review** when the task needs a human decision or would remove a reserved option.
- **Deny** a task whose authorization is stale or whose decision has already been made.
- **Wait** when the scheduled time has not arrived.

The SQLite balance change and the execution-time check occur in one write transaction. A simulated approval is recorded separately and checked again before execution. It is not an authenticated human signature.

A receipt records what the local evidence supports. A committed database update is distinct from finding the expected bytes in a local file. Missing files, altered files, and stale observations have different outcomes. These receipts are recomputable local records, not signed attestations or evidence that anything reached an external service.

## Results from the local test cases

The experiments cover 210 deliberately constructed conditions, each run under three policies, for 630 local policy executions.

| Policy | Executed | Held for review | Denied | Human-reserved actions executed |
| --- | ---: | ---: | ---: | ---: |
| Check only when scheduled | 210 | 0 | 0 | 60 |
| Check resources and permission at execution | 120 | 0 | 90 | 60 |
| Check reserved decisions as well | 60 | 90 | 60 | 0 |

The third policy lets 60 routine tasks proceed and holds 90 for simulated review. Compared with asking for review on all 150 otherwise eligible tasks, that is 40% fewer review requests **in these constructed conditions**. It is not a measured reduction in human work or evidence of better outcomes in deployed AI systems.

A separate set of 60 scripted trials covers approval, later revocation, changed resources, and decisions made before execution. The repository includes 44 automated tests covering those cases, SQLite concurrency and crash recovery, and limits of local effect evidence. See [PUBLIC_RESULTS.md](PUBLIC_RESULTS.md) for the scope of the results.

## How this differs from a general policy monitor

The contribution of this prototype is an inspectable way to connect a human-reserved decision with the permission check at execution and the evidence available afterward. It does not introduce a new authorization algorithm. A global policy monitor given the same information and rules can make the same decisions.

The examples use rights classifications supplied by a trusted local caller. They do not determine which decisions ought to belong to a person. The actions are scripted, not chosen by a deployed LLM, and no human participants were studied.

The results depend on complete mediation through the guarded path, correct resource assumptions, and the local database's integrity. They do not establish real-world safety, authenticated consent, external delivery, or the causal origin of matching file contents.

## Repository contents

- `choice_assurance.py` — decision-right specification, execution check, simulated approval, and evidence validation
- `scheduler_rights.py`, `audit.py`, `file_adapter.py` — local scheduler and evidence adapters
- `demo_human_empowerment.py` — short example
- `run_*_study.py`, `run_evidence_probes.py` — experiment scripts
- `tests/` — unit and process tests
- `results/` — example CSV and JSON outputs
- `.github/workflows/verify.yml` — automated test and reproduction commands

All reported results can be regenerated offline. There is no private dataset or model endpoint.

## License

MIT. See [LICENSE](LICENSE).
