#!/usr/bin/env python3

"""
List the operators available for an OpenShift version (e.g. 4.21), and for each
operator channel the latest version (channel head) - what OperatorHub installs.
Uses the Red Hat Ecosystem Catalog API (Pyxis), which mirrors the content of the
operator index images (registry.redhat.io/redhat/redhat-operator-index:v4.21, ...).
"""

import argparse
import csv
import io
import json
import re
import subprocess
import sys
import time
from typing import Dict, List
from urllib.parse import quote

BUNDLES_API = "https://catalog.redhat.com/api/containers/v1/operators/bundles"
CATALOGS = ['redhat-operators', 'certified-operators', 'community-operators', 'redhat-marketplace']
FIELDS = ['package', 'channel_name', 'version', 'is_default_channel', 'csv_display_name',
          'creation_date', 'organization', 'latest_in_channel']
PAGE_SIZE = 500


class FetchError(Exception):
    """Raised when the catalog API cannot be reached or returns invalid data"""


def fetch_json(url: str, attempts: int = 3) -> Dict:
    """Fetch JSON with curl, retrying on failure"""
    cmd = ['curl', '-sS', '-f', '--connect-timeout', '10', '--max-time', '60',
           '-H', 'Accept: application/json', url]
    error = ""
    for attempt in range(attempts):
        if attempt:
            time.sleep(2 ** (attempt - 1))
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError as e:
                raise FetchError(f"{url}: invalid JSON response: {e}")
        error = result.stderr.strip()
    raise FetchError(f"{url}: {error}")


def natural_key(text: str):
    """stable-6.10 after stable-6.9"""
    return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', text)]


def version_key(version: str):
    """Natural sort: 1.10.0 > 1.9.2, 2.0.0 > 2.0.0-rc.1"""
    main, _, pre = version.partition('-')
    nums = tuple(int(n) if n.isdigit() else 0 for n in re.split(r'[.+]', main))
    return nums, 0 if pre else 1, pre


def fetch_bundles(ocp_version: str, catalog: str, all_versions: bool) -> List[Dict]:
    """All bundles of a catalog for an OCP version (only channel heads unless all_versions)"""
    query = f"ocp_version=={ocp_version};organization=={catalog};in_index_img==true"
    if not all_versions:
        query += ";latest_in_channel==true"
    include = ",".join(['total'] + [f"data.{f}" for f in FIELDS])
    bundles, page = [], 0
    while True:
        url = f"{BUNDLES_API}?filter={quote(query, safe='=;')}&page_size={PAGE_SIZE}&page={page}&include={include}"
        data = fetch_json(url)
        bundles += data.get('data', [])
        page += 1
        if page * PAGE_SIZE >= data.get('total', 0):
            return bundles


def collect(ocp_version: str, catalogs: List[str], all_versions: bool, package_filter: str,
            default_only: bool) -> List[Dict]:
    """Rows sorted by catalog, package, channel, version, deduplicated"""
    rows = {}
    newest_default = {}  # (catalog, package) -> (creation_date, channel)
    for catalog in catalogs:
        print(f"Fetching {catalog} for OpenShift {ocp_version}...", file=sys.stderr)
        for b in fetch_bundles(ocp_version, catalog, all_versions):
            if package_filter and package_filter.lower() not in (b['package'] + ' ' + (b.get('csv_display_name') or '')).lower():
                continue
            if b.get('is_default_channel'):
                # The flag is recorded when a bundle is published, so older bundles keep a stale
                # default: the default channel is the one of the newest bundle flagged default
                pkg_key = (catalog, b['package'])
                candidate = (b.get('creation_date') or '', b['channel_name'])
                newest_default[pkg_key] = max(newest_default.get(pkg_key, candidate), candidate)
            key = (catalog, b['package'], b['channel_name'], b['version'])
            rows[key] = {
                'catalog': catalog,
                'package': b['package'],
                'display_name': b.get('csv_display_name') or '',
                'channel': b['channel_name'],
                'default': False,
                'version': b['version'],
                'latest': bool(b.get('latest_in_channel')),
                'published': (b.get('creation_date') or '')[:10],
            }
    for r in rows.values():
        r['default'] = newest_default.get((r['catalog'], r['package']), ('', None))[1] == r['channel']
    result = [r for r in rows.values() if r['default'] or not default_only]
    return sorted(result, key=lambda r: (CATALOGS.index(r['catalog']), r['package'],
                                         natural_key(r['channel']), version_key(r['version'])))


def format_table(rows: List[Dict], ocp_version: str, all_versions: bool) -> str:
    packages = {(r['catalog'], r['package']) for r in rows}
    lines = [f"Operators for OpenShift {ocp_version}: {len(packages)} operators, "
             f"{len({(r['catalog'], r['package'], r['channel']) for r in rows})} channels", "=" * 110]
    pkg_w = max([len(r['package']) for r in rows] + [7]) + 2
    chan_w = max([len(r['channel']) for r in rows] + [7]) + 4
    ver_w = max([len(r['version']) for r in rows] + [7]) + (9 if all_versions else 2)
    current = None
    for r in rows:
        if r['catalog'] != (current or {}).get('catalog'):
            lines += ["", f"[{r['catalog']}]",
                      f"  {'Package':<{pkg_w}}{'Channel':<{chan_w}}{'Version':<{ver_w}}{'Published':<12}Name",
                      "  " + "-" * 108]
        same_pkg = current and current['catalog'] == r['catalog'] and current['package'] == r['package']
        channel = r['channel'] + (' *' if r['default'] else '')
        version = r['version'] + (' (head)' if all_versions and r['latest'] else '')
        lines.append(f"  {'' if same_pkg else r['package']:<{pkg_w}}{channel:<{chan_w}}{version:<{ver_w}}"
                     f"{r['published']:<12}{'' if same_pkg else r['display_name']}")
        current = r
    lines += ["", "  * default channel (installed when no channel is chosen)"]
    return "\n".join(lines)


def format_csv(rows: List[Dict]) -> str:
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=['catalog', 'package', 'display_name', 'channel', 'default',
                                             'version', 'latest', 'published'], lineterminator='\n')
    writer.writeheader()
    writer.writerows(rows)
    return out.getvalue().rstrip('\n')


def format_json(rows: List[Dict], ocp_version: str) -> str:
    """Nested: {catalog: {package: {display_name, default_channel, channels: {channel: [versions]}}}}"""
    tree = {}
    for r in rows:
        pkg = tree.setdefault(r['catalog'], {}).setdefault(
            r['package'], {'display_name': r['display_name'], 'default_channel': None, 'channels': {}})
        if r['default']:
            pkg['default_channel'] = r['channel']
        pkg['channels'].setdefault(r['channel'], []).append(r['version'])
    return json.dumps({'ocp_version': ocp_version, 'catalogs': tree}, indent=2)


def main():
    parser = argparse.ArgumentParser(
        description="List the operators available for an OpenShift version, with the latest version of each channel",
        epilog="Examples:\n"
               "  %(prog)s 4.21                              # redhat-operators catalog\n"
               "  %(prog)s 4.21 --package logging            # filter on package/display name\n"
               "  %(prog)s 4.21 --default-only               # only the default channel of each operator\n"
               "  %(prog)s 4.21 --all-versions -p cluster-logging   # every version of each channel\n"
               "  %(prog)s 4.21 --catalog certified-operators --catalog community-operators\n"
               "  %(prog)s 4.21 --catalog all --format csv > operators-4.21.csv",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('ocp_version', help="OpenShift version, e.g. 4.21 (or 4.21.17, only the stream is used)")
    parser.add_argument('--catalog', '-c', choices=CATALOGS + ['all'], action='append',
                        help="Operator catalog (repeatable). Default: redhat-operators")
    parser.add_argument('--package', '-p', default='', help="Only operators whose package or display name contains this text")
    parser.add_argument('--default-only', '-d', action='store_true', help="Only show the default channel of each operator")
    parser.add_argument('--all-versions', '-a', action='store_true',
                        help="List every version available in each channel, not only the channel head")
    parser.add_argument('--format', '-f', default='table', choices=['table', 'csv', 'json'],
                        help="Output format (default: table)")
    args = parser.parse_args()

    match = re.fullmatch(r'(\d+\.\d+)(\.\d+)?', args.ocp_version)
    if not match:
        parser.error(f"invalid OpenShift version '{args.ocp_version}', expected e.g. 4.21")
    ocp_version = match.group(1)  # operator catalogs are per stream
    if not args.catalog:
        catalogs = ['redhat-operators']
    elif 'all' in args.catalog:
        catalogs = CATALOGS
    else:
        catalogs = args.catalog

    try:
        rows = collect(ocp_version, catalogs, args.all_versions, args.package, args.default_only)
    except FetchError as e:
        print(f"Error: cannot query the Red Hat catalog API: {e}", file=sys.stderr)
        sys.exit(2)

    if not rows:
        print(f"No operators found for OpenShift {ocp_version} in: {', '.join(catalogs)}", file=sys.stderr)
        sys.exit(1)

    if args.format == 'json':
        print(format_json(rows, ocp_version))
    elif args.format == 'csv':
        print(format_csv(rows))
    else:
        print(format_table(rows, ocp_version, args.all_versions))


if __name__ == '__main__':
    main()
