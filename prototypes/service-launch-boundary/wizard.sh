#!/usr/bin/env bash
# THROWAWAY PROTOTYPE: prove an administrator-installed legacy LaunchDaemon.

set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PREVIOUS_PROTOTYPE_DIR=$(cd "$SCRIPT_DIR/../personal-installation-lifecycle" && pwd)
SERVICE_USER="_hplj1020"
TEST_USER="_hplj1020test"
SERVICE_LABEL="com.bartekpapierski.hplj1020.launch-boundary"
SERVICE_PLIST="/Library/LaunchDaemons/$SERVICE_LABEL.plist"
INSTALL_ROOT="/Library/Application Support/HP-LJ-1020"
BIN_ROOT="$INSTALL_ROOT/Prototype/bin"
STATE_ROOT="$INSTALL_ROOT/State"
CAPTURE_ROOT="$INSTALL_ROOT/Captured"
LOG_ROOT="/Library/Logs/HP-LJ-1020"
QUEUE="HPLJ1020LaunchBoundary"
EVIDENCE_DIR=$(mktemp -d /private/tmp/hplj1020-launch-boundary-evidence.XXXXXX)
APP_PATH=""
SYSTEM_CHANGES_STARTED=0
CLEANUP_FINISHED=0

say() { printf '%s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
confirm() {
  local reply=""
  printf '%s [y/N] ' "$1"
  read -r reply || true
  [[ "$reply" =~ ^[Yy]$ ]]
}
record() { printf '%s\n' "$*" | tee -a "$EVIDENCE_DIR/result.txt"; }

next_free_system_id() {
  local candidate
  for ((candidate=499; candidate>=450; candidate--)); do
    if ! dscacheutil -q user -a uid "$candidate" | grep -q '^name:' &&
       ! dscacheutil -q group -a gid "$candidate" | grep -q '^name:'; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

prototype_account_matches() {
  local account="$1" real_name="$2" user_record group_record
  local name uid user_gid group_gid home shell gecos
  user_record=$(dscacheutil -q user -a name "$account") || return 1
  group_record=$(dscacheutil -q group -a name "$account") || return 1
  name=$(printf '%s\n' "$user_record" | awk '$1 == "name:" {print $2; exit}')
  uid=$(printf '%s\n' "$user_record" | awk '$1 == "uid:" {print $2; exit}')
  user_gid=$(printf '%s\n' "$user_record" | awk '$1 == "gid:" {print $2; exit}')
  group_gid=$(printf '%s\n' "$group_record" | awk '$1 == "gid:" {print $2; exit}')
  home=$(printf '%s\n' "$user_record" | awk '$1 == "dir:" {print $2; exit}')
  shell=$(printf '%s\n' "$user_record" | awk '$1 == "shell:" {print $2; exit}')
  gecos=$(printf '%s\n' "$user_record" | awk 'index($0, "gecos: ") == 1 {print substr($0, 8); exit}')
  [[ "$name" == "$account" ]]
  [[ "$uid" =~ ^[0-9]+$ && "$uid" -ge 450 && "$uid" -le 499 ]]
  [[ "$user_gid" == "$group_gid" ]]
  [[ "$home" == "/var/empty" ]]
  [[ "$shell" == "/usr/bin/false" ]]
  [[ "$gecos" == "$real_name" ]]
}

create_hidden_account() {
  local account="$1" real_name="$2" account_id
  if id "$account" >/dev/null 2>&1; then
    if prototype_account_matches "$account" "$real_name"; then
      return 0
    fi
    warn "Refusing to reuse $account because its markers do not match this prototype."
    return 1
  fi
  if dscacheutil -q group -a name "$account" | grep -q '^name:'; then
    warn "Refusing to reuse group $account without its matching prototype account."
    return 1
  fi
  account_id=$(next_free_system_id)
  sudo dscl . -create "/Groups/$account"
  sudo dscl . -create "/Groups/$account" PrimaryGroupID "$account_id"
  sudo dscl . -create "/Groups/$account" Password '*'
  sudo dscl . -create "/Users/$account"
  sudo dscl . -create "/Users/$account" UniqueID "$account_id"
  sudo dscl . -create "/Users/$account" PrimaryGroupID "$account_id"
  sudo dscl . -create "/Users/$account" RealName "$real_name"
  sudo dscl . -create "/Users/$account" NFSHomeDirectory /var/empty
  sudo dscl . -create "/Users/$account" UserShell /usr/bin/false
  sudo dscl . -create "/Users/$account" IsHidden 1
  sudo dscl . -create "/Users/$account" Password '*'
}

remove_hidden_account() {
  local account="$1" real_name="$2"
  if id "$account" >/dev/null 2>&1; then
    if ! prototype_account_matches "$account" "$real_name"; then
      warn "Preserving $account because its markers do not match this prototype."
      return 1
    fi
    sudo dscl . -delete "/Users/$account"
  fi
  if dscacheutil -q group -a name "$account" | grep -q '^name:'; then
    sudo dscl . -delete "/Groups/$account"
  fi
}

install_payload() {
  create_hidden_account "$SERVICE_USER" "HP LaserJet 1020 Service"
  sudo install -d -o root -g wheel -m 755 "$BIN_ROOT"
  sudo install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 700 \
    "$STATE_ROOT" "$STATE_ROOT/Home" "$STATE_ROOT/Spool" "$CAPTURE_ROOT" "$LOG_ROOT"
  sudo install -d -o "$SERVICE_USER" -g "$SERVICE_USER" -m 700 \
    "$STATE_ROOT/Home/Library" "$STATE_ROOT/Home/Library/Application Support"
  sudo install -o root -g wheel -m 755 \
    "$APP_PATH/Contents/MacOS/hplj1020-pappl" "$BIN_ROOT/hplj1020-pappl"
  sudo install -o root -g wheel -m 755 \
    "$APP_PATH/Contents/MacOS/hplj1020-usb-probe" "$BIN_ROOT/hplj1020-usb-probe"
  sudo install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 600 \
    /dev/null "$LOG_ROOT/daemon.stdout.log"
  sudo install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 600 \
    /dev/null "$LOG_ROOT/daemon.stderr.log"
  sudo install -o "$SERVICE_USER" -g "$SERVICE_USER" -m 600 \
    /dev/null "$LOG_ROOT/launch-boundary.log"
}

install_daemon() {
  install_payload
  sudo launchctl bootout "system/$SERVICE_LABEL" >/dev/null 2>&1 || true
  sudo install -o root -g wheel -m 644 \
    "$SCRIPT_DIR/com.bartekpapierski.hplj1020.launch-boundary.plist" "$SERVICE_PLIST"
  sudo plutil -lint "$SERVICE_PLIST" | tee -a "$EVIDENCE_DIR/install.txt"
  sudo launchctl bootstrap system "$SERVICE_PLIST"
}

cleanup_prototype() {
  sudo launchctl bootout "system/$SERVICE_LABEL" >/dev/null 2>&1 || true
  sudo lpadmin -x "$QUEUE" >/dev/null 2>&1 || true
  sudo rm -f "$SERVICE_PLIST"
  sudo rm -rf "$INSTALL_ROOT"
  sudo rm -rf "$LOG_ROOT"
  remove_hidden_account "$TEST_USER" "HP LaserJet 1020 Non-Admin Test"
  remove_hidden_account "$SERVICE_USER" "HP LaserJet 1020 Service"
}

capture_installed_logs() {
  local phase="$1" name
  for name in daemon.stdout.log daemon.stderr.log launch-boundary.log; do
    if sudo test -f "$LOG_ROOT/$name"; then
      sudo cat "$LOG_ROOT/$name" >"$EVIDENCE_DIR/$phase-$name" 2>/dev/null || true
    fi
  done
}

audit_absence() {
  local failures=0
  [[ ! -e "$SERVICE_PLIST" ]] || { record "absence_plist=false"; failures=$((failures + 1)); }
  [[ ! -e "$INSTALL_ROOT" ]] || { record "absence_install_root=false"; failures=$((failures + 1)); }
  [[ ! -e "$LOG_ROOT" ]] || { record "absence_log_root=false"; failures=$((failures + 1)); }
  ! id "$SERVICE_USER" >/dev/null 2>&1 || { record "absence_service_user=false"; failures=$((failures + 1)); }
  ! id "$TEST_USER" >/dev/null 2>&1 || { record "absence_test_user=false"; failures=$((failures + 1)); }
  ! lpstat -p "$QUEUE" >/dev/null 2>&1 || { record "absence_queue=false"; failures=$((failures + 1)); }
  if (( failures == 0 )); then
    record "cleanup_absence_audit=passed"
  else
    record "cleanup_absence_audit=failed failures=$failures"
    return 1
  fi
}

service_pid() {
  sudo launchctl print "system/$SERVICE_LABEL" 2>/dev/null | \
    awk '$1 == "pid" && $2 == "=" {print $3; exit}'
}

wait_for_service() {
  local attempt pid expected_uid observed_uid listeners
  expected_uid=$(id -u "$SERVICE_USER")
  for attempt in {1..60}; do
    pid=$(service_pid || true)
    if [[ "$pid" =~ ^[0-9]+$ ]]; then
      observed_uid=$(ps -o uid= -p "$pid" 2>/dev/null | tr -d ' ')
      listeners=$(sudo /usr/sbin/lsof -nP -a -p "$pid" -iTCP:8631 -sTCP:LISTEN 2>/dev/null || true)
    else
      observed_uid=""
      listeners=""
    fi
    if [[ "$observed_uid" == "$expected_uid" ]] &&
       printf '%s\n' "$listeners" | grep -Eq '(127\.0\.0\.1|\[::1\]):8631'; then
      return 0
    fi
    sleep 0.5
  done
  return 1
}

run_pappl_cli() {
  sudo -u "$SERVICE_USER" env HOME="$STATE_ROOT/Home" \
    /bin/bash -c 'exec -a hplj1020-pappl "$@"' bash "$BIN_ROOT/hplj1020-pappl" "$@"
}

verify_runtime() {
  local phase="$1" pid expected_uid observed_uid listeners capture_count usb_log
  record "phase=$phase"
  if ! wait_for_service; then
    record "daemon_running=false"
    capture_installed_logs "$phase"
    sudo launchctl print "system/$SERVICE_LABEL" >"$EVIDENCE_DIR/$phase-launchctl.txt" 2>&1 || true
    log show --last 2m --style compact \
      --predicate "process == 'launchd' OR process == 'amfid'" \
      >"$EVIDENCE_DIR/$phase-unified.log" 2>&1 || true
    return 1
  fi

  pid=$(service_pid)
  ps -o user=,uid=,pid=,command= -p "$pid" | tee "$EVIDENCE_DIR/$phase-process.txt"
  expected_uid=$(id -u "$SERVICE_USER")
  observed_uid=$(ps -o uid= -p "$pid" | tr -d ' ')
  if [[ "$observed_uid" == "$expected_uid" ]]; then
    record "process_identity=passed"
  else
    record "process_identity=failed"
    return 1
  fi

  listeners=$(sudo /usr/sbin/lsof -nP -a -p "$pid" -iTCP -sTCP:LISTEN || true)
  printf '%s\n' "$listeners" | tee "$EVIDENCE_DIR/$phase-listeners.txt"
  if printf '%s\n' "$listeners" | grep -Eq '(127\.0\.0\.1|\[::1\]):8631' &&
     ! printf '%s\n' "$listeners" | grep -Ev '(^COMMAND|127\.0\.0\.1|\[::1\])' | grep -q .; then
    record "loopback_listener=passed"
  else
    record "loopback_listener=failed"
    return 1
  fi

  if ! run_pappl_cli printers 2>/dev/null | grep -q LaunchBoundary; then
    run_pappl_cli add -d LaunchBoundary \
      -m pwg_common-300dpi-600dpi-black_1 \
      -v 'file:///Library/Application%20Support/HP-LJ-1020/Captured?ext=pwg'
  fi
  record "pappl_file_printer=passed"

  sudo launchctl kickstart -k system/org.cups.cupsd >/dev/null 2>&1 || true
  sudo lpadmin -x "$QUEUE" >/dev/null 2>&1 || true
  sudo lpadmin -p "$QUEUE" -E \
    -v ipp://localhost:8631/ipp/print/LaunchBoundary -m everywhere
  lpstat -v "$QUEUE" | tee "$EVIDENCE_DIR/$phase-queue.txt"
  record "standard_macos_queue=passed"

  create_hidden_account "$TEST_USER" "HP LaserJet 1020 Non-Admin Test"
  if sudo -u "$TEST_USER" env HOME=/var/empty \
    lp -d "$QUEUE" /usr/share/cups/data/testprint 2>&1 | \
    sed 's/request id is .*/request accepted/' | tee "$EVIDENCE_DIR/$phase-submission.txt"; then
    record "non_admin_submission=passed"
  else
    record "non_admin_submission=failed"
    return 1
  fi
  sleep 3
  capture_count=$(sudo -u "$SERVICE_USER" find "$CAPTURE_ROOT" -type f -print | wc -l | tr -d ' ')
  record "captured_jobs=$capture_count"
  if (( capture_count < 1 )); then
    record "non_admin_job_processing=failed"
    return 1
  fi
  record "non_admin_job_processing=passed"

  usb_log="$EVIDENCE_DIR/$phase-usb.txt"
  if sudo -u "$SERVICE_USER" env HOME="$STATE_ROOT/Home" \
    "$BIN_ROOT/hplj1020-usb-probe" >"$usb_log" 2>&1; then
    cat "$usb_log"
    record "dedicated_account_usb_claim=passed"
    record "privileged_usb_helper=unnecessary"
  elif grep -q '^usb_probe_result=claim-failed$' "$usb_log"; then
    cat "$usb_log"
    record "dedicated_account_usb_claim=failed-after-discovery"
    record "privileged_usb_helper=investigate-minimal"
    return 1
  else
    cat "$usb_log"
    record "dedicated_account_usb_claim=blocked-printer-not-discovered"
    return 1
  fi
  capture_installed_logs "$phase"
}

cleanup_after_failure() {
  local status=$?
  trap - EXIT
  if (( status != 0 && SYSTEM_CHANGES_STARTED == 1 && CLEANUP_FINISHED == 0 )); then
    warn "A validation gate failed. Capturing logs and removing the exact prototype artifacts."
    capture_installed_logs failure || true
    cleanup_prototype >"$EVIDENCE_DIR/failure-cleanup.txt" 2>&1 || true
    audit_absence || true
    warn "Failure evidence and cleanup results remain at $EVIDENCE_DIR"
  fi
  exit "$status"
}

trap cleanup_after_failure EXIT

say "HP LaserJet 1020 personal service launch-boundary probe"
say "Evidence: $EVIDENCE_DIR"
say ""
say "This will create and later remove only:"
say "  $SERVICE_PLIST"
say "  $INSTALL_ROOT"
say "  $LOG_ROOT"
say "  CUPS queue $QUEUE"
say "  local accounts $SERVICE_USER and $TEST_USER when their markers match"

if [[ "${1:-}" == "--cleanup-only" ]]; then
  if confirm "Remove those exact prototype artifacts now?"; then
    cleanup_prototype 2>&1 | tee "$EVIDENCE_DIR/cleanup-only.txt"
    audit_absence
    say "Cleanup complete. Evidence: $EVIDENCE_DIR"
  fi
  exit 0
fi

if ! confirm "Build the probe, then make the listed administrator-approved changes?"; then
  say "No system changes made."
  exit 0
fi

if [[ "$(uname -m)" != "arm64" ]]; then
  warn "This probe is scoped to the arm64 reference Mac."
  exit 1
fi

if [[ -n "${HPLJ1020_BUILD_APP_PATH:-}" ]]; then
  APP_PATH="$HPLJ1020_BUILD_APP_PATH"
  say "Reusing the explicitly supplied pinned build: $APP_PATH"
else
  say "Building pinned dependencies. This stage makes no system changes."
  BUILD_LOG="$EVIDENCE_DIR/build.log"
  "$PREVIOUS_PROTOTYPE_DIR/build.sh" 2>&1 | tee "$BUILD_LOG"
  APP_PATH=$(sed -n 's/^APP_PATH=//p' "$BUILD_LOG" | tail -n 1)
fi
[[ -d "$APP_PATH" ]] || { warn "Build did not produce the expected app."; exit 1; }
cp "$APP_PATH/Contents/Resources/build-manifest.txt" "$EVIDENCE_DIR/build-manifest.txt"

say "Administrator access is required from this point. The wizard never reads or stores the password."
sudo -v
SYSTEM_CHANGES_STARTED=1

say "Checking for stale prototype state."
cleanup_prototype 2>&1 | tee "$EVIDENCE_DIR/preflight-cleanup.txt"
audit_absence

say "Simulating interruption after payload placement but before daemon registration."
install_payload 2>&1 | tee "$EVIDENCE_DIR/partial-install.txt"
[[ ! -e "$SERVICE_PLIST" ]]
if sudo launchctl print "system/$SERVICE_LABEL" >/dev/null 2>&1; then
  record "partial_install_boundary=failed-unexpected-service"
  exit 1
fi
record "partial_install_boundary=created"

say "Recovering the partial installation with the normal install operation."
install_daemon 2>&1 | tee "$EVIDENCE_DIR/recovery-install.txt"
record "interrupted_install_recovery=passed"
say "Confirm the reference printer is powered on and connected through the UGREEN dock."
read -r -p "Press Enter to run the first complete boundary check. " _
verify_runtime first-install

say "Removing the complete first installation."
cleanup_prototype 2>&1 | tee "$EVIDENCE_DIR/first-uninstall.txt"
audit_absence
record "complete_uninstall=passed"

say "Performing a clean reinstall from the same built artifact."
install_daemon 2>&1 | tee "$EVIDENCE_DIR/clean-reinstall.txt"
verify_runtime clean-reinstall
record "clean_reinstall=passed"

say "Performing final cleanup."
cleanup_prototype 2>&1 | tee "$EVIDENCE_DIR/final-uninstall.txt"
audit_absence
record "final_cleanup=passed"
record "prototype_verdict=legacy-launchdaemon-viable"
CLEANUP_FINISHED=1

say "Probe complete. Return this evidence directory for review:"
say "$EVIDENCE_DIR"
