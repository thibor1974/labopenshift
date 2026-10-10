# OpenShift Operator Versions

`list_operators.py` lists the operators available for an OpenShift version and, for each operator channel, the latest version (the channel head, what OperatorHub installs).

## Features

✅ **Per channel** - Every channel of every operator, with its latest version and publish date  
✅ **Default channel** - Marks the channel used when a Subscription doesn't set one  
✅ **All catalogs** - redhat-operators, certified-operators, community-operators, redhat-marketplace  
✅ **Full history** - `--all-versions` lists every version available in each channel  
✅ **Multiple Output Formats** - Table, CSV and JSON  
✅ **No login needed** - Uses the public Red Hat Ecosystem Catalog API, no pull secret required  
✅ **Fast** - About 2 s for redhat-operators, 7 s for the four catalogs  

## Requirements

- Python 3.9+ (standard library only)
- `curl`
- Internet access to `catalog.redhat.com`

```bash
chmod +x list_operators.py
```

## Usage

```bash
./list_operators.py <ocp_version> [options]
```

| Option | Description |
|---|---|
| `ocp_version` | OpenShift version, e.g. `4.21`. A full release (`4.21.17`) is accepted, but only the stream is used: operator catalogs are published per stream |
| `-c, --catalog` | Catalog to query: `redhat-operators` (default), `certified-operators`, `community-operators`, `redhat-marketplace`, or `all`. Repeatable |
| `-p, --package` | Only operators whose package name or display name contains this text (case-insensitive) |
| `-d, --default-only` | Only show the default channel of each operator |
| `-a, --all-versions` | List every version available in each channel, not only the latest one |
| `-f, --format` | `table` (default), `csv` or `json` |

### Examples

```bash
# All Red Hat operators for OpenShift 4.21, every channel with its latest version
./list_operators.py 4.21

# Only the logging operators
./list_operators.py 4.21 -p logging

# One line per operator: the default channel and its latest version
./list_operators.py 4.21 --default-only

# Every version published in each channel of an operator
./list_operators.py 4.21 --all-versions -p cluster-logging

# Several catalogs
./list_operators.py 4.21 -c certified-operators -c community-operators

# Every catalog, exported to CSV
./list_operators.py 4.21 -c all -f csv > operators-4.21.csv

# Compare two OpenShift versions
./list_operators.py 4.20 -d -f csv > ops-4.20.csv
./list_operators.py 4.21 -d -f csv > ops-4.21.csv
diff ops-4.20.csv ops-4.21.csv
```

## Output

### Table (default)

```
Operators for OpenShift 4.21: 149 operators, 481 channels
==============================================================================================

[redhat-operators]
  Package                       Channel           Version   Published   Name
  --------------------------------------------------------------------------------------------
  advanced-cluster-management   release-2.15      2.15.8    2026-09-30  Advanced Cluster Management for Kubernetes
                                release-2.16      2.16.6    2026-09-30
                                release-2.17 *    2.17.3    2026-09-30
  cluster-logging               stable-6.4        6.4.7     2026-10-07  Red Hat OpenShift Logging
                                stable-6.5        6.5.3     2026-09-23
                                stable-6.6 *      6.6.1     2026-09-10
  compliance-operator           4.7               0.1.32    ...         Compliance Operator
                                release-0.1       0.1.61    ...
                                stable *          1.10.0    2026-09-15

  * default channel (installed when no channel is chosen)
```

With `--all-versions`, every version of a channel is listed and the latest one is marked `(head)`.

### CSV

One row per catalog / package / channel / version:

```
catalog,package,display_name,channel,default,version,latest,published
redhat-operators,cluster-logging,Red Hat OpenShift Logging,stable-6.4,False,6.4.7,True,2026-10-07
redhat-operators,cluster-logging,Red Hat OpenShift Logging,stable-6.6,True,6.6.1,True,2026-09-10
```

| Column | Meaning |
|---|---|
| `default` | `True` if this channel is the operator's default channel |
| `latest` | `True` if this version is the head of the channel (always `True` without `--all-versions`) |
| `published` | Date the bundle was published in the catalog |

### JSON

Nested by catalog, package and channel:

```json
{
  "ocp_version": "4.21",
  "catalogs": {
    "redhat-operators": {
      "compliance-operator": {
        "display_name": "Compliance Operator",
        "default_channel": "stable",
        "channels": {
          "4.7": ["0.1.32"],
          "release-0.1": ["0.1.61"],
          "stable": ["1.10.0"]
        }
      }
    }
  }
}
```

Useful with `jq`, e.g. the latest version of the default channel of every operator:

```bash
./list_operators.py 4.21 -f json | jq -r '.catalogs["redhat-operators"] | to_entries[]
  | "\(.key)  \(.value.default_channel)  \(.value.channels[.value.default_channel][-1])"'
```

## How it works

The data comes from the **Red Hat Ecosystem Catalog API** (Pyxis):

```
https://catalog.redhat.com/api/containers/v1/operators/bundles
  ?filter=ocp_version==4.21;organization==redhat-operators;in_index_img==true;latest_in_channel==true
```

- Each record is an operator **bundle** (one version of an operator) in one channel of one catalog index for one OpenShift stream.
- `in_index_img==true` keeps only bundles that are currently in the index image.
- `latest_in_channel==true` keeps only the channel heads (removed with `--all-versions`).
- Results are paginated (500 per page) and deduplicated.

The catalogs map to the index images used by OperatorHub on the cluster:

| Catalog | Index image |
|---|---|
| `redhat-operators` | `registry.redhat.io/redhat/redhat-operator-index:v4.21` |
| `certified-operators` | `registry.redhat.io/redhat/certified-operator-index:v4.21` |
| `community-operators` | `registry.redhat.io/redhat/community-operator-index:v4.21` |
| `redhat-marketplace` | `registry.redhat.io/redhat/redhat-marketplace-index:v4.21` |

### Default channel

The API stores the "default channel" flag on each bundle when it is published, so older bundles keep a stale flag (for example, two 3scale channels were both flagged default). The script uses the channel of the **most recently published bundle flagged default**, which gives exactly one default channel per operator.

## Limitations

- The API mirrors the index images but is not the image itself. For an exact match with what a disconnected mirror will pull, check against the index image with your pull secret:
  ```bash
  oc-mirror list operators --catalog=registry.redhat.io/redhat/redhat-operator-index:v4.21 --package=cluster-logging
  ```
- The `published` date is when the bundle was added to the catalog, not necessarily the operator's official release date.
- Some versions are reported exactly as published by the vendor, including build suffixes (e.g. `7.12.7-opr-1+0.1780501200.p`).
- Results reflect the catalog at the time of the query; channel heads change as new versions are released.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | Success |
| `1` | No operators found (unknown OpenShift version, or filter matched nothing) |
| `2` | The catalog API could not be reached |

## Related scripts

- `operator_upgrade_path.py` - OLM upgrade graph of an operator channel, and the upgrade path from an installed version ([OPERATOR_UPGRADE_PATH_README.md](OPERATOR_UPGRADE_PATH_README.md))
- `list_versions.py` - OpenShift releases available per stream and update channel, with release dates
- `get_vulnerabilities.py` - CVEs affecting an OpenShift version, and the release that fixes them
