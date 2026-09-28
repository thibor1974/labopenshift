#!/usr/bin/env python3

"""
OpenShift Vulnerability Scanner - Python Version
Query vulnerabilities affecting specific OpenShift versions using Red Hat Security API
"""

import argparse
import json
import sys
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import List, Dict, Optional

OCP_PRODUCT = "Red Hat OpenShift Container Platform"


class FetchError(Exception):
    """Raised when the Red Hat API cannot be reached or returns invalid data"""


class VulnerabilityScanner:
    """Vulnerability scanner using Red Hat Security API"""

    def __init__(self):
        self.api_base = "https://access.redhat.com/hydra/rest/securitydata/cve.json"
        self.cve_detail_base = "https://access.redhat.com/hydra/rest/securitydata/cve"
        self.cve_cache = {}  # Cache CVE details to avoid duplicate API calls
        self.per_page = 1000

    def validate_version(self, version: str) -> bool:
        """Validate version format (e.g., 4.21, 4.12)"""
        parts = version.split('.')
        if len(parts) != 2:
            return False
        return all(part.isdigit() for part in parts)

    def fetch_json(self, url: str, attempts: int = 3, connect_timeout: int = 10, max_time: int = 30):
        """Fetch a URL with curl (urllib gets 403 errors), retrying on failure.
        Raises FetchError instead of returning empty data, so an API outage
        is never reported as "no vulnerabilities"."""
        error = ""
        for attempt in range(attempts):
            if attempt:
                time.sleep(2 ** (attempt - 1))
            try:
                result = subprocess.run(
                    ['curl', '-sS', '-f', '--connect-timeout', str(connect_timeout),
                     '--max-time', str(max_time), url],
                    capture_output=True,
                    text=True,
                    timeout=max_time + 5
                )
            except subprocess.TimeoutExpired:
                error = "timeout"
                continue
            if result.returncode != 0:
                error = result.stderr.strip()
                continue
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as e:
                error = f"invalid JSON response: {e}"
        raise FetchError(f"{url}: {error}")

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

    def filter_vulnerabilities(self, vulns: List[Dict], severity: Optional[str] = None) -> List[Dict]:
        """Filter vulnerabilities by severity"""
        if not severity:
            return vulns

        severity_lower = severity.lower()
        return [v for v in vulns if v.get('severity', '').lower() == severity_lower]

    def sort_vulnerabilities(self, vulns: List[Dict]) -> List[Dict]:
        """Sort vulnerabilities by severity"""
        severity_order = {'critical': 0, 'important': 1, 'moderate': 2, 'low': 3}
        return sorted(vulns, key=lambda x: severity_order.get(x.get('severity', 'low').lower(), 4))

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

    def extract_fix_advisory(self, cve_id: str, target_version: str) -> str:
        """Return the earliest advisory fixing the CVE in the target OCP stream.
        '-' means Red Hat lists no fix for this stream; '?' means the lookup failed."""
        cve_data = self.get_cve_details_cached(cve_id)
        if cve_data is None:
            return "?"

        product_name = f"{OCP_PRODUCT} {target_version}"
        advisories = {
            r.get('advisory') for r in cve_data.get('affected_release') or []
            if r.get('product_name') == product_name and r.get('advisory')
        }
        if not advisories:
            return "-"
        return min(advisories, key=self._advisory_key)

    def prefetch_cve_details(self, vulns: List[Dict], workers: int = 8):
        """Fetch CVE details in parallel to fill the cache"""
        cve_ids = [v.get('CVE') for v in vulns if v.get('CVE')]
        print(f"[*] Fetching fix status for {len(cve_ids)} CVEs...", file=sys.stderr)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(self.get_cve_details_cached, cve_ids))

    def format_table(self, vulns: List[Dict], version: str) -> str:
        """Format as human-readable table with fix advisory for the target stream"""
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

        self.prefetch_cve_details(vulns)

        fix_header = f"Fix ({version})"
        output.append(f"{'CVE ID':<16} {'Severity':<10} {fix_header:<17} {'Date':<11} {'Description'}")
        output.append("-" * 130)

        # Rows
        for vuln in vulns:
            cve = vuln.get('CVE', 'N/A')
            severity = vuln.get('severity', 'N/A').upper()
            date = (vuln.get('public_date') or 'N/A')[:10]  # Truncate to just date
            description = (vuln.get('bugzilla_description') or '')[:70]
            fix = self.extract_fix_advisory(cve, version)

            output.append(f"{cve:<16} {severity:<10} {fix:<17} {date:<11} {description}")

        output.append("")
        output.append(f"Total: {len(vulns)} vulnerabilities found")
        output.append(f"Fix ({version}): advisory fixing the CVE in this stream; "
                      "'-' = no fix listed, '?' = lookup failed")
        output.append("")

        return "\n".join(output)

    def format_csv(self, vulns: List[Dict]) -> str:
        """Format as CSV"""
        import csv
        import io

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['CVE', 'severity', 'public_date', 'bugzilla', 'description', 'advisories'])
        writer.writeheader()

        for vuln in vulns:
            writer.writerow({
                'CVE': vuln.get('CVE', ''),
                'severity': vuln.get('severity', ''),
                'public_date': vuln.get('public_date', ''),
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
                severity = vuln.get('severity', 'unknown').lower()
                severity_counts[severity] = severity_counts.get(severity, 0) + 1

            output.append("By Severity:")
            for severity in ['critical', 'important', 'moderate', 'low']:
                count = severity_counts.get(severity, 0)
                output.append(f"  {severity.upper()}: {count}")

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

        # Affected releases (fixed in)
        affected_releases = cve_data.get('affected_release') or []
        ocp_releases = [r for r in affected_releases if 'OpenShift' in r.get('product_name', '')]

        if ocp_releases:
            output.append("Fixed in OpenShift versions:")
            output.append("-" * 80)
            for release in ocp_releases:
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

    # Filter and sort
    vulns = scanner.filter_vulnerabilities(vulns, args.severity)
    vulns = scanner.sort_vulnerabilities(vulns)

    # Filter by advisory prefixes (e.g., RHSA,RHBA)
    if args.advisory_prefix:
        prefixes = tuple(p.strip().upper() for p in args.advisory_prefix.split(',') if p.strip())
        if prefixes:
            vulns = [
                v for v in vulns
                if any(a.upper().startswith(prefixes) for a in (v.get('advisories') or []))
            ]

    # Format output
    if args.format == 'csv':
        output = scanner.format_csv(vulns)
    elif args.format == 'json':
        output = scanner.format_json(vulns, args.version)
    elif args.format == 'stats':
        output = scanner.format_stats(vulns, args.version)
    else:  # table
        output = scanner.format_table(vulns, args.version)

    # Write output
    args.output.write(output)

    if args.format == 'table':
        print(f"[*] Report generation complete", file=sys.stderr)

    sys.exit(0)


if __name__ == '__main__':
    main()
