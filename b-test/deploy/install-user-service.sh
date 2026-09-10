#!/usr/bin/env sh
# Run as the Linux account that will own the simulator; no root operation is needed.
set -eu
src_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
install_dir="$HOME/.local/share/jammers-linux"
unit_dir="$HOME/.config/systemd/user"
mkdir -p "$install_dir" "$unit_dir" "$HOME/.local/state/jammers-linux"
python3 - "$src_dir" "$install_dir" <<'PY'
import pathlib, shutil, sys
src, dest = map(pathlib.Path, sys.argv[1:])
if src.resolve() != dest.resolve():
    for item in src.iterdir():
        if item.name in {'runs', 'validation', '__pycache__', 'secrets', '.git'}:
            continue
        target = dest / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        else:
            shutil.copy2(item, target)
PY
cp "$install_dir/deploy/jammers-linux.service" "$unit_dir/jammers-linux.service"
systemctl --user daemon-reload
systemctl --user enable --now jammers-linux.service
systemctl --user --no-pager status jammers-linux.service
