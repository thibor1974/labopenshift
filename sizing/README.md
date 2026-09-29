# check_sizing.py

Checks that the Deployments and DaemonSets of an OpenShift namespace fit the namespace sizing
(ResourceQuota, ClusterResourceQuota, LimitRange) for CPU and memory requests/limits, and that the
quota leaves enough room to roll out an update.

Needs only `python3` (3.9+) and `oc` (logged in). No extra Python packages.

## Usage

```bash
./check_sizing.py                      # current project
./check_sizing.py -n dev-thib-1 -n dev-thib-2
./check_sizing.py -A                   # every namespace with a quota or LimitRange
./check_sizing.py -n dev-thib-1 -o json
./check_sizing.py -n dev-thib-1 --oversize-factor 2   # stricter oversizing check

# Offline, from a dump
oc get deploy,ds,hpa,resourcequota,limitrange,appliedclusterresourcequota -n dev-thib-1 -o json > dump.json
./check_sizing.py -f dump.json
```

Exit code: `0` OK, `1` warnings only, `2` errors (pods rejected or rollout blocked), usable in a pipeline.

## What is computed

- **Pod size**: per container after LimitRange defaults (request = limit when only the limit is set),
  then pod total the way quota counts it: `max(sum(containers + sidecars), biggest init container)`.
- **Declared footprint**: pod × replicas. HPA `maxReplicas` is used when higher; a DaemonSet uses
  `status.desiredNumberScheduled` (its node count).
- **Rollout extra**: the surge pods created during an update.
  - Deployment `RollingUpdate`: `maxSurge` (default 25%, rounded up). `Recreate`: none.
  - DaemonSet `RollingUpdate`: `maxSurge` (default 0). `OnDelete`: none.
- **Headroom**: `hard - max(used, declared)` per quota. Quota scopes (`BestEffort`, `NotTerminating`,
  `PriorityClass`...) decide which workloads a quota counts.

## Statuses per quota resource

| Status | Meaning |
|---|---|
| OK | fits, including every rollout at once |
| TIGHT | above `--warn-percent` (default 90%) at rollout peak |
| SERIAL | each workload can roll out, but not all at once (helm upgrade / GitOps sync) |
| NO-ROLLOUT | at least one workload update will stall: surge pods rejected by the quota |
| OVER | the declared replicas do not even fit in steady state |
| OVERSIZED | quota is `--oversize-factor` times (default 3) or more what the workloads need at peak |

**Oversizing**: peak need = `max(used, declared) + all rollouts`. The `HARD/PEAK` column shows the
ratio. When it reaches the factor, the namespace reserves far more than its apps can use: either
the pods are sized too low (requests/limits to raise) or the quota is too generous. The finding
suggests the smallest quota that stays under `--warn-percent` at peak (rounded to 100m CPU,
128Mi memory). `--oversize-factor 0` disables the check.

Findings also flag containers without requests/limits (pods rejected when a quota constrains the
missing value and no LimitRange default fills it) and LimitRange min/max/ratio violations.

## Limits

- Checks the **current** pod template. If an update also changes requests/limits, the new pods use
  the new values: run the script on the updated manifests (`-f`) to check them.
- Terminating pods keep counting in the quota during their grace period, so a real rollout can
  briefly need a bit more than the computed surge. Keep some margin (see TIGHT).
- StatefulSets, DeploymentConfigs, Jobs and builds are not modelled, but whatever they consume is in
  the quota `used` value, so it reduces the headroom.
- Node capacity (can the scheduler place the pods) is not checked, only namespace sizing.
