# OpenShift Vulnerability Scanner

A comprehensive bash/Python solution to query **real vulnerabilities** affecting specific OpenShift versions using the official Red Hat Security API.

## Features

✅ **Real-time Data** - Fetches from official Red Hat Security Advisory API  
✅ **Multiple Output Formats** - Table, CSV, JSON, and Statistics  
✅ **Fixed Release per CVE** - The OpenShift release (e.g. 4.12.92) and advisory that fix each CVE  
✅ **Fix Status** - Affected / Fix deferred / Will not fix... for CVEs not fixed yet (`--include-unfixed`)  
✅ **Severity Filtering** - Filter by critical, important, moderate, low  
✅ **Release Check** - Give a full release (e.g. 4.21.17) to see which CVEs it is still exposed to  
✅ **Fast Performance** - Results in seconds  
✅ **Cross-platform** - Works on Linux and macOS  
✅ **Three Entry Points** - Python (all logic), Bash wrapper (positional args), jq-based quick lister  

## Installation

Scripts are ready to use immediately:
```bash
chmod +x *.sh *.py
```

## Usage

### Basic Usage

```bash
# List all vulnerabilities for OpenShift 4.21
./get_vulnerabilities.sh 4.21

# List vulnerabilities in CSV format
./get_vulnerabilities.sh 4.21 csv

# List vulnerabilities in JSON format
./get_vulnerabilities.sh 4.21 json

# Show statistics for OpenShift 4.21
./get_vulnerabilities.py 4.21 --format stats

# Lookup details and fix status for a specific CVE
./get_vulnerabilities.py --cve CVE-2026-46300
./get_vulnerabilities.sh --cve CVE-2026-46300
```

### CVE Details & Fix Status (NEW!)

Check if a specific CVE is fixed and in which versions:

```bash
# Get comprehensive details about a CVE
./get_vulnerabilities.py --cve CVE-2026-46300
```

Shows:
- CVE severity and publication date
- CVSS vector (if available)
- **The release that fixes it in each OpenShift version** (e.g. 4.12 → 4.12.96, with advisory)
- **Which versions are still affected** (package fix states)
- Full vulnerability description

Example scenario:
```bash
# You found CVE-2026-46300 in your environment
# Check if upgrading to 4.21 will fix it:
./get_vulnerabilities.sh --cve CVE-2026-46300

# Output shows the release per stream, e.g.:
# Fixed in OpenShift Container Platform:
# --------------------------------------------------------------------------------
#   Stream   Fixed In     Advisory
#   4.12     4.12.96      RHSA-2026:54206
#   4.13     4.13.70      RHSA-2026:54188
#   ...
#   4.21     4.21.29      RHSA-2026:54602
#   4.22     4.22.10      RHSA-2026:54770
```

### Fixed release & fix status per CVE

```bash
# Every CVE fixed in 4.12, with the 4.12.z release that fixes it
./get_vulnerabilities.sh 4.12 csv > fixed_4.12.csv

# Also include CVEs NOT fixed in 4.12 (Affected, Fix deferred, Will not fix...) - takes 2-3 minutes
./get_vulnerabilities.py 4.12 --include-unfixed --format csv > status_4.12.csv
./get_vulnerabilities.sh --include-unfixed 4.12 table important

# Summary by fix status
./get_vulnerabilities.py 4.12 --include-unfixed --format stats

# Skip the fix lookups when you only need the CVE list (faster)
./get_vulnerabilities.py 4.12 --format csv --no-fix
```

### Check a specific release (e.g. 4.21.17)

Give the full release instead of the stream to see which CVEs your cluster is still exposed to:

```bash
./get_vulnerabilities.sh 4.21.17                      # table, most urgent first
./get_vulnerabilities.sh 4.21.17 csv important > exposure_4.21.17.csv
./get_vulnerabilities.py 4.21.17 --format stats       # counts + minimum upgrade
./get_vulnerabilities.py 4.21.17 --include-unfixed    # also CVEs with no fix yet (slow)
```

```
CVE ID           Severity   In 4.21.17           Fixed In / Status    Advisory         Date        Description
CVE-2026-84394   IMPORTANT  VULNERABLE           4.21.34              RHSA-2026:68547  2026-09-02  fast-uri: fast-uri: Host confusion via unbalanced U
CVE-2026-84292   IMPORTANT  VULNERABLE           4.21.34              RHSA-2026:68547  2026-09-02  fast-uri: fast-uri: Authority Injection via Unvalid
CVE-2026-46300   IMPORTANT  Not vulnerable       4.21.17              RHBA-2026:20032  2026-05-13  kernel: "Fragnesia" is a variant of Dirty Frag vuln
CVE-2026-41674   IMPORTANT  Not vulnerable       4.21.17              RHSA-2026:20034  2026-05-07  xmldom: xmldom: Arbitrary XML markup injection
...
In 4.21.17: VULNERABLE: 99, Not vulnerable: 19
Upgrade to 4.21.34 or later to get all available fixes
```

The **In 4.21.17** column (`version_status` in CSV/JSON):

| Value | Meaning |
|-------|---------|
| `VULNERABLE` | Fixed in a later release; **Fixed In** is the release to upgrade to |
| `Not vulnerable` | The fix shipped in this release or an earlier one |
| `Vulnerable (no fix)` | No fix in this stream yet (Affected / Fix deferred / Will not fix; with `--include-unfixed`) |
| `Unknown` | The fixing release could not be determined (e.g. `Fixed (see adv.)`), or under investigation |

The data is still fetched for the whole stream (4.21). "VULNERABLE" means the fix came after your release;
Red Hat does not publish whether an individual earlier release actually shipped the vulnerable code.

### CVEs fixed in a specific release (`--fixed-in`)

List only the CVEs whose fix shipped in exactly that release (release notes style):

```bash
./get_vulnerabilities.sh --fixed-in 4.21.17               # table
./get_vulnerabilities.sh --fixed-in 4.21.17 csv important
./get_vulnerabilities.py --fixed-in 4.21.17 --format json
```

```
════════════════════════════════════════════════════════════════════════════════════════════════════
OpenShift 4.21.17 - CVEs fixed in this release
════════════════════════════════════════════════════════════════════════════════════════════════════

CVE ID           Severity   First Fixed  Fixed In / Status    Advisory         Date        Description
---------------------------------------------------------------------------------------------------------------------------------------------------------
CVE-2026-46300   IMPORTANT  4.21.17      4.21.17              RHBA-2026:20032  2026-05-13  kernel: "Fragnesia" is a variant of Dirty Frag vulnerability
CVE-2026-41674   IMPORTANT  4.21.17      4.21.17              RHSA-2026:20034  2026-05-07  xmldom: xmldom: Arbitrary XML markup injection
CVE-2026-35469   IMPORTANT  4.21.16      4.21.17              RHSA-2026:20034  2026-04-13  Kubelet: CRI-O: kube-apiserver: Kubelet, CRI-O, kube-apiserv
CVE-2026-33186   IMPORTANT  4.21.10      4.21.17              RHSA-2026:20034  2026-03-20  google.golang.org/grpc/grpc-go: google.golang.org/grpc/authz
...
Total: 7 vulnerabilities found
Fix status: Fixed: 7
First fixed in 4.21.17: 3, fixed earlier with more components fixed in 4.21.17: 4
```

Red Hat often fixes a CVE component by component over several releases, so a CVE is listed if **any** of its
fixes shipped in that release. **First Fixed** shows when the stream first got a fix (`first_fixed_in` in CSV/JSON,
empty when it is this release); JSON also has `fix_releases`, the full list of releases/advisories.
Advisories whose release cannot be determined (a few old ones) cannot be matched; a note on stderr gives the count.

### Filter by Severity

```bash
# Show only important vulnerabilities (bash)
./get_vulnerabilities.sh 4.21 table important

# Show only important vulnerabilities in CSV
./get_vulnerabilities.sh 4.21 csv important

# Python version with severity filter
./get_vulnerabilities.py 4.21 --severity important
```

### Examples

```bash
# Table format (default)
./get_vulnerabilities.sh 4.21

# CSV export for spreadsheets
./get_vulnerabilities.sh 4.21 csv > vulns_4.21.csv

# JSON for programmatic processing
./get_vulnerabilities.sh 4.21 json > vulns_4.21.json

# Statistics summary
./get_vulnerabilities.py 4.21 --format stats

# Export important vulnerabilities to CSV
./get_vulnerabilities.sh 4.21 csv important > important_vulns.csv

# Python with all options
./get_vulnerabilities.py 4.21 --severity important --format csv --output report.csv

# Advanced bash script (fastest)
./get_vulnerabilities_advanced.sh 4.21 csv > report.csv
```

## Output Formats

### Table Format (Default - with fixed release / fix status)
```
════════════════════════════════════════════════════════════════════════════════════════════════════
OpenShift 4.12 - Vulnerabilities Report
════════════════════════════════════════════════════════════════════════════════════════════════════

CVE ID           Severity   Fixed In / Status    Advisory         Date        Description
--------------------------------------------------------------------------------------------------------------------------------------------
CVE-2026-43037   CRITICAL   4.12.92              RHSA-2026:26528  2026-05-01  kernel: ip6_tunnel: clear skb2->cb[] in ip4ip6_err()
CVE-2023-49569   CRITICAL   4.12.50              RHSA-2024:0832   2024-01-09  go-git: Maliciously crafted Git server replies can lead to p
CVE-2021-4235    MODERATE   4.12.0               RHSA-2022:7398   2022-12-27  go-yaml: Denial of Service in go-yaml
CVE-2023-0229    MODERATE   Fixed (see adv.)     RHBA-2023:1037   2023-01-12  openshift/apiserver-library-go: Bypass of SCC seccomp profil
CVE-2026-75887   IMPORTANT  Affected                              2026-09-23  openshift/console: openshift/console: Unauthenticated path t
CVE-2026-89713   IMPORTANT  Fix deferred                          2026-09-11  kernel: NFSD: check truncate permission under inode lock

Total: 2479 vulnerabilities found
Fix status: Fix deferred: 1121, Affected: 722, Will not fix: 307, Fixed: 253, Under investigation: 39, Out of support scope: 37
```
(excerpt of `./get_vulnerabilities.py 4.12 --include-unfixed`; without it only the 253 fixed CVEs are listed)

**Fixed In / Status**, per CVE, for the requested version:

| Value | Meaning |
|-------|---------|
| `4.12.92` | Earliest 4.12 release containing the fix; **Advisory** is the errata that shipped it |
| `Fixed (see adv.)` | Fixed, but the release could not be derived from the advisory (a few old/non-release errata) |
| `Affected`, `Fix deferred`, `Under investigation`, `Will not fix`, `Out of support scope` | Not fixed in this version: Red Hat's status (only with `--include-unfixed`) |
| `No fix listed` / `Lookup failed` | No fix or status published / the per-CVE API call failed |

How it is computed: the CVE's `affected_release` entries for this stream give the advisory, and the
advisory's CSAF document (or errata page) gives the release, e.g. `RHSA-2026:54206` → `4.12.96`.

> **Important:** the product query for a version (e.g. 4.12) only returns CVEs Red Hat has **already fixed** in it.
> To also see CVEs that are **not fixed**, add `--include-unfixed`: it checks the ~4000 CVEs filed against the generic
> "OpenShift Container Platform 4" product (takes 2-3 minutes). Red Hat publishes that status for "OCP 4" as a whole,
> not per minor version, so some of those rows concern components the version you asked for may not ship.

### CSV Format
```csv
CVE,severity,public_date,fix_status,fixed_in,fix_advisory,bugzilla,description,advisories
CVE-2026-43037,critical,2026-05-01T00:00:00Z,Fixed,4.12.92,RHSA-2026:26528,2464351,kernel: ip6_tunnel: clear skb2->cb[] in ip4ip6_err(),RHSA-2026:28741;...
```

### JSON Format
```json
{
  "version": "4.21",
  "count": 27,
  "vulnerabilities": [
    {
      "CVE": "CVE-2026-46300",
      "severity": "important",
      "public_date": "2026-05-13T12:00:00Z",
      "advisories": ["RHSA-2026:21695", "..."],
      "bugzilla": "2477015",
      "bugzilla_description": "kernel: ...",
      "resource_url": "https://access.redhat.com/hydra/rest/securitydata/cve/CVE-2026-46300.json"
    }
  ],
  "source": "Red Hat Security Advisory API"
}
```

### Statistics Format
```
============================================================
OpenShift 4.21 - Vulnerability Statistics
============================================================

Total Vulnerabilities: 27

By Severity:
  CRITICAL: 0
  IMPORTANT: 19
  MODERATE: 8
  LOW: 0
```

## Data Sources

The scripts fetch data from:
- **Red Hat Security Advisory API**: Official vulnerability database
- URL: `https://access.redhat.com/hydra/rest/securitydata/cve.json`
- Returns: Real-time CVE data for all OpenShift versions

## Script Comparison

| Feature | Bash (wraps Python) | Python | Advanced |
|---------|------|--------|----------|
| Table output | ✓ | ✓ | ✓ |
| CSV output | ✓ | ✓ | ✓ |
| JSON output | ✓ | ✓ | ✓ |
| Statistics | ✗ (use .py) | ✓ | ✗ |
| Severity filter | ✓ | ✓ | ✗ |
| Fixed release / fix status | ✓ | ✓ | ✗ |
| `--include-unfixed` | ✓ | ✓ | ✗ |
| Pagination (>1000 CVEs) | ✓ | ✓ | ✗ |
| Speed | ~15s (2-3 min unfixed) | ~15s (2-3 min unfixed) | ~1s |
| jq required | ✗ | ✗ | Optional |

## Version Format

- **X.Y** (e.g. `4.21`, `4.12`): list the CVEs of that stream, with the release that fixes each one
- **X.Y.Z** (e.g. `4.21.17`): same, plus whether each CVE is fixed in that exact release
- `--fixed-in X.Y.Z` (e.g. `--fixed-in 4.21.17`): only the CVEs fixed by that release

Not supported: `4.21.x` (wildcards) or 4-part versions.

## Requirements

- Bash 3.2+ (for bash scripts; macOS default bash works)
- Python 3.6+ (for Python script)
- `curl` (for API calls)
- Optional: `jq` (for advanced bash script, has fallback)

## Exit Codes

- `0`: Successful execution
- `1`: Invalid arguments, or the Red Hat API could not be reached / returned invalid data

## Common Tasks

### List vulnerabilities for a single version
```bash
./get_vulnerabilities.sh 4.21
```

### Export to CSV for compliance reports
```bash
./get_vulnerabilities.sh 4.21 csv > vulnerability_report_$(date +%Y%m%d).csv
```

### Check multiple versions
```bash
for version in 4.19 4.20 4.21; do
    echo "=== OpenShift $version ==="
    ./get_vulnerabilities.py $version --format stats
done
```

### Monitor only critical vulnerabilities
```bash
CRITICAL=$(./get_vulnerabilities.sh 4.21 | grep CRITICAL | wc -l)
echo "Critical vulnerabilities: $CRITICAL"
```

### Export for vulnerability management system
```bash
./get_vulnerabilities.sh 4.21 json | curl -X POST http://vuln-mgmt.local/api/import -d @-
```

## Production Usage

### Scheduling daily scans
```bash
# Add to crontab
0 2 * * * /path/to/vulns/get_vulnerabilities.sh 4.21 csv > /reports/vulns_$(date +\%Y\%m\%d).csv
```

### Integrating with monitoring
```bash
#!/bin/bash
COUNT=$(./get_vulnerabilities.py 4.21 --format json | jq '.count')
if [ "$COUNT" -gt 20 ]; then
    # Send alert
    mail -s "High vulnerability count" admin@example.com
fi
```

### Kubernetes CronJob
```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: ocp-vuln-scanner
spec:
  schedule: "0 2 * * *"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: scanner
            image: quay.io/my-org/ocp-scanner:latest
            command:
            - /bin/bash
            - -c
            - |
              ./get_vulnerabilities.sh 4.21 csv > /reports/vulns_$(date +%Y%m%d).csv
```

## Supported OpenShift Versions

The scripts work with any OpenShift version available in Red Hat Security API:
- 4.1 through 4.21+ (as of last update)
- Enterprise versions (3.11, etc.) - check Red Hat docs

## Support

For more information:
- Red Hat Security: https://access.redhat.com/security/
- OpenShift Docs: https://docs.openshift.com/
- CVE Database: https://cve.mitre.org/
