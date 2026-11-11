#!/usr/bin/env bash
set -euo pipefail

PRODUCT_ROOT="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
readonly PRODUCT_ROOT

exec "${AIXAND_DEV_PYTHON:-${CARRIER_DEV_PYTHON:-python3}}" -B "${PRODUCT_ROOT}/scripts/carrier_dev.py" "$@"
