# Engineering validation

These artifacts are implementation checks, **not model parity**. No paid model
API calls were made. The pinned Harbor version is 0.23.0 at commit
`99218a4611e3bd76e49ce3b5f977e8c8134ad3ac`.

- `differential.json`: the pinned original AgentGym clients, wrappers and
  LMRL-Gym implementations compared with the adapter: 50 tasks, 350 scenarios,
  3,280 state comparisons, and 50 successful reference episodes. Reproduce with
  `bash scripts/run_upstream_check.sh` from the adapter directory.
- `harbor-oracle.json`: the full 50-task Docker job's unmodified aggregate result
  and selected per-trial fields, including task checksums and verifier rewards.
- `harbor-native-smoke.json`: Maze 00 and Wordle 00 through the native Harbor
  agent using a local mock Chat Completions service that replays reference
  actions. It validates transport and conversation wiring, not model ability.
- `harbor-nop-smoke.json`: the same two tasks with Harbor's no-op agent. Both
  must receive zero reward with no infrastructure exception.
- `oracle-terminal.txt` and `oracle-terminal.svg`: captured Harbor terminal
  output and a rendering of that exact output for the PR.

After installing the pinned Harbor version and this adapter as described in the
main README, generate and run the full oracle job:

```bash
uv run agenteval-games --output-dir /tmp/agenteval-generated
harbor run -p /tmp/agenteval-generated -a oracle \
  --job-name agenteval-oracle-50 --jobs-dir /tmp/agenteval-harbor-jobs \
  --n-concurrent 4 --max-retries 0
```

Run the no-op negative control with a new job name:

```bash
harbor run -p /tmp/agenteval-generated -a nop \
  -i agenteval-maze-00 -i agenteval-wordle-00 \
  --job-name agenteval-nop-smoke-01 --jobs-dir /tmp/agenteval-harbor-jobs \
  --n-concurrent 2 --max-retries 0
```

Job timestamps are preserved exactly as emitted by Harbor. Trial configuration,
host paths, and environment variables are not included in the selected per-trial
fields. The original full job directories remain local to the execution host;
these are not Harbor Hub or Hugging Face publication records.

After the container runs, newly authored Python files were formatted with Ruff
0.11.13. All 17 abstract syntax trees were unchanged (recorded in
`format-equivalence.json`), and all 21 unit/interface tests passed again with no
skips. The recorded task checksums identify the generated files used in the
container runs, before that formatting-only change. Vendored upstream code and
prompt whitespace are retained verbatim.
