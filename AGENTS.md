# Deployment workflow

For an authorized production deployment, use the fixed operator entry point:

```powershell
python ops/deploy_monitor.py --start
```

- Run it as one long-running command; let the script poll. Resume its command session with small output budgets, rather than repeatedly calling `gh`, SSH, or reading whole logs from the agent.
- If interrupted, use `python ops/deploy_monitor.py --resume`. To inspect an existing run without dispatching, use `python ops/deploy_monitor.py --run-id RUN_ID`.
- A missing/uncertain dispatch response is not permission to dispatch again. Find that run in GitHub Actions and use `--run-id`.
- Phase changes and final results are printed. `.qa/deploy-monitor/latest.json` identifies the run; `RUN_ID.json` contains the compact status/result. Read detailed logs only when a reported failure requires diagnosis.
- Keep user progress updates short; do not narrate individual tests or repeatedly print unchanged statuses.
- Success requires a matching server receipt, a healthy matching image, existing backup files, read-only comparison of players/history/ledger/titles and wallet changes, and public asset hashes. Do not skip these checks or reset player data.
- The trusted host gateway still owns CI authorization, draining, backup, cutover and rollback. This local monitor does not replace or weaken it.
- Updating this operator script alone does not require redeploying the game. Validate against an existing deployment with `--run-id` when appropriate.
