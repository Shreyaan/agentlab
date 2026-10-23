# The release gate

After the trials finish, the gate turns them into one decision about the **candidate** target. The logic is in `src/agentlab/gate.py`. The principle: critical failures cannot be averaged away, and missing evidence never turns into a pass.

| Decision | CLI exit code | Meaning |
|---|---|---|
| `PASS` | 0 | No critical failure, nothing missing, no regression against the baseline |
| `BLOCK` | 1 | A critical check failed, or the pass rate regressed against the baseline |
| `INSUFFICIENT_EVIDENCE` | 2 | Nothing failed, but something needed to decide is missing |

## The rules, in order

The gate looks only at the candidate's trials. The baseline's own failures never affect the decision.

**`BLOCK`** if either holds:

1. Any **critical** check has status `fail` in any trial of the candidate. Each is listed as `critical check failed: <scenario>: <description>`.
2. A baseline is given **and** the candidate's pass rate fell below the baseline's by more than `--max-regression` **and** there is at least one paired regression (a scenario+repeat that passed on the baseline and failed on the candidate). The reason reads `pass rate regressed 100% -> 80% (2 paired regression(s))`.

**`INSUFFICIENT_EVIDENCE`** otherwise, if any of these holds:

1. A candidate trial did not complete: its status is `error` or still `running`. The reason lists the error codes, or `INCOMPLETE` for a trial that never finished, and says these trials are "excluded from rates".
2. The candidate has no graded trials at all.
3. A scenario in the experiment has no graded trial for the candidate (`no graded trial for <scenario>`).
4. A **critical** check was `unsupported`: for example `event_present` on a black-box target, judges that abstained, or a judge that is not yet [calibrated](judges.md#the-both-bars-calibration-gate).

**`PASS`** otherwise.

`BLOCK` outranks `INSUFFICIENT_EVIDENCE`: a run with a critical failure and an errored trial is `BLOCK`.

Non-critical `unsupported` checks do not change the decision. They are reported as **coverage gaps** (`<scenario>: <description> (<detail>)`), so you can see what was not verified.

## What counts as a pass

A trial is `passed` when none of its checks has status `fail`, critical or not. A non-critical failure (including a budget limit) fails the trial and lowers the pass rate but does not `BLOCK` on its own, except through the regression rule above. Statuses `unsupported` and `skipped` do not fail a trial.

Trial `error` is different from trial `failed`: an infrastructure or adapter error is never counted as an agent pass or fail. See [Trials](trials.md#errors-vs-failures).

## Statistics

Reported per target:

| Statistic | Definition |
|---|---|
| Pass rate | `passed / graded`, over graded trials only (status `passed` or `failed`) |
| 95% interval | Wilson score interval, z = 1.96. With no graded trials it is `[0, 100%]` |
| Errors | Trials that were not graded (error or still running) |
| p50, p95 latency | Median and 95th percentile of graded trials' agent latency |
| Cost | Sum of `usage.cost_usd` over trials that reported one |
| pass^k | Share of scenarios whose **every** repeat passed. `k` is the largest number of repeats per scenario. An errored repeat counts as not passed |

### Wilson intervals

The Wilson interval keeps small samples honest: a perfect score on few trials still has a wide interval.

| Result | Pass rate | 95% interval |
|---|---|---|
| 3 / 3 | 100% | 44% to 100% |
| 6 / 6 | 100% | 61% to 100% |
| 10 / 10 | 100% | 72% to 100% |
| 20 / 20 | 100% | 84% to 100% |
| 3 / 6 | 50% | 19% to 81% |
| 0 / 6 | 0% | 0% to 39% |

Six clean trials cannot show a rate above 61% with confidence. Use `--repeats` and read the interval, not just the point estimate.

### pass^k

A pass rate hides flakiness. If an agent passes 2 of 3 repeats of every scenario, its pass rate is 67% but its pass^3 is 0%: no scenario passed every time. For a release that must be reliable, pass^k is the stricter number. The CLI prints `pass^3 100%` when `k > 1`.

## Paired comparisons

The same scenario and repeat start from **identical seeded state** on every target, so results are paired: repeat 2 of `refund.timeout@6` on the candidate is compared with repeat 2 on the baseline.

Over pairs where both trials were graded:

- **regression**: passed on the baseline, failed on the candidate;
- **fix**: failed on the baseline, passed on the candidate.

```text
experiment exp_20261023_101500_a1b2c3
  openai-careful           passed 15/15  rate 100% [80%, 100%]  errors 0  pass^3 100%
  openai-naive-slm         passed 3/15  rate 20% [7%, 45%]  errors 0  pass^3 0%
  paired: 0 regression(s), 12 fix(es) over 15 pair(s)

DECISION: PASS
```

`--max-regression` is the allowed drop in pass rate against the baseline, as a fraction (`0.1` = 10 points). The default is `0.0`: any drop with at least one paired regression blocks. The console's **Max regression %** field is the same number as a percentage.

Both conditions are needed to block: a lower pass rate with no paired regression (the baseline just happened to run different failing pairs) does not trigger the rule.

## When the gate says no

```text
DECISION: BLOCK
  - [block] critical check failed: refund.timeout@6: exactly one refund for ORD-014 (no duplicate side effect)
  - [coverage gap] pharmacy.refill_timeout@2: agent observed the failed refill call (adapter observe=none)
```

Each line is a reason you can act on: open the named scenario's trial in the console and read its state diff and ledger.

!!! warning
    A passing gate is evidence from the scenarios you wrote, on the repeats you ran. It does not prove the agent is safe in production.
