#!/usr/bin/env python3

"""
OpenShift Vulnerability Scanner - Python Version
Query vulnerabilities affecting specific OpenShift versions using Red Hat Security API
"""

import argparse
import json
import os
import re
import sys
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Dict, Optional, Tuple

OCP_PRODUCT = "Red Hat OpenShift Container Platform"
CSAF_ADVISORY_BASE = "https://security.access.redhat.com/data/csaf/v2/advisories"
ERRATA_BASE = "https://access.redhat.com/errata"

# When a CVE has no fix in the stream, the most actionable package state wins
FIX_STATE_PRIORITY = ['Affected', 'Fix deferred', 'Under investigation', 'Will not fix',
                      'Out of support scope', 'Not affected']


class FetchError(Exception):
    """Raised when the Red Hat API cannot be reached or returns invalid data"""


class VulnerabilityScanner:
    """Vulnerability scanner using Red Hat Security API"""

    def __init__(self):
        self.api_base = "https://access.redhat.com/hydra/rest/securitydata/cve.json"
        self.cve_detail_base = "https://access.redhat.com/hydra/rest/securitydata/cve"
        self.cve_cache = {}  # Cache CVE details to avoid duplicate API calls
        self.release_cache = {}  # (advisory, stream) -> OCP release (e.g. 4.12.96) or None
        self.per_page = 1000

    def validate_version(self, version: str) -> bool:
        """Validate version format (e.g., 4.21, 4.12)"""
        parts = version.split('.')
        if len(parts) != 2:
            return False
        return all(part.isdigit() for part in parts)

    def fetch_text(self, url: str, attempts: int = 3, connect_timeout: int = 10, max_time: int = 30,
                   byte_range: Optional[str] = None) -> str:
        """Fetch a URL with curl (urllib gets 403 errors), retrying on failure.
        Raises FetchError instead of returning empty data, so an API outage
        is never reported as "no vulnerabilities"."""
        cmd = ['curl', '-sS', '-f', '--connect-timeout', str(connect_timeout), '--max-time', str(max_time)]
        if byte_range:
            cmd += ['-r', byte_range]
        error = ""
        for attempt in range(attempts):
            if attempt:
                time.sleep(2 ** (attempt - 1))
            try:
                result = subprocess.run(cmd + [url], capture_output=True, text=True, timeout=max_time + 5)
            except subprocess.TimeoutExpired:
                error = "timeout"
                continue
            if result.returncode == 0:
                return result.stdout
            error = result.stderr.strip()
            if 'error: 404' in error:  # not transient, don't retry
                break
        raise FetchError(f"{url}: {error}")

    def fetch_json(self, url: str, **kwargs):
        """Fetch and parse JSON (see fetch_text)"""
        text = self.fetch_text(url, **kwargs)
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise FetchError(f"{url}: invalid JSON response: {e}")

    def fetch_vulnerabilities(self, version: str) -> List[Dict]:
        """Fetch all vulnerabilities for a version from Red Hat API (all pages)"""
        print(f"[*] Fetching vulnerabilities for OpenShift {version}...", file=sys.stderr)
        product = f"{OCP_PRODUCT} {version}".replace(' ', '%20')
        vulns = []
        page = 1
        while True:
            url = f"{self.api_base}?product={product}&per_page={self.per_page}&page={page}"
            data = self.fetch_json(url)
            if isinstance(data, dict):
                data = data.get('data', [])
            if not isinstance(data, list):
                raise FetchError(f"{url}: unexpected response type {type(data).__name__}")
            vulns.extend(data)
            if len(data) < self.per_page:
                return vulns
            page += 1

    def find_unfixed(self, version: str, exclude: set, keep) -> List[Dict]:
        """The product query for a stream (e.g. 4.12) only returns CVEs Red Hat has fixed in it.
        Unfixed CVEs are filed against the generic 'OCP <major>' product: fetch those, keep the ones
        with no fix in this stream and a status other than 'Not affected' (Affected, Fix deferred,
        Will not fix, ...). Note the generic status is not specific to the minor version."""
        major = version.split('.')[0]
        candidates = [v for v in self.fetch_vulnerabilities(major) if v.get('CVE') not in exclude and keep(v)]
        print(f"[*] Checking {len(candidates)} other OpenShift {major} CVEs for unfixed status "
              "(this can take a few minutes)...", file=sys.stderr)
        self.add_fix_info(candidates, version)
        failed = sum(1 for v in candidates if v['fix_status'] == 'Lookup failed')
        if failed:
            print(f"[!] Warning: fix status lookup failed for {failed} CVEs; they are not listed", file=sys.stderr)
        return [v for v in candidates if v['fix_status'] not in ('Not affected', 'No fix listed', 'Lookup failed')]

    def sort_vulnerabilities(self, vulns: List[Dict]) -> List[Dict]:
        """Sort vulnerabilities by severity"""
        severity_order = {'critical': 0, 'important': 1, 'moderate': 2, 'low': 3}
        return sorted(vulns, key=lambda x: severity_order.get((x.get('severity') or 'low').lower(), 4))

    def get_cve_details_cached(self, cve_id: str) -> Optional[Dict]:
        """Fetch CVE details with caching to avoid duplicate API calls"""
        if cve_id not in self.cve_cache:
            try:
                self.cve_cache[cve_id] = self.fetch_json(
                    f"{self.cve_detail_base}/{cve_id}.json", attempts=2, connect_timeout=5, max_time=15)
            except FetchError:
                self.cve_cache[cve_id] = None
        return self.cve_cache[cve_id]

    def _advisory_key(self, advisory: str):
        """Sort key for advisory IDs like RHSA-2026:54206 (year, number)"""
        try:
            year, number = advisory.split('-', 1)[1].split(':')
            return (int(year), int(number))
        except (IndexError, ValueError):
            return (9999, 0)

    def _version_key(self, version: str):
        """Sort key for dotted versions like 4.12.96"""
        return tuple(int(part) for part in version.split('.'))

    def _product_matches(self, product_name: str, version: str) -> bool:
        """True if the product is OCP <version> or a variant of it, e.g.
        'Ironic content for Red Hat OpenShift Container Platform 4.12' (but not 4.120)"""
        return re.search(rf'OpenShift Container Platform {re.escape(version)}(?![\d.])', product_name or '') is not None

    def resolve_release(self, advisory: str, stream: str) -> Optional[str]:
        """Map an advisory to the OCP z-stream release that shipped it (e.g. RHSA-2026:54206 -> 4.12.96),
        using the Red Hat CSAF advisory (first 8 KB only: the release is in the summary), falling back
        to the errata page for advisories missing from the CSAF feed (e.g. 4.12.0 GA).
        Returns None if neither names a release for this stream."""
        key = (advisory, stream)
        if key in self.release_cache:
            return self.release_cache[key]
        pattern = re.compile(rf'OpenShift Container Platform (?:release )?({re.escape(stream)}\.\d+)')
        release = None
        try:
            year = advisory.split('-', 1)[1].split(':')[0]
            name = advisory.lower().replace(':', '_')
            sources = [(f"{CSAF_ADVISORY_BASE}/{year}/{name}.json", '0-8191'),
                       (f"{ERRATA_BASE}/{advisory}", '0-65535')]
        except IndexError:
            sources = []
        for url, byte_range in sources:
            try:
                text = self.fetch_text(url, attempts=2, connect_timeout=5, max_time=15, byte_range=byte_range)
            except FetchError:
                continue
            match = pattern.search(text)
            if match:
                release = match.group(1)
                break
        self.release_cache[key] = release
        return release

    def get_fix_info(self, cve_id: str, version: str) -> Dict[str, str]:
        """Fix information for one CVE in the target OCP stream:
          fix_status   - 'Fixed', or Red Hat's state when unfixed (Affected, Will not fix, ...),
                         'No fix listed' when Red Hat gives no status, 'Lookup failed' on API errors
          fixed_in     - earliest OCP release containing the fix (e.g. 4.12.96), '' if unknown
          fix_advisory - advisory delivering that fix"""
        cve_data = self.get_cve_details_cached(cve_id)
        if cve_data is None:
            return {'fix_status': 'Lookup failed', 'fixed_in': '', 'fix_advisory': ''}

        advisories = sorted({
            r.get('advisory') for r in cve_data.get('affected_release') or []
            if self._product_matches(r.get('product_name'), version) and r.get('advisory')
        }, key=self._advisory_key)

        if advisories:
            releases = [(self.resolve_release(a, version), a) for a in advisories]
            resolved = [(rel, a) for rel, a in releases if rel]
            if resolved:
                fixed_in, advisory = min(resolved, key=lambda ra: self._version_key(ra[0]))
            else:
                fixed_in, advisory = '', advisories[0]
            return {'fix_status': 'Fixed', 'fixed_in': fixed_in, 'fix_advisory': advisory}

        # Not fixed in this stream: use the package states for this stream or the generic "OCP 4" product
        major = version.split('.')[0]
        states = {
            p.get('fix_state') for p in cve_data.get('package_state') or []
            if self._product_matches(p.get('product_name'), version)
            or self._product_matches(p.get('product_name'), major)
        }
        status = next((s for s in FIX_STATE_PRIORITY if s in states), None)
        if status is None and states - {None}:
            status = sorted(states - {None})[0]
        return {'fix_status': status or 'No fix listed', 'fixed_in': '', 'fix_advisory': ''}

    def add_fix_info(self, vulns: List[Dict], version: str, workers: int = 8):
        """Add fix_status / fixed_in / fix_advisory to each vulnerability (parallel lookups)"""
        if not vulns:
            return
        print(f"[*] Fetching fix status for {len(vulns)} CVEs...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            infos = list(pool.map(lambda v: self.get_fix_info(v.get('CVE', ''), version), vulns))
        for vuln, info in zip(vulns, infos):
            vuln.update(info)

    def _fix_display(self, vuln: Dict) -> Tuple[str, str]:
        """(Fixed In / Status, Advisory) cells for the table"""
        status = vuln.get('fix_status', '')
        if status == 'Fixed':
            return (vuln.get('fixed_in') or 'Fixed (see adv.)', vuln.get('fix_advisory', ''))
        return (status, '')

    def format_table(self, vulns: List[Dict], version: str) -> str:
        """Format as human-readable table with fix release / status for the target stream"""
        output = []
        output.append("")
        output.append("═" * 100)
        output.append(f"OpenShift {version} - Vulnerabilities Report")
        output.append("═" * 100)
        output.append("")

        if not vulns:
            output.append("No vulnerabilities found for the specified criteria.")
            output.append("")
            return "\n".join(output)

        output.append(f"{'CVE ID':<16} {'Severity':<10} {'Fixed In / Status':<20} {'Advisory':<16} {'Date':<11} {'Description'}")
        output.append("-" * 140)

        # Rows
        for vuln in vulns:
            cve = vuln.get('CVE', 'N/A')
            severity = (vuln.get('severity') or 'N/A').upper()
            date = (vuln.get('public_date') or 'N/A')[:10]  # Truncate to just date
            description = (vuln.get('bugzilla_description') or '')[:60]
            fixed_in, advisory = self._fix_display(vuln)

            output.append(f"{cve:<16} {severity:<10} {fixed_in:<20} {advisory:<16} {date:<11} {description}")

        output.append("")
        output.append(f"Total: {len(vulns)} vulnerabilities found")
        if any('fix_status' in v for v in vulns):
            counts = {}
            for vuln in vulns:
                counts[vuln['fix_status']] = counts.get(vuln['fix_status'], 0) + 1
            output.append("Fix status: " + ", ".join(f"{s}: {n}" for s, n in sorted(counts.items(), key=lambda x: -x[1])))
        output.append("")

        return "\n".join(output)

    def format_csv(self, vulns: List[Dict]) -> str:
        """Format as CSV"""
        import csv
        import io

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['CVE', 'severity', 'public_date', 'fix_status', 'fixed_in',
                                                    'fix_advisory', 'bugzilla', 'description', 'advisories'])
        writer.writeheader()

        for vuln in vulns:
            writer.writerow({
                'CVE': vuln.get('CVE', ''),
                'severity': (vuln.get('severity') or ''),
                'public_date': vuln.get('public_date', ''),
                'fix_status': vuln.get('fix_status', ''),
                'fixed_in': vuln.get('fixed_in', ''),
                'fix_advisory': vuln.get('fix_advisory', ''),
                'bugzilla': vuln.get('bugzilla', ''),
                'description': vuln.get('bugzilla_description', ''),
                'advisories': ';'.join(vuln.get('advisories') or [])
            })

        return output.getvalue()

    def format_json(self, vulns: List[Dict], version: str) -> str:
        """Format as JSON"""
        data = {
            "version": version,
            "count": len(vulns),
            "vulnerabilities": vulns,
            "generated": datetime.now().isoformat(),
            "source": "Red Hat Security Advisory API"
        }
        return json.dumps(data, indent=2)

    def format_stats(self, vulns: List[Dict], version: str) -> str:
        """Generate statistics summary"""
        output = []
        output.append("")
        output.append("=" * 60)
        output.append(f"OpenShift {version} - Vulnerability Statistics")
        output.append("=" * 60)
        output.append("")
        output.append(f"Total Vulnerabilities: {len(vulns)}\n")

        if vulns:
            severity_counts = {}
            for vuln in vulns:
                severity = (vuln.get('severity') or 'unknown').lower()
                severity_counts[severity] = severity_counts.get(severity, 0) + 1

            output.append("By Severity:")
            for severity in ['critical', 'important', 'moderate', 'low']:
                count = severity_counts.get(severity, 0)
                output.append(f"  {severity.upper()}: {count}")

            if any('fix_status' in v for v in vulns):
                status_counts = {}
                for vuln in vulns:
                    status = vuln.get('fix_status', 'Unknown')
                    status_counts[status] = status_counts.get(status, 0) + 1
                output.append("")
                output.append("By Fix Status:")
                for status, count in sorted(status_counts.items(), key=lambda x: -x[1]):
                    output.append(f"  {status}: {count}")

        output.append("")
        return "\n".join(output)

    def fetch_cve_details(self, cve_id: str) -> Dict:
        """Fetch details for a specific CVE from Red Hat API"""
        print(f"[*] Fetching details for {cve_id}...", file=sys.stderr)
        return self.fetch_json(f"{self.cve_detail_base}/{cve_id}.json")

    def format_cve_details(self, cve_data: Dict) -> str:
        """Format CVE details showing fix status for OpenShift"""
        output = []
        output.append("")
        output.append("═" * 80)
        output.append(f"CVE Details: {cve_data.get('name', 'Unknown')}")
        output.append("═" * 80)
        output.append("")

        # Basic info
        output.append(f"Severity: {cve_data.get('threat_severity', 'Unknown')}")
        output.append(f"Published: {cve_data.get('public_date', 'Unknown')}")
        cvss3 = cve_data.get('cvss3') or {}
        if cvss3.get('cvss3_base_score'):
            output.append(f"CVSS3 Score: {cvss3.get('cvss3_base_score')}")
        if cvss3.get('cvss3_scoring_vector'):
            output.append(f"CVSS3 Vector: {cvss3.get('cvss3_scoring_vector')}")
        output.append("")

        # Affected releases (fixed in): OCP streams resolved to their z-stream release
        affected_releases = cve_data.get('affected_release') or []
        stream_advisories = {}
        other_releases = []
        for release in affected_releases:
            product = release.get('product_name', '')
            match = re.search(r'OpenShift Container Platform (\d+\.\d+)(?![\d.])', product)
            if match and release.get('advisory'):
                stream_advisories.setdefault(match.group(1), set()).add(release['advisory'])
            elif 'OpenShift' in product:
                other_releases.append(release)

        if stream_advisories:
            pairs = [(s, a) for s, advs in stream_advisories.items() for a in advs]
            with ThreadPoolExecutor(max_workers=8) as pool:
                releases = dict(zip(pairs, pool.map(lambda sa: self.resolve_release(sa[1], sa[0]), pairs)))
            output.append("Fixed in OpenShift Container Platform:")
            output.append("-" * 80)
            output.append(f"  {'Stream':<8} {'Fixed In':<12} {'Advisory'}")
            for stream in sorted(stream_advisories, key=self._version_key):
                advisories = sorted(stream_advisories[stream], key=self._advisory_key)
                resolved = [(releases[(stream, a)], a) for a in advisories if releases[(stream, a)]]
                if resolved:
                    fixed_in, advisory = min(resolved, key=lambda ra: self._version_key(ra[0]))
                else:
                    fixed_in, advisory = '-', advisories[0]
                output.append(f"  {stream:<8} {fixed_in:<12} {advisory}")
            output.append("")

        if other_releases:
            output.append("Fixed in other OpenShift products:")
            output.append("-" * 80)
            for release in other_releases:
                product = release.get('product_name', 'N/A')
                advisory = release.get('advisory', 'N/A')
                package = release.get('package', 'N/A')
                output.append(f"  Product: {product}")
                output.append(f"    Advisory: {advisory}")
                output.append(f"    Package: {package}")
                output.append("")

        # Not fixed status
        package_states = cve_data.get('package_state') or []
        ocp_states = [p for p in package_states if 'OpenShift' in p.get('product_name', '')]

        if ocp_states:
            output.append("Status by OpenShift version:")
            output.append("-" * 80)
            for state in ocp_states:
                product = state.get('product_name', 'N/A')
                fix_state = state.get('fix_state', 'Unknown')
                output.append(f"  {product}: {fix_state}")
            output.append("")

        # Description
        if cve_data.get('details'):
            output.append("Description:")
            output.append("-" * 80)
            for detail in cve_data.get('details', []):
                output.append(f"  {detail}")
            output.append("")

        return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description='OpenShift Vulnerability Scanner',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s 4.21                          # List all vulnerabilities
  %(prog)s 4.12 --severity critical      # List critical vulnerabilities only
  %(prog)s 4.12 --format csv             # Export as CSV
  %(prog)s 4.12 --format json            # Export as JSON
  %(prog)s 4.12 --format stats           # Show statistics
  %(prog)s 4.12 --format csv --no-fix    # Skip fix lookups (faster)
  %(prog)s 4.12 --include-unfixed        # Also list CVEs not fixed in 4.12 (slow)
  %(prog)s --cve CVE-2025-1234           # Show fix status for a specific CVE
        '''
    )

    parser.add_argument('version', nargs='?', default=None, help='OpenShift version (e.g., 4.21, 4.12)')
    parser.add_argument(
        '--cve',
        help='Lookup details for a specific CVE (e.g., CVE-2025-1234)'
    )
    parser.add_argument(
        '--format', '-f',
        choices=['table', 'csv', 'json', 'stats'],
        default='table',
        help='Output format (default: table)'
    )
    parser.add_argument(
        '--severity', '-s',
        choices=['critical', 'important', 'moderate', 'low'],
        help='Filter by severity level'
    )
    parser.add_argument(
        '--output', '-o',
        type=argparse.FileType('w'),
        default=sys.stdout,
        help='Output file (default: stdout)'
    )
    parser.add_argument(
        '--advisory-prefix',
        help='Comma-separated advisory prefixes to include (e.g., RHSA,RHBA)'
    )
    parser.add_argument(
        '--no-fix',
        action='store_true',
        help='Skip the per-CVE fix lookups (faster; fix columns stay empty)'
    )
    parser.add_argument(
        '--include-unfixed',
        action='store_true',
        help='Also list CVEs NOT fixed in this version (Affected, Fix deferred, Will not fix, ...). '
             'Checks ~4000 OpenShift 4 CVEs, takes a few minutes'
    )

    args = parser.parse_args()

    # Handle CVE detail lookup mode
    if args.cve:
        scanner = VulnerabilityScanner()
        try:
            cve_data = scanner.fetch_cve_details(args.cve)
        except FetchError as e:
            print(f"[!] Could not fetch CVE details: {e}", file=sys.stderr)
            sys.exit(1)
        args.output.write(scanner.format_cve_details(cve_data))
        print(f"[*] CVE lookup complete", file=sys.stderr)
        sys.exit(0)

    # Handle version-based vulnerability listing mode
    if not args.version:
        parser.print_help()
        sys.exit(1)

    # Validate version
    scanner = VulnerabilityScanner()
    if not scanner.validate_version(args.version):
        print(f"Error: Invalid version format '{args.version}'", file=sys.stderr)
        print("Use format like: 4.21 or 4.12", file=sys.stderr)
        sys.exit(1)

    # Fetch vulnerabilities
    try:
        vulns = scanner.fetch_vulnerabilities(args.version)
    except FetchError as e:
        print(f"[!] Failed to fetch vulnerabilities: {e}", file=sys.stderr)
        sys.exit(1)
    if not vulns:
        print(f"[!] Warning: the API returned no CVEs for OpenShift {args.version} "
              "- check that this version exists", file=sys.stderr)

    # Filter by severity and advisory prefixes (e.g., RHSA,RHBA)
    prefixes = tuple(p.strip().upper() for p in (args.advisory_prefix or '').split(',') if p.strip())

    def keep(v: Dict) -> bool:
        if args.severity and (v.get('severity') or '').lower() != args.severity:
            return False
        return not prefixes or any(a.upper().startswith(prefixes) for a in (v.get('advisories') or []))

    known_cves = {v.get('CVE') for v in vulns}
    vulns = [v for v in vulns if keep(v)]

    # Fixed-in release / fix status per CVE for the requested stream
    if (args.format != 'stats' or args.include_unfixed) and not args.no_fix:
        scanner.add_fix_info(vulns, args.version)

    # Optionally add CVEs not fixed in this stream (Affected, Fix deferred, Will not fix, ...)
    if args.include_unfixed:
        try:
            vulns += scanner.find_unfixed(args.version, known_cves, keep)
        except FetchError as e:
            print(f"[!] Failed to fetch unfixed vulnerabilities: {e}", file=sys.stderr)
            sys.exit(1)

    vulns = scanner.sort_vulnerabilities(vulns)

    # Format output
    if args.format == 'csv':
        output = scanner.format_csv(vulns)
    elif args.format == 'json':
        output = scanner.format_json(vulns, args.version) + "\n"
    elif args.format == 'stats':
        output = scanner.format_stats(vulns, args.version)
    else:  # table
        output = scanner.format_table(vulns, args.version)

    # Write output
    try:
        args.output.write(output)
        args.output.flush()
    except BrokenPipeError:  # e.g. piped into head: silence the final flush at exit
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        sys.exit(0)

    if args.format == 'table':
        print(f"[*] Report generation complete", file=sys.stderr)

    sys.exit(0)


if __name__ == '__main__':
    main()
