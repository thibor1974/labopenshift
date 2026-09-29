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

# simulate_node_loss.py

From an extract of the cluster, totals the CPU/memory requests and limits of every workload
(Deployment, StatefulSet, DaemonSet, DeploymentConfig, Job...) and simulates the loss of one or
more nodes: can every pod of the lost node(s) be scheduled again on the remaining ones?

Runs offline on the extract, so it can be used on a cluster you only get a dump from.
Uses `check_sizing.py` (same directory) for the quantity parsing.

## Usage

```bash
# Extract (cluster-admin, or at least read on nodes and pods in every namespace)
oc get nodes,pods,replicasets,deployments,statefulsets,daemonsets,jobs -A -o json > cluster.json
# ... or let the script run that command and analyse the result
./simulate_node_loss.py --extract cluster.json

./simulate_node_loss.py -f cluster.json                          # lose each node, one at a time
./simulate_node_loss.py -f cluster.json --role worker            # only lose worker nodes
./simulate_node_loss.py -f cluster.json --lose worker-1 --lose worker-2   # lose both together
./simulate_node_loss.py -f cluster.json -s workloads --exclude-system --csv totals.csv
./simulate_node_loss.py -f cluster.json -v                       # placement detail per scenario
./simulate_node_loss.py -f cluster.json -o json
```

Exit code: `0` every scenario OK, `1` warnings (pods already Pending, bare pods lost),
`2` at least one scenario leaves pods unschedulable.

## Output

- **Workload totals**: per workload, pods running/desired, nodes used, sum of requests and
  limits (`none` / `*` = no limit on all / some containers). Filter with `-n REGEX` or
  `--exclude-system`; `--csv` exports it (cores and bytes) for a spreadsheet.
- **Nodes**: allocatable, requested (what the scheduler reserves) and limits (overcommit) per node.
- **Simulation**: per lost node, the pods to move, the requests moved, the fullest remaining node
  afterwards and the result. Unschedulable pods get a scheduler-like reason, e.g.
  `0/5 nodes available: 3 untolerated taint node-role.kubernetes.io/master, 2 insufficient cpu`.

## How the simulation works

- Pods of the lost node: DaemonSet and static pods disappear with it, bare pods (no controller)
  are not recreated, every other pod must be scheduled again.
- They are placed by priority, then size, on the least allocated node (the default OpenShift
  scheduler profile) that passes: cordon / NotReady, taints and tolerations, nodeSelector,
  required node affinity, requests vs allocatable (cpu, memory, pods, extended resources),
  host ports, required pod affinity / anti-affinity, `topologySpreadConstraints` with
  `DoNotSchedule`.
- Only requests matter for scheduling. Limits only show the overcommit risk (throttling, OOM).

## Limits of the simulation

- No preemption: a high priority pod that does not fit is reported unschedulable, while the real
  scheduler could evict lower priority pods to make room (which would then be the ones pending).
- Volumes are not modelled: a pod bound to a zone (EBS, vSphere...) or a local PV can only restart
  where its volume is reachable, and RWO volumes are released only after the detach timeout.
- StatefulSet pods restart only once the node object is deleted or the pods are force-deleted.
- Pod (anti-)affinity with a `namespaceSelector` is treated as matching all namespaces (namespace
  labels are not in the extract), which is the conservative choice.
- Pods already Pending before the loss are reported but not included in the simulation.
