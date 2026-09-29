#!/usr/bin/env python3
###############################################################################
# Script: check_sizing.py
# Purpose: Check that the Deployments and DaemonSets of an OpenShift namespace
#          are correctly sized against the namespace sizing (ResourceQuota,
#          ClusterResourceQuota, LimitRange) for CPU and memory requests/limits,
#          and that the quota leaves enough room to roll out an update.
#
# Usage: ./check_sizing.py -n NAMESPACE [-n NAMESPACE ...] [options]
#        ./check_sizing.py -A                      # every namespace you can see
#        ./check_sizing.py -f dump.json            # offline, from a dump
#
# Options:
#   -n, --namespace NS    Namespace to check (repeatable, default: current project)
#   -A, --all-namespaces  Check every namespace that has a quota or a LimitRange
#   -f, --file FILE       Read objects from a JSON file instead of the cluster, made with:
#                           oc get deploy,ds,hpa,resourcequota,limitrange -n NS -o json > dump.json
#                           (optionally add appliedclusterresourcequota to the list)
#   -o, --output FORMAT   table (default) or json
#   --warn-percent N      Warn when a quota is used above N% after the rollout (default: 90)
#   --oversize-factor F   Warn when a quota is F times (or more) what the workloads need at
#                         rollout peak: namespace sized far above its apps (default: 3, 0 = off)
#   --no-hpa              Ignore HorizontalPodAutoscalers (use spec.replicas only)
#
# What is checked, per namespace:
#   * every container has CPU/memory requests and limits (after LimitRange defaults);
#     a missing value that a quota constrains means the pods are rejected
#   * LimitRange min / max / maxLimitRequestRatio (Container and Pod level)
#   * declared footprint (replicas x pod, HPA maxReplicas, DaemonSet node count)
#     against the quota hard limits
#   * rollout of each workload: the extra pods created by the update strategy
#     (Deployment RollingUpdate maxSurge, DaemonSet maxSurge) must fit in the
#     quota headroom (hard - used)
#   * rollout of every workload at once (helm upgrade, GitOps sync)
#   * oversizing: quota far above what the workloads need, with a suggested value
#
# Exit code: 0 = OK, 1 = warnings only, 2 = errors (pods or rollouts would be blocked)
###############################################################################

import argparse
import json
import math
import subprocess
import sys
from decimal import Decimal, InvalidOperation

RESOURCES = ("requests.cpu", "limits.cpu", "requests.memory", "limits.memory")

# Quota keys that account for the same thing
QUOTA_ALIASES = {
    "cpu": "requests.cpu",
    "memory": "requests.memory",
    "requests.cpu": "requests.cpu",
    "requests.memory": "requests.memory",
    "limits.cpu": "limits.cpu",
    "limits.memory": "limits.memory",
    "pods": "pods",
    "count/pods": "pods",
}

SUFFIXES = {
    "Ki": 2 ** 10, "Mi": 2 ** 20, "Gi": 2 ** 30, "Ti": 2 ** 40, "Pi": 2 ** 50, "Ei": 2 ** 60,
    "n": Decimal("1e-9"), "u": Decimal("1e-6"), "m": Decimal("1e-3"),
    "k": 10 ** 3, "M": 10 ** 6, "G": 10 ** 9, "T": 10 ** 12, "P": 10 ** 15, "E": 10 ** 18,
}

RED = "\033[0;31m"
YELLOW = "\033[0;33m"
GREEN = "\033[0;32m"
BLUE = "\033[0;34m"
NC = "\033[0m"


###############################################################################
# Quantities
###############################################################################

def parse_quantity(value):
    """Kubernetes quantity -> Decimal (cores for CPU, bytes for memory)."""
    if value is None:
        return None
    s = str(value).strip()
    for suffix in sorted(SUFFIXES, key=len, reverse=True):
        if s.endswith(suffix) and s[:-len(suffix)]:
            try:
                return Decimal(s[:-len(suffix)]) * Decimal(SUFFIXES[suffix])
            except InvalidOperation:
                break
    try:
        return Decimal(s)
    except InvalidOperation:
        raise ValueError("invalid quantity: %r" % value)


def fmt(resource, value):
    """Human readable value for a resource key."""
    if value is None:
        return "-"
    if resource == "pods":
        return str(int(value))
    if resource.endswith("cpu"):
        if value == value.to_integral_value():
            return str(int(value))
        return "%dm" % int((value * 1000).to_integral_value(rounding="ROUND_CEILING"))
    for unit, factor in (("Gi", 2 ** 30), ("Mi", 2 ** 20), ("Ki", 2 ** 10)):
        if abs(value) >= factor:
            v = value / factor
            return ("%d%s" % (v, unit)) if v == v.to_integral_value() else ("%.1f%s" % (v, unit))
    return str(int(value))


def round_up(resource, value):
    """Round a suggested quota to a readable step (100m CPU, 128Mi memory, 1 pod)."""
    step = {"pods": Decimal(1)}.get(resource, Decimal("0.1") if resource.endswith("cpu") else Decimal(128 * 2 ** 20))
    return max(step, (value / step).to_integral_value(rounding="ROUND_CEILING") * step)


def int_or_percent(value, total, round_up, default):
    """Resolve an IntOrString like maxSurge against a replica count."""
    if value is None:
        value = default
    if isinstance(value, int):
        return value
    s = str(value)
    if s.endswith("%"):
        raw = Decimal(s[:-1]) * total / 100
        return int(math.ceil(raw) if round_up else math.floor(raw))
    return int(s)


###############################################################################
# Data collection
###############################################################################

def oc_json(args, tolerate_error=False):
    cmd = ["oc"] + args + ["-o", "json"]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        sys.exit("error: 'oc' not found in PATH")
    if out.returncode != 0:
        if tolerate_error:
            return {"items": []}
        sys.exit("error: %s\n%s" % (" ".join(cmd), out.stderr.strip()))
    return json.loads(out.stdout)


def current_project():
    out = subprocess.run(["oc", "project", "-q"], capture_output=True, text=True, check=False)
    if out.returncode != 0:
        sys.exit("error: no namespace given and no current project: %s" % out.stderr.strip())
    return out.stdout.strip()


def collect_from_cluster(namespaces, all_namespaces):
    kinds = "deployments,daemonsets,horizontalpodautoscalers,resourcequotas,limitranges"
    if all_namespaces:
        items = oc_json(["get", kinds, "--all-namespaces"])["items"]
    else:
        items = []
        for ns in namespaces:
            items += oc_json(["get", kinds, "-n", ns])["items"]
    # OpenShift multi-project quotas, readable by project users (absent on plain Kubernetes)
    nss = sorted({i["metadata"]["namespace"] for i in items}) if all_namespaces else namespaces
    for ns in nss:
        for crq in oc_json(["get", "appliedclusterresourcequotas", "-n", ns], tolerate_error=True)["items"]:
            crq["metadata"]["namespace"] = ns
            items.append(crq)
    return items


def collect_from_file(path):
    with open(path) as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    if data.get("kind", "").endswith("List") or "items" in data:
        return data.get("items", [])
    return [data]


KINDS = ("Deployment", "DaemonSet", "HorizontalPodAutoscaler", "ResourceQuota", "LimitRange",
         "AppliedClusterResourceQuota")


def group_by_namespace(items, wanted):
    namespaces = {ns: {k: [] for k in KINDS} for ns in wanted}
    for item in items:
        ns = item.get("metadata", {}).get("namespace", "default")
        if wanted and ns not in wanted:
            continue
        bucket = namespaces.setdefault(ns, {k: [] for k in KINDS})
        if item.get("kind") in bucket:
            bucket[item["kind"]].append(item)
    return namespaces


###############################################################################
# LimitRange
###############################################################################

class LimitRanges:
    def __init__(self, limitranges):
        self.container = []
        self.pod = []
        self.names = [lr["metadata"]["name"] for lr in limitranges]
        for lr in limitranges:
            for limit in lr.get("spec", {}).get("limits", []):
                if limit.get("type") == "Container":
                    self.container.append(limit)
                elif limit.get("type") == "Pod":
                    self.pod.append(limit)

    def defaults(self, field, resource):
        """Default limit (field=default) or request (field=defaultRequest) for a container."""
        for limit in self.container:
            # The API server fills defaultRequest from default, and default from max
            chain = {"default": ("default", "max"), "defaultRequest": ("defaultRequest", "default", "max")}[field]
            for key in chain:
                if resource in limit.get(key, {}):
                    return parse_quantity(limit[key][resource])
        return None

    def check(self, limits, level, where, request, limit, resource, findings):
        for lr in limits:
            lo = parse_quantity(lr.get("min", {}).get(resource))
            hi = parse_quantity(lr.get("max", {}).get(resource))
            ratio = parse_quantity(lr.get("maxLimitRequestRatio", {}).get(resource))
            if lo is not None:
                if request is None or request < lo:
                    findings.error(where, "%s %s request %s is below LimitRange min %s -> pods rejected"
                                   % (level, resource, fmt(resource, request), fmt(resource, lo)))
            if hi is not None:
                if limit is None:
                    findings.error(where, "%s %s has no limit but LimitRange max is %s -> pods rejected"
                                   % (level, resource, fmt(resource, hi)))
                elif limit > hi:
                    findings.error(where, "%s %s limit %s is above LimitRange max %s -> pods rejected"
                                   % (level, resource, fmt(resource, limit), fmt(resource, hi)))
            if ratio is not None and request and limit and limit / request > ratio:
                findings.error(where, "%s %s limit/request ratio %.2f is above LimitRange maxLimitRequestRatio %s"
                               " -> pods rejected" % (level, resource, limit / request, ratio))


###############################################################################
# Quotas
###############################################################################

class Quota:
    def __init__(self, name, kind, hard, used, scopes, scope_selector):
        self.name = name
        self.kind = kind
        self.hard = {}
        self.used = {}
        for key, value in hard.items():
            if key in QUOTA_ALIASES:
                canonical = QUOTA_ALIASES[key]
                q = parse_quantity(value)
                self.hard[canonical] = min(q, self.hard.get(canonical, q))
                self.used[canonical] = parse_quantity(used.get(key, "0"))
        self.scopes = scopes or []
        self.scope_selector = scope_selector or []

    @classmethod
    def from_object(cls, obj):
        if obj["kind"] == "AppliedClusterResourceQuota":
            spec = obj.get("spec", {}).get("quota", {})
            status = obj.get("status", {}).get("total", {})
        else:
            spec = obj.get("spec", {})
            status = obj.get("status", {})
        return cls(obj["metadata"]["name"], obj["kind"], spec.get("hard", {}), status.get("used", {}),
                   spec.get("scopes"), spec.get("scopeSelector", {}).get("matchExpressions"))

    def applies_to(self, pod):
        """Does this quota count the pods of a workload (scopes / scopeSelector)?"""
        best_effort = all(pod.request(r) == 0 and pod.limit(r) == 0 for r in ("cpu", "memory"))
        terminating = pod.active_deadline is not None
        checks = [(s, "Exists", []) for s in self.scopes]
        checks += [(e.get("scopeName"), e.get("operator"), e.get("values", [])) for e in self.scope_selector]
        for scope, operator, values in checks:
            if scope == "BestEffort" and not best_effort:
                return False
            if scope == "NotBestEffort" and best_effort:
                return False
            if scope == "Terminating" and not terminating:
                return False
            if scope == "NotTerminating" and terminating:
                return False
            if scope == "PriorityClass":
                pc = pod.priority_class
                if operator == "In" and pc not in values:
                    return False
                if operator == "NotIn" and pc in values:
                    return False
                if operator == "Exists" and not pc:
                    return False
                if operator == "DoesNotExist" and pc:
                    return False
        return True

    def label(self):
        return ("clusterquota/" if self.kind == "AppliedClusterResourceQuota" else "quota/") + self.name


###############################################################################
# Workloads
###############################################################################

class Pod:
    """Effective resources of one pod of a workload, after LimitRange defaulting."""

    def __init__(self, pod_spec, limitranges, where, findings, quotas):
        self.priority_class = pod_spec.get("priorityClassName")
        self.active_deadline = pod_spec.get("activeDeadlineSeconds")
        containers = [(c, "container") for c in pod_spec.get("containers", [])]
        inits = []
        for c in pod_spec.get("initContainers", []):
            # Native sidecars (restartPolicy: Always) run alongside the app containers
            kind = "sidecar" if c.get("restartPolicy") == "Always" else "init"
            inits.append((c, kind))

        effective = []  # (name, kind, {resource: value})
        for c, kind in inits + containers:
            res = c.get("resources", {})
            values = {}
            for r in ("cpu", "memory"):
                req = parse_quantity(res.get("requests", {}).get(r))
                lim = parse_quantity(res.get("limits", {}).get(r))
                if req is None and lim is not None:
                    req = lim  # API server defaulting: request = limit
                if lim is None:
                    lim = limitranges.defaults("default", r)
                if req is None:
                    req = limitranges.defaults("defaultRequest", r)
                    if req is not None and lim is not None and req > lim:
                        req = lim
                values["requests." + r] = req
                values["limits." + r] = lim
                cwhere = "%s container %s" % (where, c.get("name"))
                limitranges.check(limitranges.container, "container", cwhere, req, lim, r, findings)
            effective.append((c.get("name"), kind, values))

        # Pod total the way quota counts it:
        #   max( sum(app containers + sidecars), max over init containers of (init + sidecars started before) )
        self.values = {}
        for key in RESOURCES:
            main = sum((v[key] or 0) for _, k, v in effective if k in ("container", "sidecar"))
            peak_init = Decimal(0)
            sidecars = Decimal(0)
            for _, k, v in effective:
                if k == "sidecar":
                    sidecars += v[key] or 0
                elif k == "init":
                    peak_init = max(peak_init, (v[key] or 0) + sidecars)
            self.values[key] = Decimal(max(main, peak_init))
        self.missing = {key: [n for n, _, v in effective if v[key] is None] for key in RESOURCES}

        for r in ("cpu", "memory"):
            limitranges.check(limitranges.pod, "pod", where, self.request(r),
                              None if self.missing["limits." + r] else self.limit(r), r, findings)

        constrained = {key for q in quotas if q.applies_to(self) for key in q.hard}
        for key in RESOURCES:
            if not self.missing[key]:
                continue
            names = ", ".join(self.missing[key])
            if key in constrained:
                findings.error(where, "no %s on container(s) %s and no LimitRange default, but a quota"
                               " constrains %s -> pods rejected" % (key, names, key))
            elif key.startswith("requests"):
                findings.warn(where, "no %s on container(s) %s: the scheduler cannot size this pod"
                              % (key, names))
            else:
                findings.warn(where, "no %s on container(s) %s: unbounded consumption" % (key, names))

    def request(self, r):
        return self.values["requests." + r]

    def limit(self, r):
        return self.values["limits." + r]


class Workload:
    def __init__(self, obj, hpas, limitranges, quotas, findings, use_hpa):
        self.kind = obj["kind"]
        self.name = obj["metadata"]["name"]
        self.ref = "%s/%s" % (self.kind.lower(), self.name)
        spec = obj.get("spec", {})
        status = obj.get("status", {})
        self.pod = Pod(spec.get("template", {}).get("spec", {}), limitranges, self.ref, findings, quotas)
        self.hpa_max = None

        if self.kind == "Deployment":
            self.replicas = spec.get("replicas", 1)
            if use_hpa:
                for hpa in hpas:
                    target = hpa.get("spec", {}).get("scaleTargetRef", {})
                    if target.get("kind") == "Deployment" and target.get("name") == self.name:
                        self.hpa_max = hpa["spec"].get("maxReplicas")
            self.max_replicas = max(self.replicas, self.hpa_max or 0)
            strategy = spec.get("strategy", {}) or {}
            self.strategy = strategy.get("type", "RollingUpdate")
            if self.strategy == "Recreate":
                self.surge = 0
            else:
                ru = strategy.get("rollingUpdate", {}) or {}
                self.surge = int_or_percent(ru.get("maxSurge"), self.max_replicas, True, "25%")
                unavailable = int_or_percent(ru.get("maxUnavailable"), self.max_replicas, False, "25%")
                if self.surge == 0 and unavailable == 0:
                    findings.error(self.ref, "maxSurge and maxUnavailable both resolve to 0: rollout cannot progress")
        else:  # DaemonSet: one pod per eligible node
            self.replicas = status.get("desiredNumberScheduled", 0)
            self.max_replicas = self.replicas
            strategy = spec.get("updateStrategy", {}) or {}
            self.strategy = strategy.get("type", "RollingUpdate")
            if self.strategy == "OnDelete":
                self.surge = 0
            else:
                ru = strategy.get("rollingUpdate", {}) or {}
                self.surge = int_or_percent(ru.get("maxSurge"), self.replicas, True, 0)
            if "desiredNumberScheduled" not in status:
                findings.warn(self.ref, "no status.desiredNumberScheduled (offline dump?): node count taken as 0")

        # Resources this workload counts in each quota (steady state and rollout extra)
        self.steady = {}
        self.rollout = {}
        for key in RESOURCES:
            self.steady[key] = self.pod.values[key] * self.max_replicas
            self.rollout[key] = self.pod.values[key] * self.surge
        self.steady["pods"] = Decimal(self.max_replicas)
        self.rollout["pods"] = Decimal(self.surge)


###############################################################################
# Findings
###############################################################################

class Findings:
    def __init__(self):
        self.items = []

    def error(self, where, message):
        self._add("ERROR", where, message)

    def warn(self, where, message):
        self._add("WARN", where, message)

    def info(self, where, message):
        self._add("INFO", where, message)

    def _add(self, level, where, message):
        if (level, where, message) not in self.items:
            self.items.append((level, where, message))

    def level(self):
        levels = {lvl for lvl, _, _ in self.items}
        return 2 if "ERROR" in levels else 1 if "WARN" in levels else 0


###############################################################################
# Analysis
###############################################################################

def analyse_namespace(ns, objects, args):
    findings = Findings()
    limitranges = LimitRanges(objects["LimitRange"])
    quotas = [Quota.from_object(q) for q in objects["ResourceQuota"] + objects["AppliedClusterResourceQuota"]]
    workloads = [Workload(w, objects["HorizontalPodAutoscaler"], limitranges, quotas, findings, not args.no_hpa)
                 for w in objects["Deployment"] + objects["DaemonSet"]]

    if not quotas:
        findings.warn(ns, "no ResourceQuota / ClusterResourceQuota: namespace sizing is not enforced")
    if not limitranges.names:
        findings.info(ns, "no LimitRange: containers without requests/limits get no default")

    for w in workloads:
        if w.hpa_max and w.hpa_max > w.replicas:
            findings.info(w.ref, "HPA can scale to %d replicas (spec.replicas=%d): sized at %d"
                          % (w.hpa_max, w.replicas, w.max_replicas))
        if w.kind == "Deployment" and w.strategy == "Recreate":
            findings.info(w.ref, "Recreate strategy: no extra quota needed for updates, but downtime during rollout")
        if w.kind == "DaemonSet" and w.surge == 0 and w.strategy == "RollingUpdate":
            findings.info(w.ref, "DaemonSet rolls without surge (maxSurge=0): no extra quota, one node at a time")

    quota_reports = []
    for q in quotas:
        scoped = [w for w in workloads if q.applies_to(w.pod)]
        rows = []
        for key in ("requests.cpu", "limits.cpu", "requests.memory", "limits.memory", "pods"):
            if key not in q.hard:
                continue
            hard = q.hard[key]
            used = q.used.get(key, Decimal(0))
            declared = sum((w.steady[key] for w in scoped), Decimal(0))
            biggest = max(scoped, key=lambda w: w.rollout[key], default=None)
            one_rollout = biggest.rollout[key] if biggest else Decimal(0)
            all_rollout = sum((w.rollout[key] for w in scoped), Decimal(0))
            # Rollouts need room on top of what is really running (used) and of what is declared,
            # whichever is higher (a workload may currently be scaled down or stuck on the quota)
            base = max(used, declared)
            headroom = hard - base

            status = "OK"
            if declared > hard:
                status = "OVER"
                findings.error(q.label(), "%s: workloads declare %s (steady state) but quota hard is %s"
                               % (key, fmt(key, declared), fmt(key, hard)))
            for w in scoped:
                if status == "OVER":
                    break  # steady state already does not fit, rollouts are moot
                if w.rollout[key] and base + w.rollout[key] > hard:
                    status = "NO-ROLLOUT"
                    findings.error(w.ref, "%s: rollout needs +%s (%d surge pod(s)) but %s leaves only %s"
                                   " -> update will stall" % (key, fmt(key, w.rollout[key]), w.surge,
                                                             q.label(), fmt(key, hard - base)))
            if status == "OK" and all_rollout and base + all_rollout > hard:
                status = "SERIAL"
                findings.warn(q.label(), "%s: updating all workloads at once needs +%s but only %s left:"
                              " roll them out one by one" % (key, fmt(key, all_rollout), fmt(key, hard - base)))
            peak = base + all_rollout
            if status == "OK" and hard and peak * 100 > hard * args.warn_percent:
                status = "TIGHT"
                findings.warn(q.label(), "%s: %d%% used at rollout peak (%s / %s)"
                              % (key, peak * 100 / hard, fmt(key, peak), fmt(key, hard)))
            # Oversizing: the quota reserves far more than the workloads can use, even while they
            # all roll out at once. Suggest the smallest quota that stays under --warn-percent.
            ratio = hard / peak if peak else None
            suggested = round_up(key, peak * 100 / args.warn_percent) if peak else None
            if status == "OK" and args.oversize_factor and hard and (peak == 0 or ratio >= args.oversize_factor):
                status = "OVERSIZED"
                if peak == 0:
                    findings.warn(q.label(), "%s: quota is %s but no workload in scope uses any"
                                  % (key, fmt(key, hard)))
                else:
                    findings.warn(q.label(), "%s: quota %s is %.1fx what the workloads need at rollout peak"
                                  " (%s): pods under-sized or quota over-sized, ~%s would be enough"
                                  % (key, fmt(key, hard), ratio, fmt(key, peak), fmt(key, suggested)))
            rows.append({"resource": key, "hard": hard, "used": used, "declared": declared,
                         "headroom": headroom, "one_rollout": one_rollout, "all_rollout": all_rollout,
                         "peak": peak, "ratio": ratio, "suggested": suggested, "status": status})
        # Quota on requests/limits without a matching limit on the other side
        for r in ("cpu", "memory"):
            if "limits." + r in q.hard and "requests." + r not in q.hard:
                findings.info(q.label(), "limits.%s capped but not requests.%s" % (r, r))
        quota_reports.append({"quota": q, "rows": rows, "workloads": [w.ref for w in scoped]})

    return {"namespace": ns, "workloads": workloads, "quotas": quota_reports,
            "limitranges": limitranges.names, "findings": findings}


###############################################################################
# Output
###############################################################################

def color(text, code, enabled):
    return "%s%s%s" % (code, text, NC) if enabled else text


def print_table(rows, headers):
    widths = [max(len(str(x)) for x in col) for col in zip(headers, *rows)]
    line = "  ".join("%-*s" % (w, h) for w, h in zip(widths, headers))
    print("  " + line)
    print("  " + "  ".join("-" * w for w in widths))
    for row in rows:
        print("  " + "  ".join("%-*s" % (w, str(c)) for w, c in zip(widths, row)))


def output_table(reports, use_color):
    status_colors = {"OK": GREEN, "OVERSIZED": YELLOW, "TIGHT": YELLOW, "SERIAL": YELLOW, "NO-ROLLOUT": RED, "OVER": RED}
    level_colors = {"ERROR": RED, "WARN": YELLOW, "INFO": BLUE}
    for rep in reports:
        print(color("=== Namespace: %s ===" % rep["namespace"], BLUE, use_color))
        print("LimitRanges: %s" % (", ".join(rep["limitranges"]) or "none"))
        print()
        print("Workloads (per pod, after LimitRange defaults):")
        rows = []
        for w in rep["workloads"]:
            def v(key):
                return "none" if w.pod.missing[key] else fmt(key, w.pod.values[key])
            replicas = str(w.replicas) + ("->%d(hpa)" % w.max_replicas if w.max_replicas != w.replicas else "")
            rows.append([w.ref, replicas, w.strategy, "+%d" % w.surge,
                         "%s/%s" % (v("requests.cpu"), v("limits.cpu")),
                         "%s/%s" % (v("requests.memory"), v("limits.memory")),
                         "%s/%s" % (fmt("cpu", w.steady["requests.cpu"]), fmt("memory", w.steady["requests.memory"])),
                         "%s/%s" % (fmt("cpu", w.rollout["requests.cpu"]), fmt("memory", w.rollout["requests.memory"]))])
        if rows:
            print_table(rows, ["WORKLOAD", "REPLICAS", "STRATEGY", "SURGE", "POD CPU req/lim",
                               "POD MEM req/lim", "TOTAL req cpu/mem", "ROLLOUT +req cpu/mem"])
        else:
            print("  none")
        print()
        for qr in rep["quotas"]:
            print("%s (applies to %d workload(s)):" % (qr["quota"].label(), len(qr["workloads"])))
            rows = []
            for r in qr["rows"]:
                k = r["resource"]
                rows.append([k, fmt(k, r["hard"]), fmt(k, r["used"]), fmt(k, r["declared"]),
                             fmt(k, r["headroom"]), "+" + fmt(k, r["one_rollout"]), "+" + fmt(k, r["all_rollout"]),
                             "x%.1f" % r["ratio"] if r["ratio"] is not None else "-",
                             color(r["status"], status_colors[r["status"]], use_color)])
            if rows:
                print_table(rows, ["RESOURCE", "HARD", "USED", "DECLARED", "HEADROOM",
                                   "BIGGEST ROLLOUT", "ALL ROLLOUTS", "HARD/PEAK", "STATUS"])
            else:
                print("  no cpu/memory/pods limits")
            print()
        items = rep["findings"].items
        print("Findings:" if items else color("Findings: none, sizing is consistent", GREEN, use_color))
        for level in ("ERROR", "WARN", "INFO"):
            for lvl, where, msg in items:
                if lvl == level:
                    print("  %s %s: %s" % (color("[%s]" % lvl, level_colors[lvl], use_color), where, msg))
        print()
    print("Legend: DECLARED = sum of replicas (HPA max, DaemonSet nodes) x pod; HEADROOM = hard - max(used, declared);")
    print("        STATUS OK | TIGHT (>warn% at peak) | SERIAL (updates must be sequential) |")
    print("        NO-ROLLOUT (an update will stall) | OVER (steady state does not fit) |")
    print("        OVERSIZED (quota >= --oversize-factor x need at peak); PEAK = max(used, declared) + all rollouts")


def output_json(reports):
    def num(key, v):
        return None if v is None else (int(v) if key == "pods" else float(v))

    out = []
    for rep in reports:
        out.append({
            "namespace": rep["namespace"],
            "limitranges": rep["limitranges"],
            "workloads": [{
                "ref": w.ref, "replicas": w.replicas, "max_replicas": w.max_replicas, "hpa_max": w.hpa_max,
                "strategy": w.strategy, "surge": w.surge,
                "pod": {k: num(k, w.pod.values[k]) for k in RESOURCES},
                "steady": {k: num(k, v) for k, v in w.steady.items()},
                "rollout": {k: num(k, v) for k, v in w.rollout.items()},
            } for w in rep["workloads"]],
            "quotas": [{
                "name": qr["quota"].label(), "workloads": qr["workloads"],
                "resources": [{k: (num(r["resource"], v) if k not in ("resource", "status", "ratio")
                                   else float(v) if k == "ratio" and v is not None else v)
                               for k, v in r.items()} for r in qr["rows"]],
            } for qr in rep["quotas"]],
            "findings": [{"level": l, "object": w, "message": m} for l, w, m in rep["findings"].items],
        })
    print(json.dumps(out, indent=2))


###############################################################################
# Main
###############################################################################

def main():
    parser = argparse.ArgumentParser(description="Check Deployment/DaemonSet sizing against namespace quotas "
                                                 "and LimitRanges, including rollout headroom.")
    parser.add_argument("-n", "--namespace", action="append", default=[], help="namespace (repeatable)")
    parser.add_argument("-A", "--all-namespaces", action="store_true",
                        help="every namespace that has a quota or a LimitRange")
    parser.add_argument("-f", "--file", help="JSON dump (oc get ... -o json) instead of the cluster")
    parser.add_argument("-o", "--output", choices=("table", "json"), default="table")
    parser.add_argument("--warn-percent", type=int, default=90,
                        help="warn when a quota is above this %% at rollout peak (default: 90)")
    parser.add_argument("--oversize-factor", type=float, default=3,
                        help="warn when a quota is this many times the need at rollout peak (default: 3, 0 = off)")
    parser.add_argument("--no-hpa", action="store_true", help="ignore HorizontalPodAutoscalers")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()

    if args.file:
        items = collect_from_file(args.file)
    else:
        if not args.namespace and not args.all_namespaces:
            args.namespace = [current_project()]
        items = collect_from_cluster(args.namespace, args.all_namespaces)

    grouped = group_by_namespace(items, set(args.namespace))
    if args.all_namespaces:
        grouped = {ns: o for ns, o in grouped.items()
                   if o["ResourceQuota"] or o["LimitRange"] or o["AppliedClusterResourceQuota"]}
    if not grouped:
        sys.exit("error: nothing to check")

    reports = [analyse_namespace(ns, grouped[ns], args) for ns in sorted(grouped)]
    if args.output == "json":
        output_json(reports)
    else:
        output_table(reports, sys.stdout.isatty() and not args.no_color)
    sys.exit(max(rep["findings"].level() for rep in reports))


if __name__ == "__main__":
    main()
