# OpenShift Vulnerability Scanner - Summary

## What You've Got

A comprehensive vulnerability scanning solution with **three complementary tools** for querying **real vulnerabilities** affecting OpenShift versions using the official Red Hat Security API.

### 📁 Files in This Directory

```
vulns/
├── get_vulnerabilities.sh           # Bash wrapper (positional args) around the Python script
├── get_vulnerabilities_advanced.sh  # Quick jq-based CVE list (no fix info)
├── get_vulnerabilities.py           # All the logic: fixed release, fix status, stats
├── VULNERABILITIES_README.md        # Comprehensive documentation
├── QUICK_REFERENCE.md              # Quick reference guide & examples
└── SUMMARY.md                       # This file
```

---

## 🚀 Quick Start

### Option 1: Bash (Recommended for most users)
```bash
./get_vulnerabilities.sh 4.21
./get_vulnerabilities.sh 4.21 csv > report.csv
./get_vulnerabilities.sh --cve CVE-2026-46300    # Check if a CVE is fixed
```

### Option 2: Python (Rich CLI)
```bash
./get_vulnerabilities.py 4.21
./get_vulnerabilities.py 4.21 --severity important --format table
./get_vulnerabilities.py 4.21 --format stats
./get_vulnerabilities.py --cve CVE-2026-46300    # Check if a CVE is fixed
```

### Option 3: Advanced Bash (jq-based, fastest)
```bash
./get_vulnerabilities_advanced.sh 4.21
./get_vulnerabilities_advanced.sh 4.21 csv
```

---

## � CVE Details & Fix Status (NEW!)

Check if a specific CVE is fixed in which OpenShift versions:

```bash
./get_vulnerabilities.py --cve CVE-2026-46300
# or
./get_vulnerabilities.sh --cve CVE-2026-46300
```

Shows:
- ✅ The release that fixes it in each OpenShift version (with advisories)
- ✅ Which versions are still vulnerable
- ✅ CVE severity and publication date
- ✅ Full vulnerability description

Example output:
```
Fixed in OpenShift Container Platform:
--------------------------------------------------------------------------------
  Stream   Fixed In     Advisory
  4.12     4.12.96      RHSA-2026:54206
  4.13     4.13.70      RHSA-2026:54188
  ...
  4.21     4.21.29      RHSA-2026:54602
  4.22     4.22.10      RHSA-2026:54770
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

---

## 📊 Data Source

✅ **Real Red Hat Security API** - Actual vulnerability data for OpenShift versions
- Uses: `https://access.redhat.com/hydra/rest/securitydata/cve.json`
- Returns: Current CVE data, severity levels, publication dates, and more

---

## 📖 Usage Examples

### List all vulnerabilities for a version
```bash
./get_vulnerabilities.py 4.21
```
Output: 27 vulnerabilities for OpenShift 4.21 (19 important, 8 moderate)

### Get only important/critical vulnerabilities
```bash
./get_vulnerabilities.py 4.21 --severity important
```

### Export to CSV for analysis
```bash
./get_vulnerabilities.sh 4.21 csv > vulnerabilities.csv
```

### Generate statistics
```bash
./get_vulnerabilities.py 4.21 --format stats
```

### Export to JSON for programmatic use
```bash
./get_vulnerabilities.sh 4.21 json > data.json
```

### Batch check multiple versions
```bash
for version in 4.20 4.21; do
    echo "=== OpenShift $version ==="
    ./get_vulnerabilities.py $version --format stats
done
```

---

## 🔧 Which Script to Use?

| Need | Recommended |
|------|-----|
| Quick check | `./get_vulnerabilities.py 4.21` |
| CSV export | `./get_vulnerabilities.sh 4.21 csv` |
| Statistics | `./get_vulnerabilities.py 4.21 --format stats` |
| Fixed release per CVE | `./get_vulnerabilities.sh 4.21 csv` |
| Include unfixed CVEs + status | `./get_vulnerabilities.py 4.21 --include-unfixed` |
| Fastest CVE list (no fix info) | `./get_vulnerabilities_advanced.sh 4.21` |
| Filtering by severity | `./get_vulnerabilities.py 4.21 --severity important` |
| JSON output | `./get_vulnerabilities.sh 4.21 json` |

---

## 📋 Output Formats

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
    {"CVE": "CVE-2026-46300", "severity": "important", ...}
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

---

## 🎯 Common Tasks

### Create a vulnerability report with timestamp
```bash
VERSION="4.21"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
./get_vulnerabilities.sh $VERSION csv > "vulns_${VERSION}_${TIMESTAMP}.csv"
```

### Monitor for new vulnerabilities
```bash
#!/bin/bash
VERSION=$1
CURRENT=$(./get_vulnerabilities.py "$VERSION" --format json | jq '.count')

if [ "$CURRENT" -gt 0 ]; then
    echo "Found $CURRENT vulnerabilities in OpenShift $VERSION"
fi
```

### Check only important vulnerabilities
```bash
./get_vulnerabilities.sh 4.21 table important
```

### Export for external tools
```bash
./get_vulnerabilities.py 4.21 --format json | curl -X POST http://dashboard.local/api/vulns -d @-
```

---

## 🔌 Integration Examples

### Jenkins Pipeline
```groovy
stage('Scan Vulnerabilities') {
    steps {
        sh './get_vulnerabilities.py ${OCP_VERSION} --format json > vulns.json'
        def vulns = readJSON file: 'vulns.json'
        if (vulns.count > 10) {
            unstable("Found ${vulns.count} vulnerabilities")
        }
    }
}
```

### Bash Script (Daily Report)
```bash
#!/bin/bash
REPORT_DIR="./vulnerability_reports"
mkdir -p "$REPORT_DIR"

for version in 4.19 4.20 4.21; do
    ./get_vulnerabilities.sh $version csv > \
        "$REPORT_DIR/vulns_${version}_$(date +%Y%m%d).csv"
done
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

---

## ✅ Tested & Working

✓ All scripts produce real output  
✓ Fetches from official Red Hat Security API  
✓ Multiple output formats (table, CSV, JSON, stats)  
✓ Severity filtering (critical, important, moderate, low)  
✓ Exits with code 1 (never an empty report) when the API is unreachable  
✓ Table/CSV/JSON ~15 seconds (fix lookups run in parallel); stats and `--no-fix` ~1-2 seconds; `--include-unfixed` 2-3 minutes  
✓ Works on macOS and Linux  

---

## 📞 Support

For more information:
- Red Hat Security: https://access.redhat.com/security/
- OpenShift Documentation: https://docs.openshift.com/
- CVE Database: https://cve.mitre.org/
