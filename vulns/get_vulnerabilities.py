#!/usr/bin/env python3

"""
OpenShift Vulnerability Scanner - Python Version
Query vulnerabilities affecting specific OpenShift versions using Red Hat Security API
"""

import argparse
import json
import sys
import subprocess
import re
from datetime import datetime
from typing import List, Dict, Optional

class VulnerabilityScanner:
    """Vulnerability scanner using Red Hat Security API"""
    
    def __init__(self):
        self.api_base = "https://access.redhat.com/hydra/rest/securitydata/cve.json"
        self.cve_detail_base = "https://access.redhat.com/hydra/rest/securitydata/cve"
        self.cve_cache = {}  # Cache CVE details to avoid duplicate API calls
    
    def validate_version(self, version: str) -> bool:
        """Validate version format (e.g., 4.21, 4.12)"""
        parts = version.split('.')
        if len(parts) != 2:
            return False
        return all(part.isdigit() for part in parts)
    
    def fetch_vulnerabilities(self, version: str) -> List[Dict]:
        """Fetch vulnerabilities from Red Hat API"""
        url = f"{self.api_base}?product=Red%20Hat%20OpenShift%20Container%20Platform%20{version}&per_page=1000"
        
        try:
            print(f"[*] Fetching vulnerabilities for OpenShift {version}...", file=sys.stderr)
            
            # Use curl instead of urllib to avoid 403 errors
            import subprocess
            result = subprocess.run(
                ['curl', '-s', '--connect-timeout', '10', url],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode != 0:
                print(f"[!] Curl error: {result.stderr}", file=sys.stderr)
                return []
            
            data = json.loads(result.stdout)
            
            # Handle both list and dict responses
            if isinstance(data, dict):
                return data.get('data', []) if 'data' in data else []
            elif isinstance(data, list):
                return data
            else:
                return []
        
        except json.JSONDecodeError:
            print(f"[!] Error parsing JSON response", file=sys.stderr)
            return []
        except Exception as e:
            print(f"[!] Unexpected error: {e}", file=sys.stderr)
            return []
    
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
        if cve_id in self.cve_cache:
            return self.cve_cache[cve_id]
        
        url = f"{self.cve_detail_base}/{cve_id}.json"
        
        try:
            result = subprocess.run(
                ['curl', '-s', '--connect-timeout', '5', url],
                capture_output=True,
                text=True,
                timeout=8
            )
            
            if result.returncode == 0:
                data = json.loads(result.stdout)
                self.cve_cache[cve_id] = data
                return data
        except:
            pass
        
        return None
    
    def _parse_version_from_text(self, text: str) -> Optional[str]:
        """Extract version-like token from text (e.g., 4.21 or 4.21.12)"""
        if not text:
            return None
        match = re.search(r'\b\d+(?:\.\d+){1,4}\b', text)
        return match.group(0) if match else None
    
    def _version_key(self, version: str):
        """Build comparable key for dotted numeric versions"""
        return tuple(int(part) for part in version.split('.'))
    
    def _extract_stream_patch_from_package(self, package: str, target_version: str) -> Optional[str]:
        """Extract target stream patch version from package string when present"""
        if not package:
            return None
        
        escaped_target = re.escape(target_version)
        # Match versions like 4.21.12, 4.21.9.6, 4.21.9.6.202605..., v4.21.12, etc.
        match = re.search(rf'\bv?({escaped_target}(?:\.\d+){{1,4}})\b', package)
        if match:
            version = match.group(1)
            parts = version.split('.')
            
            # Drop likely build timestamp suffixes (e.g., 202605110143)
            if len(parts) > 3 and len(parts[-1]) >= 6:
                parts = parts[:-1]
            
            # Keep at most x.y.z.w for concise display
            if len(parts) > 4:
                parts = parts[:4]
            
            return ".".join(parts)
        return None
    
    def extract_fixed_versions(self, cve_id: str, target_version: str) -> str:
        """Extract OpenShift Container Platform fixed version for target stream"""
        cve_data = self.get_cve_details_cached(cve_id)
        if not cve_data:
            return "N/A"
        
        # Get affected releases (where it's fixed)
        affected_releases = cve_data.get('affected_release', [])
        ocp_releases = [
            r for r in affected_releases
            if 'Red Hat OpenShift Container Platform' in r.get('product_name', '')
        ]
        
        if not ocp_releases:
            return "N/A"
        
        target_prefix = f"{target_version}."
        
        # Keep only matching stream releases first (e.g., 4.21 / 4.21.x)
        stream_releases = []
        for release in ocp_releases:
            product = release.get('product_name', '')
            product_version = self._parse_version_from_text(product)
            if not product_version:
                continue
            if product_version == target_version or product_version.startswith(target_prefix):
                stream_releases.append(release)
        
        if not stream_releases:
            return "N/A"
        
        candidate_releases = stream_releases
        
        # Prefer patch-level version from package metadata for the selected stream
        patch_versions = []
        for release in candidate_releases:
            package = release.get('package', '')
            patch_version = self._extract_stream_patch_from_package(package, target_version)
            if patch_version:
                patch_versions.append(patch_version)
        
        if patch_versions:
            try:
                patch_versions_sorted = sorted(set(patch_versions), key=self._version_key)
                return patch_versions_sorted[0]
            except:
                return sorted(set(patch_versions))[0]
        
        # Fall back to selected product versions
        product_versions = []
        for release in candidate_releases:
            product = release.get('product_name', '')
            product_version = self._parse_version_from_text(product)
            if product_version:
                product_versions.append(product_version)
        
        if not product_versions:
            return "N/A"
        
        # Sort versions numerically and return the earliest fix in selected set
        try:
            versions_sorted = sorted(set(product_versions), key=self._version_key)
            return versions_sorted[0]
        except:
            return ", ".join(sorted(set(product_versions)))[:30]
    
    def format_table(self, vulns: List[Dict], version: str) -> str:
        """Format as human-readable table with fixed version info"""
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
        
        # Header - with Fixed In column
        output.append(f"{'CVE ID':<15} {'Severity':<12} {'Fixed In':<10} {'Date':<12} {'Impact':<35}")
        output.append("-" * 100)
        
        # Rows
        for vuln in vulns:
            cve = vuln.get('CVE', 'N/A')
            severity = vuln.get('severity', 'N/A').upper()
            date = vuln.get('public_date', 'N/A')[:10]  # Truncate to just date
            impact = vuln.get('impact', 'N/A')[:33]
            
            # Fetch fixed version info
            fixed_in = self.extract_fixed_versions(cve, version)
            
            output.append(f"{cve:<15} {severity:<12} {fixed_in:<10} {date:<12} {impact:<35}")
        
        output.append("")
        output.append(f"Total: {len(vulns)} vulnerabilities found")
        output.append("")
        
        return "\n".join(output)
    
    def format_csv(self, vulns: List[Dict]) -> str:
        """Format as CSV"""
        import csv
        import io
        
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=['CVE', 'severity', 'public_date', 'bugzilla_id', 'impact'])
        writer.writeheader()
        
        for vuln in vulns:
            writer.writerow({
                'CVE': vuln.get('CVE', ''),
                'severity': vuln.get('severity', ''),
                'public_date': vuln.get('public_date', ''),
                'bugzilla_id': vuln.get('bugzilla_id', ''),
                'impact': vuln.get('impact', '')
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

    def fetch_cve_details(self, cve_id: str) -> Optional[Dict]:
        """Fetch details for a specific CVE from Red Hat API"""
        url = f"{self.cve_detail_base}/{cve_id}.json"
        
        try:
            print(f"[*] Fetching details for {cve_id}...", file=sys.stderr)
            
            result = subprocess.run(
                ['curl', '-s', '--connect-timeout', '10', url],
                capture_output=True,
                text=True,
                timeout=15
            )
            
            if result.returncode != 0:
                print(f"[!] Curl error: {result.stderr}", file=sys.stderr)
                return None
            
            data = json.loads(result.stdout)
            return data
        
        except json.JSONDecodeError:
            print(f"[!] Error parsing JSON response", file=sys.stderr)
            return None
        except Exception as e:
            print(f"[!] Unexpected error: {e}", file=sys.stderr)
            return None
    
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
        if cve_data.get('cvss3_scoring_vector'):
            output.append(f"CVSS Vector: {cve_data.get('cvss3_scoring_vector')}")
        output.append("")
        
        # Affected releases (fixed in)
        affected_releases = cve_data.get('affected_release', [])
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
        package_states = cve_data.get('package_state', [])
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
    
    args = parser.parse_args()
    
    # Handle CVE detail lookup mode
    if args.cve:
        scanner = VulnerabilityScanner()
        cve_data = scanner.fetch_cve_details(args.cve)
        if cve_data:
            output = scanner.format_cve_details(cve_data)
            args.output.write(output)
            print(f"[*] CVE lookup complete", file=sys.stderr)
        else:
            print(f"[!] Could not fetch CVE details", file=sys.stderr)
            sys.exit(1)
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
    vulns = scanner.fetch_vulnerabilities(args.version)
    
    # Filter and sort
    vulns = scanner.filter_vulnerabilities(vulns, args.severity)
    vulns = scanner.sort_vulnerabilities(vulns)
    
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
