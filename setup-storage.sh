#!/usr/bin/env bash
# setup-storage.sh — Mount a dedicated disk at /docker and migrate:
# A) Docker data-root  -> /docker/docker-data
# B) Project data      -> /docker/projects/pmx (with optional symlinks)
#
# Usage examples:
#   sudo ./setup-storage.sh --device /dev/sdb --mount /docker --mode both --repo /opt/pmx --project-root /docker/projects/pmx --symlink true
#   sudo ./setup-storage.sh --revert
#
set -Eeuo pipefail

# Defaults
MOUNT="/docker"
MODE="both"               # data-root | projects | both | revert
REPO="$(pwd)"
PROJECT_ROOT="/docker/projects/pmx"
SYMLINK="true"
RAG_PORT_FIX="8082"
DEVICE=""
VG_NAME=""
LV_NAME=""
LV_SIZE=""
NONINTERACTIVE="${NONINTERACTIVE:-false}"

# Logging helpers
bold() { printf "\033[1m%s\033[0m\n" "$*"; }
info() { printf "[INFO] %s\n" "$*"; }
warn() { printf "[WARN] %s\n" "$*"; }
err()  { printf "[ERR ] %s\n" "$*" >&2; }
die()  { err "$*"; exit 1; }

require_root() {
  if [[ "${EUID}" -ne 0 ]]; then
    die "Please run as root (sudo)."
  fi
}

# Arg parsing
while [[ $# -gt 0 ]]; do
  case "$1" in
    --device) DEVICE="${2:-}"; shift 2;;
    --vg) VG_NAME="${2:-}"; shift 2;;
    --lv) LV_NAME="${2:-}"; shift 2;;
    --size) LV_SIZE="${2:-}"; shift 2;;
    --mount) MOUNT="${2:-}"; shift 2;;
    --mode) MODE="${2:-}"; shift 2;;
    --repo) REPO="${2:-}"; shift 2;;
    --project-root) PROJECT_ROOT="${2:-}"; shift 2;;
    --symlink) SYMLINK="${2:-}"; shift 2;;
    --rag-port) RAG_PORT_FIX="${2:-}"; shift 2;;
    --yes|-y) NONINTERACTIVE="true"; shift;;
    --revert) MODE="revert"; shift;;
    -h|--help)
      cat <<'EOF'
setup-storage.sh

Flags:
  --device /dev/sdX        Use a raw block device (ext4, UUID in fstab)
  --vg NAME --lv NAME      Use existing/new LVM LV (with --size if create)
  --size 500G              LV size when creating
  --mount /docker          Mountpoint (default: /docker)
  --mode [data-root|projects|both|revert]
  --repo /opt/pmx          Path to your pmx repo (default: $PWD)
  --project-root /docker/projects/pmx
  --symlink [true|false]   Replace repo dirs with symlinks (default: true)
  --rag-port 8082          Patch install_rag.sh to port 8082 (or "skip")
  --yes                    Non-interactive
  --revert                 Revert Docker data-root to /var/lib/docker

Examples:
  sudo ./setup-storage.sh --device /dev/sdb --mount /docker --mode both --repo /opt/pmx
  sudo ./setup-storage.sh --revert
EOF
      exit 0
      ;;
    *)
      die "Unknown argument: $1"
      ;;
  esac
done

require_root
command -v rsync >/dev/null || (apt-get update -y && apt-get install -y rsync)
command -v jq >/dev/null || apt-get install -y jq
command -v blkid >/dev/null || apt-get install -y util-linux

if [[ "$MODE" != "data-root" && "$MODE" != "projects" && "$MODE" != "both" && "$MODE" != "revert" ]]; then
  die "--mode must be one of: data-root | projects | both | revert"
fi

mkdir -p "$MOUNT"

confirm() {
  local prompt="${1:-Proceed?}"
  if [[ "$NONINTERACTIVE" == "true" ]]; then
    return 0
  fi
  read -rp "$prompt [y/N]: " ans || true
  [[ "${ans,,}" == "y" || "${ans,,}" == "yes" ]]
}

ensure_fstab_uuid() {
  local dev="$1" mnt="$2" opts="$3"
  local uuid
  uuid="$(blkid -s UUID -o value "$dev" || true)"
  [[ -n "$uuid" ]] || die "Could not read UUID from $dev"
  local line="UUID=$uuid $mnt ext4 $opts 0 2"
  if grep -qE "^[^#]*[[:space:]]$mnt[[:space:]]" /etc/fstab; then
    sed -i -E "s|^[^#]*[[:space:]]$mnt[[:space:]].*|$line|" /etc/fstab
  else
    echo "$line" >> /etc/fstab
  fi
}

prepare_mount() {
  local mount_opts="defaults,noatime,nofail"
  local dev_path=""

  if [[ -n "$DEVICE" ]]; then
    dev_path="$DEVICE"
    [[ -b "$dev_path" ]] || die "Device $dev_path not found or not a block device"
    if ! blkid "$dev_path" >/dev/null 2>&1; then
      info "Formatting $dev_path as ext4…"
      mkfs.ext4 -F "$dev_path"
    else
      info "$dev_path already has a filesystem."
    fi
    ensure_fstab_uuid "$dev_path" "$MOUNT" "$mount_opts"
    mkdir -p "$MOUNT"
    mountpoint -q "$MOUNT" || mount "$MOUNT"
    return 0
  fi

  if [[ -n "$VG_NAME" ]]; then
    command -v lvs >/dev/null || apt-get install -y lvm2
    [[ -n "$LV_NAME" ]] || die "--lv is required when using --vg"
    dev_path="/dev/${VG_NAME}/${LV_NAME}"
    if ! lvs "$VG_NAME/$LV_NAME" >/dev/null 2>&1; then
      [[ -n "$LV_SIZE" ]] || die "--size is required to create LV"
      info "Creating LV ${VG_NAME}/${LV_NAME} of size $LV_SIZE…"
      lvcreate -L "$LV_SIZE" -n "$LV_NAME" "$VG_NAME"
    else
      info "LV ${VG_NAME}/${LV_NAME} already exists."
    fi
    if ! blkid "$dev_path" >/dev/null 2>&1; then
      info "Formatting $dev_path as ext4…"
      mkfs.ext4 -F "$dev_path"
    fi
    ensure_fstab_uuid "$dev_path" "$MOUNT" "$mount_opts"
    mkdir -p "$MOUNT"
    mountpoint -q "$MOUNT" || mount "$MOUNT"
    return 0
  fi

  if ! mountpoint -q "$MOUNT"; then
    warn "No --device/--vg given; attempting to mount $MOUNT from fstab…"
    mount "$MOUNT" || warn "Could not mount $MOUNT."
  fi
}

docker_stop() {
  systemctl is-active --quiet docker && systemctl stop docker || true
  systemctl is-active --quiet docker.socket && systemctl stop docker.socket || true
  if systemctl list-unit-files | grep -q '^containerd\.service'; then
    systemctl is-active --quiet containerd && systemctl stop containerd || true
  fi
}

docker_start() {
  systemctl daemon-reload || true
  if systemctl list-unit-files | grep -q '^containerd\.service'; then
    systemctl start containerd || true
  fi
  systemctl start docker
}

docker_root_dir() {
  docker info 2>/dev/null | awk -F': ' '/Docker Root Dir/ {print $2}'
}

migrate_docker_root() {
  local target="${MOUNT%/}/docker-data"
  mkdir -p "$target"
  chown root:root "$target"
  chmod 0755 "$target"

  local daemon_json="/etc/docker/daemon.json"
  local orig_root="/var/lib/docker"

  bold ">>> Migrating Docker data-root to: $target"
  info "Stopping Docker…"
  docker_stop

  if [[ -s "$daemon_json" ]]; then
    info "Updating $daemon_json (preserving other keys)…"
    tmp="$(mktemp)"
    jq --arg root "$target" '.["data-root"] = $root' "$daemon_json" > "$tmp"
    mv "$tmp" "$daemon_json"
  else
    info "Creating $daemon_json…"
    mkdir -p "$(dirname "$daemon_json")"
    printf '{ "data-root": "%s" }\n' "$target" > "$daemon_json"
  fi

  info "Syncing current Docker data to new location…"
  rsync -aHAXx --numeric-ids "$orig_root/" "$target/" || die "rsync failed"

  info "Starting Docker…"
  docker_start

  sleep 2
  local now_root
  now_root="$(docker_root_dir || true)"
  if [[ "$now_root" != "$target" ]]; then
    warn "Docker Root Dir reports '$now_root' (expected '$target'). Restarting docker…"
    systemctl restart docker || true
    sleep 2
    now_root="$(docker_root_dir || true)"
  fi
  info "Docker Root Dir: ${now_root:-<unknown>}"
  if [[ "$now_root" == "$target" ]]; then
    if confirm "Migration looks good. Backup old /var/lib/docker to /var/lib/docker.bak?"; then
      mv "$orig_root" "/var/lib/docker.bak.$(date +%Y%m%d-%H%M%S)"
      mkdir -p "$orig_root"
    fi
    bold ">>> Docker data-root migration complete."
  else
    warn "Docker still not using $target. Please inspect /etc/docker/daemon.json and logs."
  fi
}

revert_docker_root() {
  local daemon_json="/etc/docker/daemon.json"
  local target="/var/lib/docker"
  mkdir -p "$target"

  bold ">>> Reverting Docker data-root to: $target"
  info "Stopping Docker…"
  docker_stop

  local cur_root=""
  if [[ -s "$daemon_json" ]]; then
    cur_root="$(jq -r '."data-root" // empty' "$daemon_json" || true)"
  fi

  if [[ -n "$cur_root" && -d "$cur_root" && -z "$(ls -A "$target" 2>/dev/null || true)" ]]; then
    info "Syncing data back from $cur_root to $target…"
    rsync -aHAXx --numeric-ids "$cur_root/" "$target/"
  else
    warn "Not syncing data (either no current data-root, or $target not empty)."
  fi

  info "Updating $daemon_json…"
  tmp="$(mktemp)"
  if [[ -s "$daemon_json" ]]; then
    jq 'del(."data-root")' "$daemon_json" > "$tmp" || printf '{}\n' > "$tmp"
  else
    printf '{}\n' > "$tmp"
  fi
  mv "$tmp" "$daemon_json"

  info "Starting Docker…"
  docker_start
  sleep 2
  info "Docker Root Dir: $(docker_root_dir || true)"
  bold ">>> Revert complete."
}

move_project_data() {
  local repo="$REPO" proj_root="$PROJECT_ROOT"
  [[ -d "$repo" ]] || die "--repo path '$repo' not found"
  mkdir -p "$proj_root"

  local uid gid user group
  uid="$(stat -c %u "$repo")"
  gid="$(stat -c %g "$repo")"
  user="$(getent passwd "$uid" | cut -d: -f1 || true)"
  group="$(getent group "$gid" | cut -d: -f1 || true)"
  [[ -n "$user" ]] || user="root"
  [[ -n "$group" ]] || group="root"

  bold ">>> Relocating pmx project data to: $proj_root (owner: $user:$group)"

  local rag_src_docs="$repo/rag-backend/documents"
  local rag_src_store="$repo/rag-backend/storage"
  local rag_dst_root="$proj_root/rag"
  local rag_dst_docs="$rag_dst_root/documents"
  local rag_dst_store="$rag_dst_root/storage"

  mkdir -p "$rag_dst_docs" "$rag_dst_store"
  chown -R "$user:$group" "$rag_dst_root"
  chmod -R 0775 "$rag_dst_root"

  _move_and_link() {
    local src="$1" dst="$2"
    if [[ -d "$src" && ! -L "$src" ]]; then
      info "Syncing $src -> $dst"
      rsync -aHAX --delete "$src/" "$dst/"
      if [[ "${SYMLINK,,}" == "true" ]]; then
        local bak="${src}.bak.$(date +%Y%m%d-%H%M%S)"
        mv "$src" "$bak"
        ln -s "$dst" "$src"
      fi
    elif [[ -L "$src" ]]; then
      info "$src already a symlink. Skipping."
    else
      if [[ "${SYMLINK,,}" == "true" ]]; then
        info "$src missing; creating symlink -> $dst"
        ln -s "$dst" "$src"
      else
        info "$src missing; leaving as-is."
      fi
    fi
  }

  _move_and_link "$rag_src_docs" "$rag_dst_docs"
  _move_and_link "$rag_src_store" "$rag_dst_store"

  bold ">>> Project data relocation complete."
}

patch_rag_port() {
  local repo="$REPO"
  local rag_install="$repo/install_rag.sh"
  [[ -f "$rag_install" ]] || { info "install_rag.sh not found; skipping port patch."; return 0; }
  [[ "$RAG_PORT_FIX" == "skip" ]] && { info "RAG port patch skipped."; return 0; }
  bold ">>> Patching RAG installer to use port $RAG_PORT_FIX"
  sed -i -E "s#(:)8000#\1${RAG_PORT_FIX}#g; s#localhost:8000#localhost:${RAG_PORT_FIX}#g" "$rag_install"
}

main() {
  if [[ "$MODE" == "revert" ]]; then
    revert_docker_root
    exit 0
  fi

  prepare_mount

  case "$MODE" in
    data-root) migrate_docker_root ;;
    projects)  move_project_data; patch_rag_port ;;
    both)      migrate_docker_root; move_project_data; patch_rag_port ;;
    *) die "invalid mode";;
  esac

  bold "All done."
  echo "Summary:"
  echo "  Mount:           $MOUNT"
  echo "  Mode:            $MODE"
  echo "  Repo:            $REPO"
  echo "  Project root:    $PROJECT_ROOT"
  echo "  Symlink:         $SYMLINK"
  echo "  RAG port fix:    $RAG_PORT_FIX"
}

main "$@"
