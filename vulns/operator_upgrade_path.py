#!/usr/bin/env python3

"""
Show the OLM upgrade graph of an operator channel, and the upgrade path OLM follows
from an installed version to the channel head.

The graph comes from the operator index image itself (file-based catalog in /configs/<package>/),
extracted with `oc image extract`: the catalog API does not expose replaces/skips.
Edges follow OLM rules: an entry upgrades from the bundle it `replaces`, the bundles it `skips`,
and every version in its `skipRange`. When several entries can replace the installed one,
OLM picks the one closest to the channel head.
"""

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Dict, List, Optional, Tuple

INDEX_IMAGES = {
    'redhat-operators': 'registry.redhat.io/redhat/redhat-operator-index',
    'certified-operators': 'registry.redhat.io/redhat/certified-operator-index',
    'community-operators': 'registry.redhat.io/redhat/community-operator-index',
    'redhat-marketplace': 'registry.redhat.io/redhat/redhat-marketplace-index',
}


class CatalogError(Exception):
    """Raised when the catalog cannot be extracted or parsed"""


# --- semver (same semantics as blang/semver, used by OLM) ---------------------------------------

def parse_semver(version: str) -> Tuple:
    """'4.21.2-rhodf+build' -> ((4, 21, 2), prerelease identifiers); build metadata is ignored"""
    version = version.strip().lstrip('v').split('+', 1)[0]
    main, _, pre = version.partition('-')
    nums = [int(n) if n.isdigit() else 0 for n in main.split('.')[:3]]
    nums += [0] * (3 - len(nums))
    pre_ids = tuple((0, int(p), '') if p.isdigit() else (1, 0, p) for p in pre.split('.')) if pre else ()
    return tuple(nums), pre_ids


def semver_key(version: str):
    nums, pre = parse_semver(version)
    # A release sorts after all its prereleases: 1.0.0-rc.1 < 1.0.0
    return nums, 0 if pre else 1, pre


def in_range(version: str, skip_range: str) -> bool:
    """OLM skipRange: '>=4.3.0 <4.15.0' (space = AND), '||' = OR"""
    if not skip_range:
        return False
    v = semver_key(version)
    for alternative in skip_range.split('||'):
        ok = True
        for comparator in alternative.split():
            match = re.fullmatch(r'(>=|<=|>|<|==|=|!=|!)?(.+)', comparator)
            op, bound = match.group(1) or '=', semver_key(match.group(2))
            ok = {'>=': v >= bound, '<=': v <= bound, '>': v > bound, '<': v < bound,
                  '=': v == bound, '==': v == bound, '!=': v != bound, '!': v != bound}[op]
            if not ok:
                break
        if ok:
            return True
    return False


# --- catalog loading ------------------------------------------------------------------------------

def parse_documents(path: str) -> List[Dict]:
    """A file-based catalog file holds a stream of JSON or YAML documents"""
    text = open(path).read()
    if path.endswith('.json'):
        decoder, docs, i = json.JSONDecoder(), [], 0
        text = text.strip()
        while i < len(text):
            doc, i = decoder.raw_decode(text, i)
            docs.append(doc)
            while i < len(text) and text[i].isspace():
                i += 1
        return docs
    try:
        import yaml
        return [d for d in yaml.safe_load_all(text) if d]
    except ImportError:
        pass
    if shutil.which('yq'):
        result = subprocess.run(['yq', '-o=json', '-I=0', '.', path], capture_output=True, text=True)
        if result.returncode == 0:
            return [json.loads(line) for line in result.stdout.splitlines() if line.strip() not in ('', 'null')]
    raise CatalogError(f"{path}: YAML catalog, install PyYAML (pip install pyyaml) or yq")


def load_catalog_dir(directory: str) -> List[Dict]:
    docs = []
    for root, _, files in os.walk(directory):
        for name in sorted(files):
            if name.endswith(('.json', '.yaml', '.yml')):
                docs += parse_documents(os.path.join(root, name))
    return docs


def extract_package(image: str, package: str, registry_config: Optional[str]) -> List[Dict]:
    """Extract /configs/<package>/ from the index image (only the layers holding it are read)"""
    if not shutil.which('oc'):
        raise CatalogError("the 'oc' CLI is required to extract the catalog from the index image")
    with tempfile.TemporaryDirectory() as tmp:
        cmd = ['oc', 'image', 'extract', image, '--path', f'/configs/{package}/:{tmp}',
               '--filter-by-os', 'linux/amd64', '--confirm']
        if registry_config:
            cmd += ['--registry-config', registry_config]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            error = result.stderr.strip()
            if 'unauthorized' in error.lower() or 'authentication required' in error.lower():
                error += ("\nHint: log in with `podman login registry.redhat.io` (or `docker login`), "
                          "or pass --registry-config <pull-secret.json>")
            raise CatalogError(f"cannot extract {package} from {image}:\n{error}")
        docs = load_catalog_dir(tmp)
    if not docs:
        raise CatalogError(f"package '{package}' not found in {image} (no /configs/{package}/)")
    return docs


# --- graph ----------------------------------------------------------------------------------------

class Channel:
    def __init__(self, package: str, name: str, entries: List[Dict], versions: Dict[str, str]):
        self.package, self.name = package, name
        self.entries = {e['name']: e for e in entries}
        self.versions = versions  # bundle name -> version
        self.order = self._order()  # head first

    def version(self, bundle: str) -> str:
        if bundle in self.versions:
            return self.versions[bundle]
        match = re.search(r'\.v?(\d+\.\d+.*)$', bundle)  # pruned bundle: guess from the name
        return match.group(1) if match else bundle

    def _order(self) -> List[str]:
        """Channel entries head first: follow `replaces` from the head, then the rest by version"""
        replaced = {e.get('replaces') for e in self.entries.values()}
        skipped = {s for e in self.entries.values() for s in e.get('skips', [])}
        heads = [n for n in self.entries if n not in replaced and n not in skipped] or list(self.entries)
        head = max(heads, key=lambda n: semver_key(self.version(n)))
        order, current = [], head
        while current in self.entries and current not in order:
            order.append(current)
            current = self.entries[current].get('replaces')
        rest = sorted((n for n in self.entries if n not in order), key=lambda n: semver_key(self.version(n)), reverse=True)
        return order + rest

    @property
    def head(self) -> str:
        return self.order[0]

    def upgrade_reason(self, entry: str, installed: str) -> Optional[str]:
        """Why `entry` can replace the installed bundle (None if it can't)"""
        e = self.entries[entry]
        if entry == installed:
            return None
        if e.get('replaces') == installed:
            return 'replaces'
        if installed in e.get('skips', []):
            return 'skips'
        if in_range(self.version(installed), e.get('skipRange', '')):
            return f"skipRange {e['skipRange']}"
        return None

    def next_step(self, installed: str) -> Optional[Tuple[str, str]]:
        """OLM picks, among the entries that can replace the installed bundle, the closest to the head"""
        for entry in self.order:
            reason = self.upgrade_reason(entry, installed)
            if reason:
                return entry, reason
        return None

    def path(self, installed: str) -> List[Tuple[str, str]]:
        steps, current = [], installed
        while current != self.head:
            step = self.next_step(current)
            if not step or step[0] in [s[0] for s in steps]:
                break
            steps.append(step)
            current = step[0]
        return steps

    def sources(self, entry: str) -> List[str]:
        """Bundles (known in the package) that can upgrade directly to `entry`"""
        return sorted((b for b in set(self.versions) | set(self.entries) if self.upgrade_reason(entry, b)),
                      key=lambda b: semver_key(self.version(b)))


def build_package(docs: List[Dict], package: str) -> Tuple[Dict[str, 'Channel'], Optional[str]]:
    default_channel = None
    versions = {}
    channel_entries = {}
    for doc in docs:
        schema = doc.get('schema')
        if schema == 'olm.package' and doc.get('name') == package:
            default_channel = doc.get('defaultChannel')
        elif schema == 'olm.bundle' and doc.get('package') == package:
            for prop in doc.get('properties', []):
                if prop.get('type') == 'olm.package':
                    versions[doc['name']] = prop['value']['version']
        elif schema == 'olm.channel' and doc.get('package') == package:
            channel_entries[doc['name']] = doc.get('entries', [])
    channels = {name: Channel(package, name, entries, versions) for name, entries in channel_entries.items()}
    return channels, default_channel


def find_bundle(channels: Dict[str, Channel], package: str, version: str) -> str:
    """Bundle name of an installed version (accepts 1.2.3, v1.2.3 or the full CSV name)"""
    any_channel = next(iter(channels.values()))
    for bundle, v in any_channel.versions.items():
        if version in (bundle, v, 'v' + v):
            return bundle
    # Not in the catalog any more (pruned): OLM still matches skips/skipRange by name and version
    return f"{package}.v{version.lstrip('v')}"


# --- output ---------------------------------------------------------------------------------------

def natural_key(text: str):
    return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', text)]


def format_path(channel: Channel, installed: str, steps: List[Tuple[str, str]], image: str) -> str:
    v = channel.version
    lines = [f"Upgrade path for {channel.package} in channel {channel.name}", f"Catalog: {image}", "=" * 90]
    lines.append(f"  Installed      {v(installed)}  ({installed})")
    lines.append(f"  Channel head   {v(channel.head)}  ({channel.head})")
    lines.append("-" * 90)
    if installed == channel.head:
        lines.append("  Already at the channel head, nothing to upgrade.")
        return "\n".join(lines)
    if not steps and semver_key(v(installed)) > semver_key(v(channel.head)):
        lines.append(f"  {v(installed)} is newer than the channel head: nothing to upgrade in {channel.name}.")
        return "\n".join(lines)
    if not steps:
        lines.append(f"  No upgrade edge from {v(installed)} in channel {channel.name}:")
        lines.append("  no entry replaces it, skips it, or has a skipRange that includes it.")
        return "\n".join(lines)
    current = installed
    for i, (entry, reason) in enumerate(steps, 1):
        lines.append(f"  {i:>3}. {v(current):<20} -> {v(entry):<20} ({reason})")
        current = entry
    lines.append("-" * 90)
    if current == channel.head:
        lines.append(f"  {len(steps)} upgrade(s) to reach the head: " + " -> ".join([v(installed)] + [v(s[0]) for s in steps]))
    else:
        lines.append(f"  Stuck at {v(current)}: no entry upgrades from it to reach the head {v(channel.head)}")
    return "\n".join(lines)


def format_graph(channel: Channel, image: str, default_channel: Optional[str], all_channels: List[str]) -> str:
    v = channel.version
    lines = [f"Upgrade graph for {channel.package} - channel {channel.name}"
             f"{' (default)' if channel.name == default_channel else ''}",
             f"Catalog: {image}",
             f"Channels: {', '.join(c + (' *' if c == default_channel else '') for c in all_channels)}",
             "=" * 110,
             f"  {'Version':<22}{'Replaces':<22}{'Skips':<22}{'skipRange':<28}Direct upgrade from",
             "-" * 110]
    for entry in channel.order:
        e = channel.entries[entry]
        sources = channel.sources(entry)
        head = '  (head)' if entry == channel.head else ''
        skips = ", ".join(v(s) for s in e.get('skips', [])) or '-'
        src = ", ".join(v(s) for s in sources)
        if len(sources) > 6:
            src = f"{len(sources)} versions: {v(sources[0])} ... {v(sources[-1])}"
        lines.append(f"  {v(entry) + head:<22}{v(e['replaces']) if e.get('replaces') else '-':<22}"
                     f"{skips:<22}{e.get('skipRange') or '-':<28}{src or '-'}")
    lines += ["-" * 110, f"  {len(channel.entries)} entries, head {v(channel.head)}"]
    return "\n".join(lines)


def format_mermaid(channel: Channel, steps: Optional[List[Tuple[str, str]]], installed: Optional[str]) -> str:
    """Mermaid flowchart of the channel (renders in GitHub/GitLab markdown); the path is highlighted"""
    v = channel.version
    node = lambda b: 'n' + re.sub(r'\W', '_', b)
    lines = ["```mermaid", "flowchart LR"]
    nodes = set(channel.entries) | ({installed} if installed else set())
    for bundle in sorted(nodes, key=lambda b: semver_key(v(b))):
        lines.append(f'  {node(bundle)}["{v(bundle)}"]')
    path_edges = set()
    if steps:
        current = installed
        for entry, _ in steps:
            path_edges.add((current, entry))
            current = entry
    edges, link_styles = [], []
    for entry in reversed(channel.order):
        e = channel.entries[entry]
        sources = set(s for s in [e.get('replaces')] + e.get('skips', []) if s)
        sources |= {s for s, _ in path_edges if _ == entry}
        for s in sorted(sources, key=lambda b: semver_key(v(b))):
            if s not in channel.entries and s != installed:
                continue
            style = '-->' if e.get('replaces') == s or (s, entry) in path_edges else '-.->'
            if (s, entry) in path_edges:
                link_styles.append(len(edges))
            edges.append(f"  {node(s)} {style} {node(entry)}")
        if e.get('skipRange'):
            # Kept in `edges`: linkStyle indexes count every link in declaration order
            edges.append(f'  {node(entry)}_range(["skipRange {e["skipRange"]}"]) -.-> {node(entry)}')
    lines += edges
    if link_styles:
        lines.append(f"  linkStyle {','.join(map(str, link_styles))} stroke:#d33,stroke-width:3px")
    if installed:
        lines.append(f"  style {node(installed)} fill:#fde68a")
    lines.append(f"  style {node(channel.head)} fill:#bbf7d0")
    lines.append("```")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Show the OLM upgrade graph of an operator channel, and the upgrade path to the channel head",
        epilog="Examples:\n"
               "  %(prog)s 4.21 cluster-logging                       # graph of the default channel\n"
               "  %(prog)s 4.21 cluster-logging --channel stable-6.5\n"
               "  %(prog)s 4.21 cluster-logging --from 6.4.2           # upgrade path to the head\n"
               "  %(prog)s 4.21 cluster-logging --from 6.4.2 --channel stable-6.6   # path after a channel switch\n"
               "  %(prog)s 4.21 cluster-logging -f mermaid > graph.md  # diagram for markdown\n"
               "  %(prog)s 4.21 my-operator --index registry.example.com/mirror/redhat-operator-index:v4.21\n"
               "  %(prog)s 4.21 cluster-logging --registry-config ~/pull-secret.json",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('ocp_version', help="OpenShift version, e.g. 4.21 (selects the index image tag)")
    parser.add_argument('package', help="Operator package name, e.g. cluster-logging (see list_operators.py)")
    parser.add_argument('--channel', '-C', help="Channel (default: the package's default channel)")
    parser.add_argument('--from', dest='from_version', metavar='VERSION',
                        help="Installed version (e.g. 6.4.2 or cluster-logging.v6.4.2): show the upgrade path to the head")
    parser.add_argument('--catalog', '-c', choices=list(INDEX_IMAGES), default='redhat-operators',
                        help="Catalog (default: redhat-operators)")
    parser.add_argument('--index', help="Index image to use instead of the catalog (e.g. a mirrored index)")
    parser.add_argument('--catalog-dir', help="Read an already extracted /configs/<package> directory instead of the image")
    parser.add_argument('--registry-config', '-a', help="Registry auth file (pull secret) for oc image extract")
    parser.add_argument('--format', '-f', default='table', choices=['table', 'mermaid', 'json'],
                        help="Output format (default: table)")
    args = parser.parse_args()

    match = re.fullmatch(r'(\d+\.\d+)(\.\d+)?', args.ocp_version)
    if not match:
        parser.error(f"invalid OpenShift version '{args.ocp_version}', expected e.g. 4.21")
    image = args.index or f"{INDEX_IMAGES[args.catalog]}:v{match.group(1)}"

    try:
        if args.catalog_dir:
            image = args.catalog_dir
            docs = load_catalog_dir(args.catalog_dir)
        else:
            print(f"Extracting {args.package} from {image}...", file=sys.stderr)
            docs = extract_package(image, args.package, args.registry_config)
    except CatalogError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(2)

    channels, default_channel = build_package(docs, args.package)
    if not channels:
        print(f"Error: no channel found for package '{args.package}' in {image}", file=sys.stderr)
        sys.exit(1)
    channel_names = sorted(channels, key=natural_key)
    channel_name = args.channel or default_channel or channel_names[-1]
    if channel_name not in channels:
        print(f"Error: channel '{channel_name}' not found. Channels: {', '.join(channel_names)}", file=sys.stderr)
        sys.exit(1)
    channel = channels[channel_name]

    installed, steps = None, None
    if args.from_version:
        installed = find_bundle(channels, args.package, args.from_version)
        if installed not in channel.versions:
            print(f"Warning: {installed} is not in the catalog any more, matching it by name and version",
                  file=sys.stderr)
        steps = channel.path(installed)

    if args.format == 'json':
        v = channel.version
        out = {'package': args.package, 'catalog': image, 'channel': channel_name,
               'default_channel': default_channel, 'channels': channel_names, 'head': v(channel.head),
               'entries': [{'version': v(n), 'name': n, 'replaces': channel.entries[n].get('replaces'),
                            'skips': channel.entries[n].get('skips', []),
                            'skipRange': channel.entries[n].get('skipRange'),
                            'upgrade_from': [v(s) for s in channel.sources(n)]} for n in channel.order]}
        if installed:
            out['path'] = {'from': v(installed), 'reaches_head': (steps[-1][0] if steps else installed) == channel.head,
                           'steps': [{'to': v(e), 'reason': r} for e, r in steps]}
        print(json.dumps(out, indent=2))
    elif args.format == 'mermaid':
        print(format_mermaid(channel, steps, installed))
    elif installed:
        print(format_path(channel, installed, steps, image))
    else:
        print(format_graph(channel, image, default_channel, channel_names))


if __name__ == '__main__':
    main()
