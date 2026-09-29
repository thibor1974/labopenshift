#!/usr/bin/env python3
###############################################################################
# Script: simulate_node_loss.py
# Purpose: From an extract of an OpenShift cluster, total the CPU/memory
#          requests and limits of every workload (Deployment, StatefulSet,
#          DaemonSet, DeploymentConfig, Job...) and simulate the loss of nodes:
#          can every pod of the lost node be scheduled again on the others?
#
# Usage: ./simulate_node_loss.py --extract cluster.json    # dump the cluster, then analyse
#        ./simulate_node_loss.py -f cluster.json            # analyse an existing extract
#        ./simulate_node_loss.py -f cluster.json --lose worker-1 --lose worker-2
#
# The extract is a plain `oc get -o json` (what --extract runs):
#   oc get nodes,pods,replicasets,deployments,statefulsets,daemonsets,jobs -A -o json > cluster.json
#
# Options:
#   -f, --file FILE       Extract to read (repeatable, e.g. one file per kind)
#   --extract FILE        Run the oc command above, save it to FILE and analyse it
#   --lose NODE           Node to lose (repeatable: all lost together). Default: each
#                         Ready node, one at a time
#   --role ROLE           With the default mode, only lose nodes of this role (e.g. worker)
#   -n, --namespace REGEX Only show matching namespaces in the workload totals
#   --exclude-system      Hide openshift-* / kube-* namespaces from the workload totals
#                         (they are always part of the simulation)
#   -s, --section NAME    workloads, nodes, simulation (repeatable, default: all)
#   --csv FILE            Also write the workload totals to a CSV file
#   -v, --verbose         Detail every scenario, not only the failing ones
#   -o, --output FORMAT   table (default) or json
#
# Simulation (what the scheduler would do with the pods of the lost node):
#   * DaemonSet and static pods of the lost node disappear with it; bare pods
#     (no controller) are not recreated; every other pod must be rescheduled
#   * pods are placed by priority then size, on the least allocated node that passes:
#     cordon / NotReady, taints and tolerations, nodeSelector, required node affinity,
#     requests vs allocatable (cpu, memory, pods count, extended resources), host ports,
#     required pod (anti-)affinity, topologySpreadConstraints (DoNotSchedule)
#   * only requests count for scheduling; limits are shown as overcommit
#
# Exit code: 0 = every scenario OK, 1 = warnings (pending pods, pods not recreated),
#            2 = at least one scenario leaves pods unschedulable
###############################################################################

import argparse
import csv
import json
import re
import subprocess
import sys
from collections import Counter
from decimal import Decimal

from check_sizing import BLUE, GREEN, RED, YELLOW, collect_from_file, color, fmt, parse_quantity, print_table

EXTRACT_KINDS = "nodes,pods,replicasets,deployments,statefulsets,daemonsets,jobs"
SYSTEM_NAMESPACES = re.compile(r"^(openshift|kube-)")
BLOCKING_EFFECTS = ("NoSchedule", "NoExecute")
ZERO = Decimal(0)


###############################################################################
# Extract
###############################################################################

def extract(path):
    cmd = ["oc", "get", EXTRACT_KINDS, "--all-namespaces", "-o", "json"]
    print("Extracting: %s > %s" % (" ".join(cmd), path), file=sys.stderr)
    try:
        with open(path, "w") as f:
            out = subprocess.run(cmd, stdout=f, stderr=subprocess.PIPE, text=True, check=False)
    except FileNotFoundError:
        sys.exit("error: 'oc' not found in PATH")
    if out.returncode != 0:
        sys.exit("error: %s\n%s" % (" ".join(cmd), out.stderr.strip()))


###############################################################################
# Selectors, taints
###############################################################################

def match_label_selector(selector, labels):
    if selector is None:
        return False  # a null selector matches nothing
    for key, value in (selector.get("matchLabels") or {}).items():
        if labels.get(key) != value:
            return False
    for expr in selector.get("matchExpressions") or []:
        if not match_expression(expr, labels):
            return False
    return True


def match_expression(expr, labels):
    key, op, values = expr.get("key"), expr.get("operator"), expr.get("values") or []
    if op == "In":
        return labels.get(key) in values
    if op == "NotIn":
        return labels.get(key) not in values
    if op == "Exists":
        return key in labels
    if op == "DoesNotExist":
        return key not in labels
    if op in ("Gt", "Lt") and key in labels:
        try:
            a, b = int(labels[key]), int(values[0])
        except (ValueError, IndexError):
            return False
        return a > b if op == "Gt" else a < b
    return False


def match_node_affinity(terms, node):
    """requiredDuringScheduling nodeSelectorTerms: terms are ORed, expressions ANDed."""
    if not terms:
        return True
    for term in terms:
        exprs = term.get("matchExpressions") or []
        fields = term.get("matchFields") or []
        if not exprs and not fields:
            continue
        if all(match_expression(e, node.labels) for e in exprs) and \
                all(match_expression(e, {"metadata.name": node.name}) for e in fields):
            return True
    return False


def tolerates(tolerations, taint):
    for t in tolerations:
        if t.get("effect") and t["effect"] != taint.get("effect"):
            continue
        op = t.get("operator", "Equal")
        if not t.get("key"):
            if op == "Exists":
                return True  # empty key + Exists tolerates everything
            continue
        if t["key"] != taint.get("key"):
            continue
        if op == "Exists" or t.get("value", "") == taint.get("value", ""):
            return True
    return False


###############################################################################
# Objects
###############################################################################

def add_into(total, values):
    for key, value in values.items():
        total[key] = total.get(key, ZERO) + value


def pod_resources(spec):
    """Pod requests/limits the way the scheduler counts them:
    max(sum(app containers + sidecars), max over init containers of (init + sidecars before)) + overhead."""
    inits = [(c, "sidecar" if c.get("restartPolicy") == "Always" else "init") for c in spec.get("initContainers") or []]
    containers = inits + [(c, "app") for c in spec.get("containers") or []]
    overhead = spec.get("overhead") or {}
    result = {}
    unlimited = set()
    for field in ("requests", "limits"):
        names = {n for c, _ in containers for n in ((c.get("resources") or {}).get(field) or {})}
        totals = {}
        for name in names | {"cpu", "memory"}:
            main = sidecars = peak = ZERO
            for c, kind in containers:
                raw = ((c.get("resources") or {}).get(field) or {}).get(name)
                value = parse_quantity(raw) or ZERO
                if field == "limits" and raw is None and kind != "init" and name in ("cpu", "memory"):
                    unlimited.add(name)
                if kind == "init":
                    peak = max(peak, value + sidecars)
                else:
                    main += value
                    if kind == "sidecar":
                        sidecars += value
            totals[name] = max(main, peak) + (parse_quantity(overhead.get(name)) or ZERO)
        result[field] = totals
    return result["requests"], result["limits"], unlimited


class Owners:
    """Resolve a pod to the workload that owns it (Deployment through its ReplicaSet, etc.)."""

    def __init__(self, items):
        self.parents = {}  # (kind, ns, name) -> (kind, name) of its controller
        self.desired = {}  # (ns, kind, name) -> desired replicas
        for item in items:
            kind, meta = item.get("kind"), item.get("metadata", {})
            ns, name = meta.get("namespace"), meta.get("name")
            if kind in ("ReplicaSet", "Job"):
                refs = [r for r in meta.get("ownerReferences") or [] if r.get("controller")]
                if refs:
                    self.parents[(kind, ns, name)] = (refs[0]["kind"], refs[0]["name"])
            elif kind in ("Deployment", "StatefulSet"):
                self.desired[(ns, kind, name)] = item.get("spec", {}).get("replicas", 1)
            elif kind == "DaemonSet":
                self.desired[(ns, kind, name)] = item.get("status", {}).get("desiredNumberScheduled")

    def resolve(self, pod):
        meta = pod["metadata"]
        ns = meta.get("namespace")
        refs = meta.get("ownerReferences") or []
        refs = [r for r in refs if r.get("controller")] or refs
        if not refs:
            return "Pod", meta["name"]
        kind, name = refs[0]["kind"], refs[0]["name"]
        if kind in ("ReplicaSet", "Job") and (kind, ns, name) in self.parents:
            return self.parents[(kind, ns, name)]
        if kind == "ReplicaSet":
            # ReplicaSets not in the extract: strip the pod-template-hash suffix
            h = (meta.get("labels") or {}).get("pod-template-hash")
            if h and name.endswith("-" + h):
                return "Deployment", name[:-len(h) - 1]
        if kind == "ReplicationController":
            dc = (meta.get("annotations") or {}).get("openshift.io/deployment-config.name")
            if dc:
                return "DeploymentConfig", dc
        if kind == "Node":
            return "Static", meta["name"]
        return kind, name


class Pod:
    def __init__(self, obj, owners):
        meta, spec = obj["metadata"], obj.get("spec", {})
        self.ns, self.name = meta.get("namespace"), meta["name"]
        self.labels = meta.get("labels") or {}
        self.node = spec.get("nodeName")
        self.phase = obj.get("status", {}).get("phase")
        self.terminal = self.phase in ("Succeeded", "Failed")
        self.priority = spec.get("priority") or 0
        self.tolerations = spec.get("tolerations") or []
        self.node_selector = spec.get("nodeSelector") or {}
        affinity = spec.get("affinity") or {}
        required = "requiredDuringSchedulingIgnoredDuringExecution"
        self.node_affinity = ((affinity.get("nodeAffinity") or {}).get(required) or {}).get("nodeSelectorTerms")
        self.anti_affinity = (affinity.get("podAntiAffinity") or {}).get(required) or []
        self.pod_affinity = (affinity.get("podAffinity") or {}).get(required) or []
        self.spread = [c for c in spec.get("topologySpreadConstraints") or []
                       if c.get("whenUnsatisfiable", "DoNotSchedule") == "DoNotSchedule"]
        self.host_ports = {(p.get("protocol", "TCP"), p["hostPort"])
                           for c in spec.get("containers") or [] for p in c.get("ports") or [] if p.get("hostPort")}
        self.requests, self.limits, self.unlimited = pod_resources(spec)
        self.kind, self.owner = owners.resolve(obj)
        self.mirror = "kubernetes.io/config.mirror" in (meta.get("annotations") or {})

    @property
    def ref(self):
        return "%s/%s" % (self.ns, self.name)

    @property
    def workload(self):
        return "%s/%s/%s" % (self.ns, self.kind.lower(), self.owner)

    def term_namespaces(self, term):
        """Namespaces a pod (anti-)affinity term looks at; None = all."""
        if term.get("namespaceSelector") is not None:
            return None  # namespace labels are not in the extract: assume all, the conservative choice
        return set(term.get("namespaces") or [self.ns])

    def term_matches(self, term, other):
        namespaces = self.term_namespaces(term)
        return (namespaces is None or other.ns in namespaces) and \
            match_label_selector(term.get("labelSelector"), other.labels)


class Node:
    def __init__(self, obj):
        meta, spec, status = obj["metadata"], obj.get("spec", {}), obj.get("status", {})
        self.name = meta["name"]
        self.labels = meta.get("labels") or {}
        self.roles = sorted(k.split("/", 1)[1] for k in self.labels if k.startswith("node-role.kubernetes.io/"))
        self.taints = [t for t in spec.get("taints") or [] if t.get("effect") in BLOCKING_EFFECTS]
        self.unschedulable = spec.get("unschedulable", False)
        self.ready = any(c.get("type") == "Ready" and c.get("status") == "True" for c in status.get("conditions") or [])
        self.allocatable = {k: parse_quantity(v) for k, v in (status.get("allocatable") or {}).items()}

    @property
    def status(self):
        s = "Ready" if self.ready else "NotReady"
        return s + (",SchedulingDisabled" if self.unschedulable else "")


###############################################################################
# Scheduler simulation
###############################################################################

class Scenario:
    def __init__(self, nodes, pods, lost):
        self.lost = lost
        self.nodes = [n for n in nodes if n.name not in lost]
        self.placed = {n.name: [] for n in self.nodes}
        self.used = {n.name: {} for n in self.nodes}
        self.displaced, self.gone, self.not_recreated = [], [], []
        for p in pods:
            if p.terminal or not p.node:
                continue
            if p.node in self.placed:
                self.placed[p.node].append(p)
                add_into(self.used[p.node], p.requests)
            elif p.node in lost:
                if p.kind in ("DaemonSet", "Static") or p.mirror:
                    self.gone.append(p)
                elif p.kind == "Pod":
                    self.not_recreated.append(p)
                else:
                    self.displaced.append(p)
        self.assigned = {}
        self.unplaced = []  # (pod, "0/N nodes available: ...")
        self.run()

    def domain_pods(self, key, value):
        for n in self.nodes:
            if n.labels.get(key) == value:
                for p in self.placed[n.name]:
                    yield p

    def reason(self, pod, node):
        """Why pod cannot go on node, or None when it fits."""
        if not node.ready:
            return "node NotReady"
        if node.unschedulable:
            return "node cordoned"
        for taint in node.taints:
            if not tolerates(pod.tolerations, taint):
                return "untolerated taint %s" % taint.get("key")
        if any(node.labels.get(k) != v for k, v in pod.node_selector.items()) or \
                not match_node_affinity(pod.node_affinity, node):
            return "node selector/affinity mismatch"
        used = self.used[node.name]
        for name, value in sorted(pod.requests.items()):
            if value > 0 and value > node.allocatable.get(name, ZERO) - used.get(name, ZERO):
                return "insufficient %s" % name
        if len(self.placed[node.name]) + 1 > node.allocatable.get("pods", Decimal(110)):
            return "too many pods"
        if pod.host_ports and any(pod.host_ports & p.host_ports for p in self.placed[node.name]):
            return "host port conflict"
        # Required anti-affinity, both ways: the incoming pod's terms and the placed pods' terms
        for term in pod.anti_affinity:
            key = term.get("topologyKey")
            if key in node.labels and any(pod.term_matches(term, p)
                                          for p in self.domain_pods(key, node.labels[key])):
                return "pod anti-affinity"
        for n in self.nodes:
            for p in self.placed[n.name]:
                for term in p.anti_affinity:
                    key = term.get("topologyKey")
                    if key in node.labels and n.labels.get(key) == node.labels[key] and p.term_matches(term, pod):
                        return "pod anti-affinity (of %s)" % p.workload
        for term in pod.pod_affinity:
            key = term.get("topologyKey")
            if key in node.labels and any(pod.term_matches(term, p) for p in self.domain_pods(key, node.labels[key])):
                continue
            everywhere = any(pod.term_matches(term, p) for ps in self.placed.values() for p in ps)
            if everywhere or not pod.term_matches(term, pod):
                return "pod affinity"
        for constraint in pod.spread:
            if not self.spread_ok(pod, node, constraint):
                return "topology spread (%s)" % constraint.get("topologyKey")
        return None

    def spread_ok(self, pod, node, constraint):
        key = constraint.get("topologyKey")
        if key not in node.labels:
            return False
        selector = constraint.get("labelSelector")
        counts = {}
        for n in self.nodes:
            # Default nodeAffinityPolicy=Honor: only nodes the pod could select form domains
            if key not in n.labels or any(n.labels.get(k) != v for k, v in pod.node_selector.items()) or \
                    not match_node_affinity(pod.node_affinity, n):
                continue
            count = sum(1 for p in self.placed[n.name] if p.ns == pod.ns and match_label_selector(selector, p.labels))
            counts[n.labels[key]] = counts.get(n.labels[key], 0) + count
        if not counts:
            return True
        self_match = 1 if match_label_selector(selector, pod.labels) else 0
        return counts.get(node.labels[key], 0) + self_match - min(counts.values()) <= constraint.get("maxSkew", 1)

    def score(self, pod, node):
        """LeastAllocated: prefer the node with the most free cpu/memory after placement."""
        free = []
        for r in ("cpu", "memory"):
            alloc = node.allocatable.get(r, ZERO)
            if alloc:
                free.append((alloc - self.used[node.name].get(r, ZERO) - pod.requests.get(r, ZERO)) / alloc)
        return sum(free) / len(free) if free else ZERO

    def run(self):
        order = sorted(self.displaced, key=lambda p: (-p.priority, -p.requests.get("cpu", ZERO),
                                                     -p.requests.get("memory", ZERO), p.ref))
        for pod in order:
            reasons = Counter()
            best = None
            for node in self.nodes:
                why = self.reason(pod, node)
                if why:
                    reasons[why] += 1
                elif best is None or self.score(pod, node) > self.score(pod, best):
                    best = node
            if best is None:
                detail = ", ".join("%d %s" % (n, r) for r, n in reasons.most_common())
                self.unplaced.append((pod, "0/%d nodes available: %s" % (len(self.nodes), detail or "no node left")))
            else:
                self.assigned[pod.ref] = best.name
                self.placed[best.name].append(pod)
                add_into(self.used[best.name], pod.requests)

    def moved_requests(self):
        total = {}
        for p in self.displaced:
            add_into(total, p.requests)
        return total

    def utilisation(self):
        """Per remaining node: (requested cpu %, requested memory %, pods, pods allocatable)."""
        rows = {}
        for n in self.nodes:
            rows[n.name] = tuple(pct(self.used[n.name].get(r, ZERO), n.allocatable.get(r)) for r in ("cpu", "memory"))
        return rows

    def free(self):
        """Per remaining node: allocatable - requests, for cpu and memory."""
        return {n.name: {r: n.allocatable.get(r, ZERO) - self.used[n.name].get(r, ZERO) for r in ("cpu", "memory")}
                for n in self.nodes}


def pct(value, total):
    return int(value * 100 / total) if total else 0


###############################################################################
# Reports
###############################################################################

def workload_totals(pods, owners, args):
    groups = {}
    for p in pods:
        if p.terminal:
            continue
        if args.namespace and not re.search(args.namespace, p.ns or ""):
            continue
        if args.exclude_system and SYSTEM_NAMESPACES.match(p.ns or ""):
            continue
        g = groups.setdefault((p.ns, p.kind, p.owner), {"pods": 0, "pending": 0, "nodes": set(), "requests": {},
                                                          "limits": {}, "unlimited": set()})
        g["pods"] += 1
        if not p.node:
            g["pending"] += 1
        else:
            g["nodes"].add(p.node)
        add_into(g["requests"], p.requests)
        add_into(g["limits"], p.limits)
        g["unlimited"] |= p.unlimited
    rows = []
    for (ns, kind, name), g in sorted(groups.items()):
        rows.append({"namespace": ns, "kind": kind, "name": name, "pods": g["pods"], "pending": g["pending"],
                     "desired": owners.desired.get((ns, kind, name)), "nodes": len(g["nodes"]),
                     "requests.cpu": g["requests"].get("cpu", ZERO), "requests.memory": g["requests"].get("memory", ZERO),
                     "limits.cpu": g["limits"].get("cpu", ZERO), "limits.memory": g["limits"].get("memory", ZERO),
                     "unlimited": sorted(g["unlimited"])})
    return rows


def node_rows(nodes, pods):
    rows = []
    for n in nodes:
        on = [p for p in pods if p.node == n.name and not p.terminal]
        req, lim = {}, {}
        for p in on:
            add_into(req, p.requests)
            add_into(lim, p.limits)
        rows.append({"node": n.name, "roles": ",".join(n.roles) or "-", "status": n.status,
                     "alloc.cpu": n.allocatable.get("cpu", ZERO), "alloc.memory": n.allocatable.get("memory", ZERO),
                     "alloc.pods": n.allocatable.get("pods", ZERO), "pods": len(on),
                     "requests.cpu": req.get("cpu", ZERO), "requests.memory": req.get("memory", ZERO),
                     "limits.cpu": lim.get("cpu", ZERO), "limits.memory": lim.get("memory", ZERO)})
        for r in ("cpu", "memory"):
            rows[-1]["free." + r] = rows[-1]["alloc." + r] - rows[-1]["requests." + r]
    return rows


def cluster_totals(rows):
    """Sum of the node rows (every node, control plane included)."""
    keys = [k for k in rows[0] if "." in k] if rows else []
    totals = {k: sum((r[k] for r in rows), ZERO) for k in keys}
    totals["pods"] = sum(r["pods"] for r in rows)
    return totals


def role_totals(rows):
    """cluster_totals per role combination (e.g. master, worker, infra,worker): a node is counted once."""
    groups = {}
    for r in rows:
        groups.setdefault(r["roles"], []).append(r)
    return {role: dict(cluster_totals(g), nodes=len(g)) for role, g in sorted(groups.items())}


def limit_text(row, resource):
    value = row["limits." + resource]
    if resource not in row["unlimited"]:
        return fmt(resource, value)
    return "none" if not value else fmt(resource, value) + "*"


def print_workloads(rows, use_color):
    print(color("=== Workload totals (running + pending pods) ===", BLUE, use_color))
    table = []
    for r in rows:
        pods = str(r["pods"]) if r["desired"] is None else "%d/%d" % (r["pods"], r["desired"])
        if r["pending"]:
            pods += " (%d pending)" % r["pending"]
        table.append([r["namespace"], r["kind"], r["name"], pods, r["nodes"],
                      fmt("cpu", r["requests.cpu"]), limit_text(r, "cpu"),
                      fmt("memory", r["requests.memory"]), limit_text(r, "memory")])
    total = {k: sum((r[k] for r in rows), ZERO) for k in ("requests.cpu", "limits.cpu", "requests.memory", "limits.memory")}
    table.append(["TOTAL", "", "%d workload(s)" % len(rows), sum(r["pods"] for r in rows), "",
                  fmt("cpu", total["requests.cpu"]), fmt("cpu", total["limits.cpu"]),
                  fmt("memory", total["requests.memory"]), fmt("memory", total["limits.memory"])])
    print_table(table, ["NAMESPACE", "KIND", "NAME", "PODS", "NODES", "REQ CPU", "LIM CPU", "REQ MEM", "LIM MEM"])
    print("  none / *: no limit on all / some containers, the real limit is unbounded")
    print()


def print_nodes(rows, use_color):
    print(color("=== Nodes (requests are what the scheduler reserves, limits show overcommit) ===", BLUE, use_color))
    table = []
    totals = [dict(t, node="TOTAL", roles=role, status="%d node(s)" % t["nodes"])
              for role, t in role_totals(rows).items()]
    totals.append(dict(cluster_totals(rows), node="TOTAL", roles="all", status="%d node(s)" % len(rows)))
    for r in rows + totals:
        table.append([r["node"], r["roles"], r["status"], "%d/%d" % (r["pods"], r["alloc.pods"]),
                      "%s/%s (%d%%)" % (fmt("cpu", r["requests.cpu"]), fmt("cpu", r["alloc.cpu"]),
                                        pct(r["requests.cpu"], r["alloc.cpu"])),
                      "%d%%" % pct(r["limits.cpu"], r["alloc.cpu"]), fmt("cpu", r["free.cpu"]),
                      "%s/%s (%d%%)" % (fmt("memory", r["requests.memory"]), fmt("memory", r["alloc.memory"]),
                                        pct(r["requests.memory"], r["alloc.memory"])),
                      "%d%%" % pct(r["limits.memory"], r["alloc.memory"]), fmt("memory", r["free.memory"])])
    print_table(table, ["NODE", "ROLES", "STATUS", "PODS", "REQ CPU / ALLOC", "LIM CPU", "FREE CPU",
                        "REQ MEM / ALLOC", "LIM MEM", "FREE MEM"])
    print("  FREE = allocatable - requests: what the scheduler can still place. TOTAL <ROLES> sums the nodes with")
    print("  exactly these roles (tainted or cordoned ones included); a pod must fit on a single node, not in a total.")
    print()


def print_simulation(scenarios, pending, verbose, use_color):
    print(color("=== Node loss simulation ===", BLUE, use_color))
    if pending:
        print(color("  %d pod(s) already Pending before any loss (not part of the simulation):" % len(pending),
                    YELLOW, use_color))
        for p in pending[:10]:
            print("    %s (%s)" % (p.ref, p.workload))
        if len(pending) > 10:
            print("    ...")
    table = []
    for s in scenarios:
        moved = s.moved_requests()
        util = s.utilisation()
        worst_cpu = max((u[0] for u in util.values()), default=0)
        worst_mem = max((u[1] for u in util.values()), default=0)
        result = color("OK", GREEN, use_color) if not s.unplaced else \
            color("FAIL (%d unschedulable)" % len(s.unplaced), RED, use_color)
        table.append([", ".join(s.lost), len(s.displaced), "%s / %s" % (fmt("cpu", moved.get("cpu", ZERO)),
                                                                         fmt("memory", moved.get("memory", ZERO))),
                      "%d%% / %d%%" % (worst_cpu, worst_mem), len(s.not_recreated), result])
    print_table(table, ["LOST NODE(S)", "PODS TO MOVE", "REQ CPU / MEM MOVED", "FULLEST NODE CPU/MEM",
                        "NOT RECREATED", "RESULT"])
    print()
    for s in scenarios:
        if not verbose and not s.unplaced and not s.not_recreated:
            continue
        print("--- Loss of %s ---" % ", ".join(s.lost))
        for pod, why in s.unplaced:
            print("  %s %s [%s] req %s/%s prio %d: %s" % (
                color("[UNSCHEDULABLE]", RED, use_color), pod.ref, pod.workload,
                fmt("cpu", pod.requests.get("cpu", ZERO)), fmt("memory", pod.requests.get("memory", ZERO)),
                pod.priority, why))
        for pod in s.not_recreated:
            print("  %s %s: bare pod without controller, lost with the node"
                  % (color("[NOT RECREATED]", YELLOW, use_color), pod.ref))
        sts = sorted({p.workload for p in s.displaced if p.kind == "StatefulSet"})
        if sts:
            print("  [INFO] StatefulSet pods only restart once the lost node is deleted or its pods force-deleted: %s"
                  % ", ".join(sts))
        if verbose:
            util = s.utilisation()
            free = s.free()
            print("  Remaining nodes after rescheduling (requested cpu% / memory%, free cpu / memory):")
            for name, (c, m) in sorted(util.items()):
                print("    %-40s %3d%% / %3d%%   %8s / %s" % (name, c, m, fmt("cpu", free[name]["cpu"]),
                                                            fmt("memory", free[name]["memory"])))
            by_role = {}
            for n in s.nodes:
                add_into(by_role.setdefault(",".join(n.roles) or "-", {}), free[n.name])
            by_role = sorted(by_role.items())
            by_role.append(("all", {}))
            for f in free.values():
                add_into(by_role[-1][1], f)
            for role, f in by_role:
                print("    %-40s               %8s / %s" % ("TOTAL " + role, fmt("cpu", f.get("cpu", ZERO)),
                                                         fmt("memory", f.get("memory", ZERO))))
            if s.assigned:
                print("  Placement of the moved pods:")
            for pod in sorted(s.displaced, key=lambda p: p.ref):
                if pod.ref in s.assigned:
                    print("    %s -> %s" % (pod.ref, s.assigned[pod.ref]))
        print()


def to_json(workloads, nodes, scenarios, pending):
    def num(v):
        return float(v) if isinstance(v, Decimal) else v

    return {
        "workloads": [{k: num(v) for k, v in r.items()} for r in workloads],
        "nodes": [{k: num(v) for k, v in r.items()} for r in nodes],
        "cluster": {k: num(v) for k, v in cluster_totals(nodes).items()},
        "roles": {role: {k: num(v) for k, v in t.items()} for role, t in role_totals(nodes).items()},
        "pending_before": [p.ref for p in pending],
        "scenarios": [{
            "lost": s.lost,
            "result": "OK" if not s.unplaced else "FAIL",
            "pods_to_move": len(s.displaced),
            "requests_moved": {k: num(v) for k, v in s.moved_requests().items()},
            "unschedulable": [{"pod": p.ref, "workload": p.workload, "priority": p.priority, "reason": why,
                               "requests": {k: num(v) for k, v in p.requests.items()}} for p, why in s.unplaced],
            "not_recreated": [p.ref for p in s.not_recreated],
            "placement": s.assigned,
            "utilisation_after": {n: {"cpu_pct": c, "memory_pct": m, "free_cpu": num(s.free()[n]["cpu"]),
                                      "free_memory": num(s.free()[n]["memory"])}
                                  for n, (c, m) in s.utilisation().items()},
        } for s in scenarios],
    }


def write_csv(path, rows):
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["namespace", "kind", "name", "pods", "desired", "pending", "nodes",
                    "requests_cpu_cores", "limits_cpu_cores", "requests_memory_bytes", "limits_memory_bytes",
                    "no_limit_on"])
        for r in rows:
            w.writerow([r["namespace"], r["kind"], r["name"], r["pods"], r["desired"] if r["desired"] is not None else "",
                        r["pending"], r["nodes"], r["requests.cpu"], r["limits.cpu"], int(r["requests.memory"]),
                        int(r["limits.memory"]), " ".join(r["unlimited"])])
    print("Workload totals written to %s" % path, file=sys.stderr)


###############################################################################
# Main
###############################################################################

def main():
    parser = argparse.ArgumentParser(description="Total requests/limits per workload and simulate node loss "
                                                 "from an OpenShift extract.")
    parser.add_argument("-f", "--file", action="append", default=[], help="extract (oc get ... -o json), repeatable")
    parser.add_argument("--extract", metavar="FILE", help="dump the cluster with oc into FILE, then analyse it")
    parser.add_argument("--lose", action="append", default=[], metavar="NODE",
                        help="node to lose (repeatable, lost together); default: each node in turn")
    parser.add_argument("--role", help="default mode: only lose nodes with this role (e.g. worker)")
    parser.add_argument("-n", "--namespace", metavar="REGEX", help="namespaces shown in the workload totals")
    parser.add_argument("--exclude-system", action="store_true", help="hide openshift-*/kube-* from workload totals")
    parser.add_argument("-s", "--section", action="append", choices=("workloads", "nodes", "simulation"))
    parser.add_argument("--csv", metavar="FILE", help="write the workload totals to a CSV file")
    parser.add_argument("-v", "--verbose", action="store_true", help="detail every scenario")
    parser.add_argument("-o", "--output", choices=("table", "json"), default="table")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()

    if args.extract:
        extract(args.extract)
        args.file.append(args.extract)
    if not args.file:
        parser.error("give an extract with -f FILE, or create one with --extract FILE")
    items = []
    for path in args.file:
        items += collect_from_file(path)

    owners = Owners(items)
    nodes = sorted((Node(i) for i in items if i.get("kind") == "Node"), key=lambda n: n.name)
    pods = [Pod(i, owners) for i in items if i.get("kind") == "Pod"]
    if not nodes or not pods:
        sys.exit("error: the extract must contain nodes and pods (found %d nodes, %d pods)" % (len(nodes), len(pods)))

    names = {n.name for n in nodes}
    unknown = [n for n in args.lose if n not in names]
    if unknown:
        sys.exit("error: unknown node(s): %s" % ", ".join(unknown))
    if args.lose:
        losses = [args.lose]
    else:
        losses = [[n.name] for n in nodes if n.ready and (not args.role or args.role in n.roles)]
        if not losses:
            sys.exit("error: no Ready node%s to simulate" % (" with role " + args.role if args.role else ""))

    sections = set(args.section or ("workloads", "nodes", "simulation"))
    workloads = workload_totals(pods, owners, args)
    node_table = node_rows(nodes, pods)
    pending = [p for p in pods if not p.node and not p.terminal]
    scenarios = [Scenario(nodes, pods, lost) for lost in losses] if "simulation" in sections else []

    if args.csv:
        write_csv(args.csv, workloads)
    if args.output == "json":
        print(json.dumps(to_json(workloads, node_table, scenarios, pending), indent=2))
    else:
        use_color = sys.stdout.isatty() and not args.no_color
        if "workloads" in sections:
            print_workloads(workloads, use_color)
        if "nodes" in sections:
            print_nodes(node_table, use_color)
        if "simulation" in sections:
            print_simulation(scenarios, pending, args.verbose, use_color)

    if any(s.unplaced for s in scenarios):
        sys.exit(2)
    sys.exit(1 if pending or any(s.not_recreated for s in scenarios) else 0)


if __name__ == "__main__":
    main()
