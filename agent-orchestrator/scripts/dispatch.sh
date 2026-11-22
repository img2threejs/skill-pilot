#!/bin/zsh
# Run one external agent for an orchestrated round and capture evidence.
#
# dispatch.sh --round <round_dir> --label <name> --agent codex|pi --model <id> [--effort low|medium|high|xhigh]
#             --access write|read [--via herdr|exec] --cwd <git_dir> --brief <file> --phase <phase> [--timeout <sec>] [--resume <label>]
#             [--stall <min>] [--herdr-home <label>] [--il <project_root>]
# dispatch.sh --round <round_dir> --close <label>
# dispatch.sh --decide --round <round_dir> --label <label> --of <labels> --verdict <verdict>
#             --findings <n> --accepted <n> [--note <text>]
# Herdr launches require --il or HERDR_IL_PATH. Missing both gives HERDR_IL_REQUIRED (exit 2).
#
# Writes <round_dir>/runs/<label>.{log,out.md,kv}. The .kv file holds key=value lines for
# agent-audit/log-run.sh. Dispatch logs each final run and each decision through that writer.
# exit: 0 ran (check outcome in .kv), 2 bad usage.
# Read-mode checks use TMPDIR (<round_dir>/runs/<label>.tmp); pi also needs two lock directories.
# Read-mode snapshots exclude ignored files and the cache directories below.
set -u
zmodload zsh/zutil zsh/datetime
skill_dir=${0:A:h:h}
zparseopts -D -E -F -A o -round: -label: -agent: -model: -effort: -access: -via: -cwd: -brief: -phase: -timeout: -resume: -close: -herdr-home: -il: -stall: -decide -of: -verdict: -findings: -accepted: -note: || exit 2
il=${o[--il]:-${HERDR_IL_PATH:-}}
valid_label() {
  local LC_ALL=C
  [[ $1 == [A-Za-z0-9]* && $1 != *[^A-Za-z0-9._-]* ]]
}

valid_model() {
  local LC_ALL=C
  [[ $1 == [A-Za-z0-9]* && $1 != *[^A-Za-z0-9._:/-]* ]]
}

valid_round() {
  [[ $1 != *[[:cntrl:]]* ]] && valid_label "${1:a:t}"
}

usage_error() {
  print -ru2 -- "invalid $1: $2"
  return 2
}

kv_value() {
  sed -n "s/^$2=//p" "$1" | tail -n 1
}

audit_writer() {
  local writer=${DISPATCH_AUDIT_DIR:-${il:-${round:h:h:h}}/agent-audit}/log-run.sh
  if [[ -z ${DISPATCH_AUDIT_DIR:-} && ${round:h:t} == rounds ]]; then
    writer=${round:h:h}/log-run.sh
    [[ -x $writer ]] || writer=${il:-${round:h:h:h}}/agent-audit/log-run.sh
  fi
  print -r -- "$writer"
}

audit_row() {
  local writer=$1
  shift
  if [[ ! -x $writer ]]; then
    print -ru2 -- "$label: AUDIT_WRITER_MISSING: $writer"
    return 127
  fi
  "$writer" "$@" || { print -ru2 -- "$label: AUDIT_WRITE_FAILED"; return 1; }
}

with_record_lock() (
  local record=$1 handler=$2 lock_fd
  shift 2
  # Keep a stable lock inode and pass its descriptor to the writer across exec.
  exec {lock_fd}>> "$record.lock" && flock -x "$lock_fd" && "$handler" "$record" "$@"
  # Propagate the handler's status when called from the run's EXIT trap.
  exit $?
)

append_record_fields() {
  local record=$1
  shift
  print -rl -- "$@" >> "$record"
}

audit_record_pending() {
  local recorded_outcome
  [[ -f $1 && ! -L $1 && $(kv_value "$1" audited) != 1 ]] || return 1
  recorded_outcome=$(kv_value "$1" outcome)
  [[ -n $recorded_outcome && $recorded_outcome != running ]]
}

audit_record_locked() {
  local record=$1 writer=$2 label=${1:t:r} ledger=${2:h}/runs.jsonl ledger_status
  local -a fields
  audit_record_pending "$record" || return 0
  if [[ -e $ledger ]]; then
    # A previous process can die after append but before marking the record.
    jq -Ren --arg round "${round:t}" --arg label "$label" '
      first(inputs | fromjson? | objects | select(.round == $round and .agent != "orchestrator" and
        ((.label // "") == $label or ((.label // "") == "" and
          ((.note // "") | startswith("label=" + $label + " ")))))) | true
    ' "$ledger" >/dev/null
    ledger_status=$?
    case $ledger_status in
      0) append_record_fields "$record" audited=1; return ;;
      4) ;;
      *) return 1 ;;
    esac
  fi
  fields=("${(@f)$(<"$record")}")
  audit_row "$writer" "${fields[@]}" && append_record_fields "$record" audited=1
}

audit_run_record() {
  local record=$1 writer=$2
  audit_record_pending "$record" || return 0
  if ! with_record_lock "$record" audit_record_locked "$writer"; then
    print -ru2 -- "${record:t:r}: AUDIT_PENDING"
  fi
}

sweep_audit_records() {
  local record writer
  writer=$(audit_writer)
  for record in "$round"/runs/*.kv(N); do
    audit_run_record "$record" "$writer"
  done
}

record_decision() {
  local round label=${o[--label]:-} verdict=${o[--verdict]:-}
  local references=${o[--of]:-} findings=${o[--findings]:-} accepted=${o[--accepted]:-}
  local note=${o[--note]:-} decision_model=${DISPATCH_ORCHESTRATOR_MODEL:-unknown} verified record ref key
  local -Ua records
  for key in "${(@k)o}"; do
    case $key in
      --decide|--round|--label|--of|--verdict|--findings|--accepted|--note) ;;
      *) print -ru2 -- "unexpected decision option: $key"; return 2 ;;
    esac
  done
  if (( $# )) || [[ -z ${o[--round]:-} || -z $references ]] ||
     [[ $findings != <-> || $accepted != <-> ]] || (( accepted > findings )); then
    print -ru2 -- 'usage: dispatch.sh --decide --round <round_dir> --label <label> --of <labels> --verdict merge|send-back|accept|reject --findings N --accepted N [--note text]'
    return 2
  fi
  round=${o[--round]:a}
  valid_round "${o[--round]}" || { usage_error --round 'expected a safe round directory name'; return 2; }
  valid_label "$label" || { usage_error --label 'expected a safe identifier'; return 2; }
  valid_model "$decision_model" || { usage_error DISPATCH_ORCHESTRATOR_MODEL 'expected a safe model identifier'; return 2; }
  if [[ $note == *[[:cntrl:]]* || $note =~ '^[[:space:]]*=' ]]; then
    usage_error --note 'expected plain single-line text without a leading equals sign'
    return 2
  fi
  case $verdict in
    merge|accept) verified=true ;;
    send-back|reject) verified=false ;;
    *) usage_error --verdict "expected merge, send-back, accept or reject"; return 2 ;;
  esac
  for ref in "${(@s:,:)references}"; do
    valid_label "$ref" || { usage_error --of 'expected comma-separated run identifiers'; return 2; }
    records+=("$round/runs/$ref.kv")
  done
  sweep_audit_records
  for record in "${records[@]}"; do
    ref=${record:t:r}
    if [[ ! -f $record || -L $record || ! -w $record ]]; then
      print -ru2 -- "invalid or unwritable run record: $ref"
      return 2
    fi
    if [[ $(kv_value "$record" outcome) == running ]]; then
      print -ru2 -- "run still in progress: $ref"
      return 2
    fi
  done
  audit_row "$(audit_writer)" "round=${round:t}" "label=$label" "phase=adjudicate" "agent=orchestrator" \
    "model=$decision_model" "outcome=$verdict" "verdict=$verdict" "of=$references" \
    "secs=0" "exit=0" "verified_done=$verified" "findings=$findings" "findings_accepted=$accepted" \
    "note=label=$label of=$references verdict=$verdict${note:+ $note}" || return 1
  for record in "${records[@]}"; do
    if ! with_record_lock "$record" append_record_fields "verified_done=$verified" "findings_accepted=$accepted"; then
      print -ru2 -- "$label: decision logged, but could not update $record"
      return 1
    fi
  done
  print -r -- "$label: $verdict"
}

if (( ${+o[--decide]} )); then
  record_decision "$@"
  exit $?
fi
for k in of verdict findings accepted note; do
  (( ! ${+o[--$k]} )) || { print -ru2 -- "--$k requires --decide"; exit 2; }
done

tab_matches() {
  jq -e --arg id "$1" --arg ws "$2" --arg label "$3" '
    .result.tab | .tab_id == $id and .workspace_id == $ws and .label == $label and
    .number > 1 and .pane_count == 1' >/dev/null
}

pane_matches_tab() {
  jq -e --arg id "$1" --arg ws "$2" --arg pane "$3" '
    .result.pane | .tab_id == $id and .workspace_id == $ws and .pane_id == $pane' >/dev/null
}

close_dispatch_tab() {
  local id=$1 ws=$2 tab_name=$3 tab_pane=${4-} result
  if result=$(herdr tab get "$id" 2>&1); then
    if ! tab_matches "$id" "$ws" "$tab_name" <<< "$result" ||
       { (( $# == 4 )) && {
         [[ -z $tab_pane ]] || ! result=$(herdr pane get "$tab_pane" 2>&1) ||
           ! pane_matches_tab "$id" "$ws" "$tab_pane" <<< "$result"
       }; }; then
      print -r -- 'HERDR_TAB_IDENTITY_CHANGED'
      return 1
    fi
    result=$(herdr tab list --workspace "$ws" 2>&1) || { print -r -- "$result"; return 1; }
    # Herdr closes the workspace with its last tab. The original shell tab is never a run tab.
    if ! jq -e --arg id "$id" '.result.tabs |
      any(.tab_id == $id) and any(.number == 1 and .tab_id != $id)' <<< "$result" >/dev/null; then
      print -r -- 'HERDR_HOME_ANCHOR_MISSING'
      return 1
    fi
    if result=$(herdr tab close "$id" 2>&1); then
      print -r -- "$result"
      return 0
    fi
  fi
  if [[ $(jq -r '.error.code // empty' <<< "$result" 2>/dev/null) == tab_not_found ]]; then
    print -r -- 'tab already closed'
    return 0
  fi
  print -r -- "$result"
  return 1
}

if (( ${+o[--close]} )); then
  label=${o[--close]}
  [[ -n ${o[--round]:-} ]] && valid_round "${o[--round]}" && valid_label "$label" && (( ${#o} == 2 )) || {
    echo "usage: dispatch.sh --round <round_dir> --close <label>" >&2; exit 2
  }
  round=${o[--round]:a}
  sweep_audit_records
  record=$round/runs/$label.kv
  if [[ -f $record && $(kv_value "$record" outcome) == running ]]; then
    print -ru2 -- "$label: run still in progress"
    exit 2
  fi
  [[ -f $record ]] && tab=$(kv_value "$record" herdr_tab) && [[ -n $tab ]] || {
    echo "$label: no recorded herdr tab" >&2; exit 2
  }
  if [[ $(kv_value "$record" herdr_closed) == 1 ]]; then
    echo "$label: tab already closed"
    exit 0
  fi
  recorded_pane=$(kv_value "$record" herdr_pane)
  pane_arg=()
  [[ -n $recorded_pane ]] && pane_arg=("$recorded_pane")
  if result=$(close_dispatch_tab "$tab" "$(kv_value "$record" herdr_workspace)" \
    "$(kv_value "$record" herdr_tab_label)" "${pane_arg[@]}"); then
    with_record_lock "$record" append_record_fields herdr_closed=1 || exit 2
    if [[ $result == 'tab already closed' ]]; then
      echo "$label: tab already closed"
    else
      echo "$label: tab closed"
    fi
  else
    print -ru2 -- "$label: tab close failed: $result"
    exit 1
  fi
  exit 0
fi
for k in round label agent model access cwd brief phase; do [[ -n ${o[--$k]:-} ]] || { echo "missing --$k" >&2; exit 2; }; done
round=${o[--round]:a} label=${o[--label]} agent=${o[--agent]} model=${o[--model]} effort=${o[--effort]:-medium}
mode=${o[--access]} via=${o[--via]-herdr} cwd=${o[--cwd]:a} phase=${o[--phase]} tmo=${o[--timeout]:-1200}
valid_round "${o[--round]}" || { usage_error --round 'expected a safe round directory name'; exit 2; }
valid_label "$label" || { usage_error --label 'expected a safe identifier'; exit 2; }
valid_label "$phase" || { usage_error --phase 'expected a safe identifier'; exit 2; }
valid_label "$effort" || { usage_error --effort 'expected a safe identifier'; exit 2; }
valid_model "$model" || { usage_error --model 'expected a safe model identifier'; exit 2; }
if (( ${+o[--resume]} )) && ! valid_label "${o[--resume]}"; then
  usage_error --resume 'expected a safe run identifier'
  exit 2
fi
[[ ${o[--cwd]} != *[[:cntrl:]]* && ${cwd:A} != *[[:cntrl:]]* ]] || { usage_error --cwd 'expected a path without control characters'; exit 2; }
case $agent in codex|pi) ;; *) usage_error --agent 'expected codex or pi'; exit 2 ;; esac
case $mode in read|write) ;; *) usage_error --access 'expected read or write'; exit 2 ;; esac
case $via in exec|herdr) ;; *) usage_error --via 'expected exec or herdr'; exit 2 ;; esac
if [[ $via == herdr ]]; then
  stall_min=${o[--stall]:-${DISPATCH_STALL_MIN:-8}}
  if [[ $stall_min != <-> && $stall_min != <->.<-> ]] || (( stall_min <= 0 )); then
    print -ru2 -- 'stall interval must be a positive number of minutes'
    exit 2
  fi
  stall_secs=$(( stall_min * 60.0 ))
  stall_poll=$(( stall_secs < 4 ? stall_secs / 4 : 1.0 ))
  [[ -n $il ]] || { print -ru2 -- "$label: HERDR_IL_REQUIRED: pass --il <project_root> or set HERDR_IL_PATH"; exit 2; }
  [[ $il != *[[:cntrl:]]* && ${il:A} != *[[:cntrl:]]* ]] ||
    { usage_error --il 'expected a path without control characters'; exit 2; }
fi
[[ -f "${o[--brief]}" && -s "${o[--brief]}" ]] || { echo "missing or empty brief: ${o[--brief]}" >&2; exit 2; }
brief="$(<"${o[--brief]}")"
repo_top=$(git -C "$cwd" rev-parse --show-toplevel 2>/dev/null) || { echo "not a git work tree: $cwd" >&2; exit 2; }
sweep_audit_records
base=$round/runs/$label; log=$base.log; out=$base.out.md; record_tmp=$base.kv.$$
[[ ! -e $base.kv ]] || { echo "label already used: $label" >&2; exit 2; }
mkdir -p "$round/runs" || exit 2
if [[ $agent == pi ]]; then
  effort=-
  tmo=${o[--timeout]:-1500}
fi

export PYTHONDONTWRITEBYTECODE=1
# ponytail: cache dirs excluded by name; add a pattern when another tool's cache shows up as a false edit
nocache=(':(exclude,glob)**/__pycache__/**' ':(exclude,glob)**/.pytest_cache/**' ':(exclude,glob)**/node_modules/.cache/**')
snapshot() {
  local file root
  root=$(git -C "$1" rev-parse --show-toplevel) || return 1
  shift
  local -a paths=(. "${nocache[@]}" "$@")
  git -C "$root" rev-parse --verify HEAD 2>/dev/null
  git --no-optional-locks -C "$root" status --porcelain=v1 --untracked-files=all -- "${paths[@]}"
  git -C "$root" diff -- "${paths[@]}" | shasum
  git -C "$root" diff --cached -- "${paths[@]}" | shasum
  git -C "$root" ls-files --others --exclude-standard -z -- "${paths[@]}" |
    while IFS= read -r -d '' file; do
      if [[ -L $root/$file ]]; then
        readlink "$root/$file" | shasum
      elif [[ -f $root/$file ]]; then
        git -C "$root" hash-object --no-filters -- "$file"
      fi
    done
}
# ponytail: path+size+mtime+inode via one stat pass (a per-file shasum took minutes on ~15k npm files);
# a same-size edit that also restores mtime escapes, but the sandbox already denies these writes.
snapshot_pi_state() (
  [[ -d $1 ]] || return 0
  cd -- "$1" || return 1
  find . \( -path ./sessions -o -path ./auth.json -o -path ./models-store.json -o -name '*.lock' \) -prune \
    -o \( -type f -o -type l \) -print0 | xargs -0 stat -f '%N %z %m %i' | LC_ALL=C sort | shasum
)
st=$(date +%s); rc=0; real_model=$model; where=$cwd; detail=; workspace=; tab=; tab_label=$label; pane=; branch=; trust_accepted=
scratch= events= stalled= transcript= mcp_builtin_on= mcp_failure= pane_exited= response= run_pid=
resume=${o[--resume]:-} target=dispatch-$st-$$ herdr_closed= herdr_started= closed_idle= creating_tab=
requested_model=$model
[[ $agent == pi && $model != */* ]] && requested_model=minimax/$model

codex_mcp_flags() {
  local listing names name candidate toml_python= list_rc=0 LC_ALL=C
  mcp_args=()
  listing=$(cd -- "$where" && timeout -k 5 60 codex mcp list --json < /dev/null) || {
    list_rc=$?
    # A failed listing may be caused by invalid config. Still parse the files for a cause.
    listing='[]'
  }
  for candidate in python3 python3.14 python3.13 python3.12 python3.11; do
    if "$candidate" -c 'import tomllib' 2>/dev/null; then
      toml_python=$candidate
      break
    fi
  done
  if [[ -z $toml_python ]]; then
    echo "Python 3.11 or later is required to parse Codex MCP config" >&2
    mcp_failure=tomllib-unavailable
    return 1
  fi
  # Codex layers every .codex/config.toml from the repo top down to the cwd; collect them all.
  local project_configs=() dir=${where:A} top
  top=$(git -C "$where" rev-parse --show-toplevel 2>/dev/null) && top=${top:A} || top=$dir
  while :; do
    project_configs+=("$dir/.codex/config.toml")
    [[ $dir == "$top" || $dir == / ]] && break
    dir=${dir:h}
  done
  names=$(printf '%s\n' "$listing" | "$toml_python" -c '
import json
import re
import sys
import tomllib


def fail(cause, message):
    print(cause)
    sys.exit(message)


def report_exception(kind, error, traceback):
    print(kind.__name__)
    sys.__excepthook__(kind, error, traceback)


sys.excepthook = report_exception


def declared_servers(path):
    try:
        with open(path, "rb") as config:
            servers = tomllib.load(config).get("mcp_servers", {})
    except FileNotFoundError:
        return set()
    return {name for name, server in servers.items() if isinstance(server, dict)}


listing = json.load(sys.stdin)
if not isinstance(listing, list):
    fail("invalid-mcp-list", "expected an MCP server list")
home_servers = declared_servers(sys.argv[1])
# Project tables may only become visible to Codex after folder trust.
names_to_disable = set()
for project_config in sys.argv[2:]:
    names_to_disable |= declared_servers(project_config)
builtins_on = []
for server in listing:
    if server.get("enabled") is not True:
        continue
    name = server["name"]
    if name in home_servers or name in names_to_disable:
        names_to_disable.add(name)
    elif name in ("codex_app", "cua_repl"):
        builtins_on.append(name)
    else:
        fail("unknown-enabled-server", f"unknown enabled MCP server: {name!r}")
names_to_disable = sorted(names_to_disable)
for name in names_to_disable:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
        fail("unsafe-server-name", f"unsafe MCP server name: {name!r}")
for name in names_to_disable:
    print(name)
if builtins_on:
    print("MCP_BUILTIN_ON=" + ",".join(builtins_on))
' "${CODEX_HOME:-$HOME/.codex}/config.toml" "${project_configs[@]}") || {
    mcp_failure=${names//[^A-Za-z0-9_.:-]/}
    mcp_failure=${mcp_failure[1,60]:-mcp-parser-failed}
    return 1
  }
  if (( list_rc != 0 )); then
    mcp_failure=mcp-list-exit:$list_rc
    return 1
  fi
  for name in "${(@f)names}"; do
    case $name in
      MCP_BUILTIN_ON=*) mcp_builtin_on=$name ;;
      ?*) mcp_args+=(-c "mcp_servers.$name.enabled=false") ;;
    esac
  done
  return 0
}

snapshot_siblings() {
  local entry sibling git_dir git_common_dir ref
  siblings=()
  for entry in "$il"/*/.git(DN); do
    sibling=${entry:h}
    [[ ${sibling:A} == "$repo_top" || ${sibling:A} == "$where" || ${sibling:A} == "$round_repo" ]] && continue
    siblings[$sibling]=
    if [[ $1 == after ]]; then
      (( ${+siblings_before[$sibling]} && ! ${+skipped_siblings[$sibling]} )) || continue
    elif [[ -f $entry ]] &&
       git_dir=$(git -C "$sibling" rev-parse --absolute-git-dir 2>/dev/null) &&
       git_common_dir=$(git -C "$sibling" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) &&
       [[ $git_common_dir != "$git_dir" ]]; then
      if ref=$(git -C "$sibling" symbolic-ref -q HEAD 2>/dev/null); then
        [[ $ref == refs/heads/agent/* ]] && skipped_siblings[$sibling]=1
      elif [[ $? == 1 && ${sibling:t} == *-rv-* ]]; then
        skipped_siblings[$sibling]=1
      fi
      if (( ${+skipped_siblings[$sibling]} )); then
        continue
      fi
    fi
    siblings[$sibling]=$(snapshot "$sibling")
  done
}

stage_run_record() {
  local -a fields=("round=${round:t}" "repo=${repo_top:t}" "label=$label" "phase=$phase" "agent=$agent"
    "model=$real_model" "effort=$effort" "launcher=$via" "access=$mode" "where=$where"
    "secs=$secs" "exit=$1" "outcome=$outcome" "note=$note")
  [[ -n $stalled ]] && fields+=("code=STALLED")
  [[ -n $branch ]] && fields+=("branch=$branch")
  if [[ -n $tab ]]; then
    fields+=("herdr_workspace=$workspace" "herdr_tab=$tab" "herdr_tab_label=$tab_label"
      "herdr_agent=$target" "herdr_started=$herdr_started")
    [[ -n $pane ]] && fields+=("herdr_pane=$pane")
    [[ $mode == write ]] && fields+=("herdr_source=$repo_top")
  fi
  [[ -n $resume ]] && fields+=("resumed_from=$resume")
  [[ -n $herdr_closed ]] && fields+=("herdr_closed=$herdr_closed")
  # Tool responses and filesystem-derived diagnostics are also confined to one record line.
  print -rl -- "${(@)fields//[[:cntrl:]]/ }" > "$record_tmp"
}

publish_run_record() {
  if ! mv -f -- "$record_tmp" "$base.kv"; then
    rm -f -- "$record_tmp"
    print -ru2 -- "$label: RUN_RECORD_WRITE_FAILED"
    return 1
  fi
}

write_running_record() {
  stage_run_record '' && publish_run_record
}

finish_run() {
  trap '' INT TERM
  if (( $1 != 0 )) || [[ $outcome == running ]]; then
    rc=$1
    outcome=error
    note="$note ${detail:-SETUP_FAILED}$closed_idle"
  fi
  secs=$(( $(date +%s) - st ))
  stage_run_record "$rc" && publish_run_record || return 1
  audit_run_record "$base.kv" "$(audit_writer)"
  print -r -- "$label: $outcome${stalled:+ (STALLED)} rc=$rc ${secs}s model=$real_model where=$where out=$out"
}

refuse_resume() {
  if [[ -n $response ]]; then rm -f -- "$response"; fi
  workspace= tab= pane=
  detail="RESUME_REFUSED:$1"
  print -ru2 -- "$label: RESUME_REFUSED:$1"
  exit 2
}

read_created_tab() {
  local candidate pane_info
  tab=$(jq -r --arg ws "$workspace" --arg label "$tab_label" '
    .result.tab | objects | select(.workspace_id == $ws and .label == $label and .number > 1) |
    .tab_id | strings | select(length > 0)' "$response" 2>/dev/null)
  [[ -n $tab ]] || return
  candidate=$(jq -r --arg ws "$workspace" --arg tab "$tab" '
    .result.root_pane | objects | select(.workspace_id == $ws and .tab_id == $tab) |
    .pane_id | strings | select(length > 0 and (test("[[:space:]]") | not))' "$response" 2>/dev/null)
  pane=
  if [[ -n $candidate ]] && pane_info=$(herdr pane get "$candidate" 2>> "$log") &&
     pane_matches_tab "$tab" "$workspace" "$candidate" <<< "$pane_info"; then
    pane=$candidate
  fi
}

read_herdr_log() {
  # herdr pane read prints plain text, not JSON (measured)
  herdr pane read "$pane" --source recent --lines 400 >> "$log" 2>&1
}

close_herdr_tab() {
  local result
  local -a pane_target=()
  if [[ -n $tab && -z $herdr_closed ]]; then
    # A fresh tab receipt identifies the tab even if it omitted a usable root pane.
    if [[ -n $pane || -n $resume ]]; then pane_target=("$pane"); fi
    if result=$(close_dispatch_tab "$tab" "$workspace" "$tab_label" "${pane_target[@]}"); then
      herdr_closed=1
    else
      detail="$detail HERDR_CLOSE_FAILED"
      (( rc == 0 )) && rc=1
    fi
    print -r -- "$result" >> "$log"
  fi
}

extract_pi_report() {
  # A timeout can leave an incomplete JSON line.
  if [[ -f $events ]] && ! jq -Rnr '[inputs | fromjson? | select(.type == "message_end" and .message.role == "assistant")
    | [.message.content[]? | select(.type == "text") | .text] | join("") | select(length > 0)]
    | join("\n\n") | select(length > 0)' "$events" > "$out" 2>> "$log"; then
    (( rc == 0 )) && rc=1
    detail="$detail PI_REPORT_EXTRACTION_FAILED"
  fi
  if [[ ! -s $out ]]; then
    (( rc == 0 )) && rc=1
    detail="$detail NO_REPORT"
  fi
}

save_reader_report() {
  if [[ -n $events ]]; then
    extract_pi_report
  elif [[ -n $scratch && -s $scratch/REPORT.md && ! -s $out ]]; then
    if ! mv -- "$scratch/REPORT.md" "$out"; then
      (( rc == 0 )) && rc=1
      detail="$detail REPORT_MOVE_FAILED"
    fi
  fi
  if (( rc != 0 )) && [[ -s $out && $detail != *PARTIAL_REPORT* ]]; then
    [[ $detail == NO_REPORT ]] && detail=
    detail="$detail PARTIAL_REPORT"
  fi
}

abort_run() {
  trap '' INT TERM
  rc=$1
  [[ -n $run_pid ]] && kill "$run_pid" 2>/dev/null
  if [[ -n $creating_tab && -s $response ]]; then
    read_created_tab
    if [[ -n $tab && -z $pane ]]; then detail=HERDR_TAB_NO_PANE; fi
  fi
  if [[ -n $pane ]]; then
    herdr pane send-keys "$pane" ctrl+c >> "$log" 2>&1 || detail="$detail HERDR_INTERRUPT_FAILED"
    read_herdr_log
  fi
  if [[ $mode == read ]]; then save_reader_report; fi
  close_herdr_tab
  detail="ABORTED${detail:+ ${detail# }}"
  if [[ -n $response && -s $response.err ]]; then cat "$response.err" >> "$log"; fi
  [[ -n $response ]] && rm -f -- "$response" "$response.err" "$base.launch"
  [[ -n $scratch ]] && rm -rf -- "$scratch"
  exit "$1"
}

herdr_pane_input_fits() {
  local LC_ALL=C line
  for line in "${(@f)1}"; do
    # Allow for Herdr's bracketed-paste delimiters and Enter.
    (( ${#line} + 13 < 1024 )) || return 1
  done
}

herdr_agent_start_fits() {
  local LC_ALL=C command=$1 arg quote_escape="'\\''"
  shift
  for arg in "$@"; do
    if [[ -z $arg || $arg == -* || $arg == *[^A-Za-z0-9_./:+=-]* ]]; then
      arg="'${arg//\'/$quote_escape}'"
    fi
    command+=" $arg"
  done
  herdr_pane_input_fits "$command"
}

find_run_transcript() {
  local session marker
  while IFS= read -r -d '' session; do
    if marker=$(grep -Fn -m1 -e "\"$json_marker\"" -e "\\n$json_marker\"" -e "\\n$json_marker\\n" -e "\"$json_marker\\n" -- "$session") ||
       marker=$(grep -Fnx -m1 -- "$run_marker" "$session"); then
      transcript=$session
      transcript_marker_line=${marker%%:*}
      return 0
    fi
  done < <(find "$session_root" -type f -name "$session_glob" -newer "$base.launch" -print0 2>/dev/null)
  return 1
}

wait_for_herdr_progress() {
  local fingerprint= previous= pane_text source
  local -F last_progress=$SECONDS
  while kill -0 "$run_pid" 2>/dev/null; do
    source=$events
    if [[ -z $source ]]; then
      [[ -n $transcript ]] || find_run_transcript
      source=$transcript
    fi
    if [[ -n $source ]] && fingerprint=$(stat -f 'file:%m:%z' -- "$source" 2>/dev/null); then
      :
    elif pane_text=$(timeout -k 1 2 herdr pane read "$pane" --source recent --lines 40 2>/dev/null); then
      case ${(L)pane_text} in
        ''|working) fingerprint= ;;
        *) fingerprint="pane:$(print -rn -- "$pane_text" | shasum)" ;;
      esac
    else
      fingerprint=
    fi
    if [[ -n $fingerprint && $fingerprint != "$previous" ]]; then
      previous=$fingerprint
      last_progress=$SECONDS
    fi
    if (( SECONDS - last_progress >= stall_secs && SECONDS < deadline )) &&
       kill -0 "$run_pid" 2>/dev/null; then
      stalled=1
      kill "$run_pid" 2>/dev/null
      break
    fi
    sleep "$stall_poll"
  done
}

call_herdr() {
  local error_code='.error?.code? | strings | select(length > 0)'
  if [[ $1 == pane && ( $2 == run || $2 == send-text ) ]] && ! herdr_pane_input_fits "$4"; then
    : > "$response"
    herdr_rc=1 herdr_error=HERDR_PANE_INPUT_TOO_LONG
    return
  fi
  # The shell's wait builtin lets INT and TERM interrupt a pending request.
  if [[ $1 == tab && $2 == create ]]; then
    # Keep the creation response available to the signal trap for cleanup.
    ( trap '' INT TERM; herdr "$@" ) > "$response" 2> "$response.err"
    herdr_rc=$?
  else
    herdr "$@" > "$response" 2> "$response.err" &
    run_pid=$!
    local watch_progress=
    if [[ $1 == agent && $2 == prompt || $1 == pane && $2 == wait-output ]]; then
      watch_progress=1
      wait_for_herdr_progress
    fi
    wait "$run_pid"
    herdr_rc=$? run_pid=
    if [[ -n $watch_progress && -n $stalled ]]; then
      herdr_error=STALLED
      rm -f -- "$response.err"
      return
    fi
  fi
  cat "$response.err" >> "$log"
  herdr_error=$(jq -nr "first(inputs | $error_code)" "$response" 2>/dev/null)
  if [[ -z $herdr_error && -s $response.err ]]; then
    herdr_error=$(jq -nr "first(inputs | $error_code)" "$response.err" 2>/dev/null)
    if [[ -z $herdr_error ]]; then
      herdr_error=$(jq -Rnr "first(inputs | fromjson? | $error_code)" "$response.err" 2>/dev/null)
    fi
  fi
  rm -f -- "$response.err"
  if (( herdr_rc != 0 )) && [[ -z $herdr_error ]]; then herdr_error=HERDR_COMMAND_FAILED; fi
}

ensure_herdr_home() (
  zmodload zsh/system || return 1
  local state_dir=${DISPATCH_HERDR_STATE_DIR:-$skill_dir/state}
  local state_file lock owner own_lock anchor listing saved created id state project_hash pending
  local -a owners
  local -i start=$SECONDS stale_after=15 mtime status_code
  state_dir=${state_dir:A}
  anchor=$state_dir
  while [[ ! -d $anchor ]]; do anchor=${anchor:h}; done
  if git -C "$anchor" rev-parse --git-dir >/dev/null 2>&1; then
    print -ru2 -- 'HERDR_HOME_STATE_IN_REPO'
    return 1
  fi
  umask 077
  mkdir -p -- "$state_dir" || return 1
  state_file=$state_dir/herdr-home.json
  lock=$state_file.lock
  own_lock=$lock/$sysparams[pid]

  # Defer interruption of the transaction. Caught traps are reset for the timeout and its CLI.
  trap ':' INT TERM
  while ! mkdir -- "$lock" 2>/dev/null; do
    if (( SECONDS - start >= 30 )); then
      print -ru2 -- 'HERDR_HOME_LOCK_TIMEOUT'
      return 1
    fi
    mtime=$(stat -f %m -- "$lock" 2>/dev/null) || continue
    if (( EPOCHSECONDS - mtime >= stale_after )); then
      owners=("$lock"/<->(N/))
      if (( ! ${#owners} )) &&
         mtime=$(stat -f %m -- "$lock" 2>/dev/null) && (( EPOCHSECONDS - mtime >= stale_after )); then
        rmdir -- "$lock" 2>/dev/null
      elif (( ${#owners} == 1 )); then
        owner=$owners[1]
        if ! kill -0 "${owner:t}" 2>/dev/null; then
          rm -f -- "$owner/home.json"
          if rmdir -- "$owner" 2>/dev/null; then rmdir -- "$lock" 2>/dev/null; fi
        fi
      fi
    fi
    sleep .1
  done
  if ! mkdir -- "$own_lock"; then rmdir -- "$lock"; return 1; fi
  trap 'rm -f -- "$own_lock/home.json"; if rmdir -- "$own_lock"; then rmdir -- "$lock"; fi' EXIT
  owners=("$lock"/<->(N/))
  (( ${#owners} == 1 )) || return 1
  listing=$(timeout -k 2 10 herdr workspace list) || {
    status_code=$?
    case $status_code in
      124|130|137|143) return $status_code ;;
      *) return 1 ;;
    esac
  }
  jq -e '.result.workspaces | type == "array"' <<< "$listing" >/dev/null || return 1
  state='{}'
  if [[ -e $state_file || -L $state_file ]]; then
    if [[ ! -f $state_file || ! -r $state_file || -L $state_file ]]; then
      print -ru2 -- 'HERDR_HOME_STATE_UNREADABLE'
      return 1
    fi
    state=$(jq -sce 'select(length == 1) | .[0] | objects' "$state_file" 2>/dev/null) || state='{}'
  fi
  saved=$(jq -c --arg cwd "$il" '.[$cwd] // null' <<< "$state") || return 1
  id=$(jq -r --argjson saved "$saved" --arg cwd "$il" '
    select(($saved | type) == "object" and $saved.cwd == $cwd) |
    .result.workspaces[] | select(.workspace_id == $saved.workspace_id and .label == $saved.label) |
    .workspace_id | strings | select(length > 0)' <<< "$listing") || return 1
  if [[ -n $id ]]; then print -r -- "$saved"; return 0; fi

  # A create can succeed on the server even if dispatch never saves its receipt.
  project_hash=$(print -rn -- "$il" | shasum) || return 1
  pending=$state_dir/herdr-home.pending.${project_hash%% *}
  if [[ -e $pending || -L $pending ]]; then
    print -ru2 -- "HERDR_HOME_CREATE_UNCERTAIN: $pending"
    return 3
  fi
  mkdir -- "$pending" || return 1
  created=$(timeout -k 2 10 herdr workspace create --cwd "$il" --label "$home_label" --no-focus) || {
    status_code=$?
    case $status_code in
      124|130|137|143) return $status_code ;;
      *) print -ru2 -- 'HERDR_HOME_CREATE_FAILED'
         return 1 ;;
    esac
  }
  id=$(jq -er --arg label "$home_label" '
    .result.workspace | select(.label == $label) | .workspace_id | strings | select(length > 0)' <<< "$created") || return 1
  saved=$(jq -nc --arg cwd "$il" --arg id "$id" --arg label "$home_label" --arg created_at "$(date -u +%FT%TZ)" '
    {workspace_id:$id, label:$label, cwd:$cwd, created_at:$created_at}') || return 1
  jq --arg cwd "$il" --argjson saved "$saved" '.[$cwd] = $saved' <<< "$state" > "$own_lock/home.json" &&
    mv -f -- "$own_lock/home.json" "$state_file" || return 1
  rmdir -- "$pending"
  print -r -- "$saved"
)

codex_turn_model() {
  jq -Rnr --arg id "${1:-}" '
    reduce inputs as $line ({};
      ($line | try fromjson catch null) as $event |
      if $event.type == "session_meta" then .id = $event.payload.id
      elif $event.type == "turn_context" then .model = $event.payload.model
      else . end)
    | select($id == "" or .id == $id) | .model | strings'
}

validate_resume_agent() {
  local session_id rollout live_model
  call_herdr tab get "$saved_tab"
  [[ $herdr_error != tab_not_found ]] || refuse_resume tab_gone
  [[ -z $herdr_error ]] || refuse_resume "$herdr_error"
  tab_matches "$saved_tab" "$saved_workspace" "$saved_tab_label" < "$response" || refuse_resume tab_changed
  call_herdr pane get "$saved_pane"
  pane_matches_tab "$saved_tab" "$saved_workspace" "$saved_pane" < "$response" || refuse_resume tab_changed
  call_herdr agent get "$saved_pane"
  jq -e --arg ws "$saved_workspace" --arg tab "$saved_tab" --arg pane "$saved_pane" --arg kind "$agent" \
    '.result.agent | .workspace_id == $ws and .tab_id == $tab and .pane_id == $pane and .agent == $kind' "$response" >/dev/null ||
    refuse_resume agent_missing
  jq -e '.result.agent.agent_status | . == "idle" or . == "done"' "$response" >/dev/null ||
    refuse_resume agent_not_idle
  [[ $agent == codex ]] || refuse_resume model_mismatch
  session_id=$(jq -er '.result.agent.agent_session | select(.agent == "codex" and .kind == "id") |
    .value | select(test("^[0-9a-fA-F-]{36}$"))' "$response" 2>/dev/null) || refuse_resume model_mismatch
  rollout=$(find "${CODEX_HOME:-$HOME/.codex}/sessions" -type f -name "rollout-*-$session_id.jsonl" -print -quit 2>/dev/null)
  [[ -n $rollout ]] || refuse_resume model_mismatch
  live_model=$(codex_turn_model "$session_id" < "$rollout")
  [[ $live_model == "$requested_model" ]] || refuse_resume model_mismatch
}

idle_writer_tab() {
  local id=$1 writer_ws=$2 writer_label=$3 writer_pane=$4
  call_herdr tab get "$id"
  [[ -z $herdr_error ]] && tab_matches "$id" "$writer_ws" "$writer_label" < "$response" || return 1
  call_herdr pane get "$writer_pane"
  [[ -z $herdr_error ]] && pane_matches_tab "$id" "$writer_ws" "$writer_pane" < "$response" || return 1
  call_herdr agent get "$writer_pane"
  [[ -z $herdr_error ]] &&
    jq -e --arg id "$id" --arg pane "$writer_pane" '.result.agent | .tab_id == $id and .pane_id == $pane and
      (.agent_status == "idle" or .agent_status == "done")' "$response" >/dev/null
}

outcome=running secs=0 note="label=$label via=$via mode=$mode"
trap 'finish_run $?' EXIT
trap 'abort_run 130' INT
trap 'abort_run 143' TERM
write_running_record || exit 2

if (( ${+o[--resume]} )); then
  [[ $mode == write ]] || refuse_resume read_access
  [[ $via == herdr ]] || refuse_resume not_herdr
  record=$round/runs/$resume.kv
  [[ -f $record ]] || refuse_resume run_not_found
  [[ $(kv_value "$record" outcome) != running ]] || refuse_resume run_in_progress
  [[ $(kv_value "$record" launcher) == herdr && $(kv_value "$record" access) == write ]] ||
    refuse_resume not_herdr_writer
  [[ $(kv_value "$record" agent) == "$agent" ]] || refuse_resume agent_mismatch
  [[ $(kv_value "$record" model) == "$requested_model" &&
     " $(kv_value "$record" note) " != *" MODEL_UNVERIFIED "* ]] || refuse_resume model_mismatch
  saved_workspace=$(kv_value "$record" herdr_workspace)
  saved_tab=$(kv_value "$record" herdr_tab)
  saved_tab_label=$(kv_value "$record" herdr_tab_label)
  saved_target=$(kv_value "$record" herdr_agent)
  saved_pane=$(kv_value "$record" herdr_pane)
  saved_where=$(kv_value "$record" where)
  saved_branch=$(kv_value "$record" branch)
  [[ -n $saved_tab && $(kv_value "$record" herdr_closed) != 1 ]] || refuse_resume tab_gone
  [[ -n $saved_workspace && -n $saved_tab_label ]] || refuse_resume tab_changed
  [[ -n $saved_target && -n $saved_pane ]] || refuse_resume agent_missing
fi

if [[ $via == herdr ]]; then
  home_label=${o[--herdr-home]:-${DISPATCH_HERDR_HOME:-img2}}
  il=${il:A} repo_top=${repo_top:A} cwd=${cwd:A} where=${cwd:A}
  [[ $repo_top == "${il%/}/"* && $cwd == "${il%/}/"* ]] || { echo "git work tree is outside il: $cwd" >&2; exit 2; }
  response=$base.herdr.json
  : > "$log"
  if [[ -n $resume ]]; then
    validate_resume_agent
    [[ $(kv_value "$record" herdr_source) == "$repo_top" ]] || refuse_resume source_mismatch
    [[ -n $saved_where && ${saved_where:A} == "$il/"* && -n $saved_branch ]] &&
      [[ $(git -C "$saved_where" branch --show-current 2>/dev/null) == "$saved_branch" &&
         $(git -C "$saved_where" rev-parse --path-format=absolute --git-common-dir 2>/dev/null) ==
         "$(git -C "$repo_top" rev-parse --path-format=absolute --git-common-dir)" ]] ||
      refuse_resume worktree_changed
    workspace=$saved_workspace tab=$saved_tab tab_label=$saved_tab_label
    target=$saved_target pane=$saved_pane where=$saved_where branch=$saved_branch
    herdr_started=$(kv_value "$record" herdr_started)
  else
    # Wait for the bounded transaction to record a successful create and release its lock.
    home_signal=0
    trap 'home_signal=130' INT
    trap 'home_signal=143' TERM
    home=$(ensure_herdr_home 2>> "$log")
    home_status=$?
    if (( home_signal )); then
      print -ru2 -- "$label: HERDR_HOME_TIMEOUT (interrupted during provisioning)"
      detail='ABORTED HERDR_HOME_TIMEOUT'
      exit "$home_signal"
    fi
    trap 'abort_run 130' INT
    trap 'abort_run 143' TERM
    case $home_status in
      0) workspace=$(jq -r '.workspace_id' <<< "$home") ;;
      124|130|137|143) rc=124; detail=HERDR_HOME_TIMEOUT ;;
      3) rc=1; detail=HERDR_HOME_CREATE_UNCERTAIN ;;
      *) rc=1; detail=HERDR_HOME_FAILED
         if grep -Fq -e 'Connection refused' -e '"server_not_running"' "$log"; then detail=HERDR_NOT_RUNNING; fi ;;
    esac
    if (( rc )); then print -ru2 -- "$label: $detail (see $log)"; fi
  fi
  rm -f -- "$response"
fi

scratch_args=(); pi_prefix=()
if [[ $mode == read ]] && (( rc == 0 )); then
  runs=$round/runs
  scratch_path=${runs:A}/$label.tmp
  [[ ! -e $scratch_path && ! -L $scratch_path ]] || { echo "stale tmp dir: $scratch_path" >&2; exit 2; }
  if [[ $agent == pi ]]; then
    sandbox_bin=${commands[sandbox-exec]:-}
    [[ -n $sandbox_bin ]] || { echo "sandbox-exec is required for pi read mode" >&2; exit 2; }
    sandbox_bin=${sandbox_bin:a}
    pi_state=${HOME:A}/.pi/agent
    case "$scratch_path$pi_state" in
      *\"*|*$'\n'*|*$'\r'*) echo "unsupported character in pi sandbox path" >&2; exit 2 ;;
    esac
  fi
  mkdir -- "$scratch_path" || exit 2
  scratch=$scratch_path
  if [[ $agent == pi ]]; then
    profile=$scratch/$label.sb
    cat > "$profile" <<EOF || { rm -rf -- "$scratch"; exit 2; }
(version 1)
(allow default)
(deny file-write*)
(allow file-write* (subpath "${scratch//\\/\\\\}")
  (subpath "${pi_state//\\/\\\\}/settings.json.lock")
  (subpath "${pi_state//\\/\\\\}/auth.json.lock")
  (literal "/dev/null") (literal "/dev/tty")
  (regex #"^/dev/fd/") (regex #"^/dev/ttys"))
EOF
    pi_prefix=("$sandbox_bin" -f "$profile")
    pi_before=$(snapshot_pi_state "$pi_state")
  fi
  scratch_args=(--add-dir "$scratch")
  before=$(snapshot "$where")
fi

if [[ $via == exec ]]; then
  [[ -n $scratch ]] && export TMPDIR=$scratch
  case $agent in
    codex) if codex_mcp_flags 2> "$log"; then
             timeout -k 30 $tmo codex exec --skip-git-repo-check -C $cwd -m $model -c model_reasoning_effort=$effort \
               "${mcp_args[@]}" -s workspace-write $scratch_args -o $out "$brief" < /dev/null >> $log 2>&1 &
             run_pid=$!
             wait "$run_pid"; rc=$? run_pid=
             detected_model=$(grep -m1 '^model:' $log | awk '{print $2}')
             if valid_model "$detected_model"; then real_model=$detected_model; else detail=MODEL_UNVERIFIED; fi
           else
             rc=1; detail=CODEX_MCP_LIST_FAILED:$mcp_failure
           fi ;;
    pi)    tools=(); [[ $mode == read ]] && tools=(--tools read,bash)
           real_model=$requested_model
           events=$base.events.jsonl
           ( cd $cwd && exec timeout -k 30 $tmo "${pi_prefix[@]}" pi -p --mode json --no-session --model $model $tools "$brief" < /dev/null > $events 2> $log ) &
           run_pid=$!
           wait "$run_pid"; rc=$? run_pid= ;;
  esac
elif (( rc == 0 )); then
  if [[ $mode == write ]]; then
    if [[ -z $resume ]]; then
      writer_where=${il%/}/${repo_top:t}-wt-$label
      writer_branch=agent/$label
      [[ ! -e $writer_where && ! -L $writer_where ]] || {
        print -ru2 -- "worktree path already exists: $writer_where"
        detail=WORKTREE_PATH_EXISTS
        exit 2
      }
      git -C "$repo_top" worktree add -b "$writer_branch" "$writer_where" HEAD ||
        { detail=WORKTREE_CREATE_FAILED; exit 2; }
      where=$writer_where branch=$writer_branch
      write_running_record || abort_run 2
      typeset -A idle_tabs
      idle_order=()
      for record in "$round/runs/"*.kv(N); do
        [[ $(kv_value "$record" outcome) != running ]] || continue
        [[ $(kv_value "$record" launcher) == herdr && $(kv_value "$record" access) == write ]] || continue
        id=$(kv_value "$record" herdr_tab)
        [[ -n $id && $(kv_value "$record" herdr_closed) != 1 ]] || continue
        (( ${+idle_tabs[$id]} )) && continue
        if idle_writer_tab "$id" "$(kv_value "$record" herdr_workspace)" \
          "$(kv_value "$record" herdr_tab_label)" "$(kv_value "$record" herdr_pane)"; then
          idle_tabs[$id]=$record
          idle_order+=("$(kv_value "$record" herdr_started) $id")
        fi
      done
      idle_count=${#idle_order}
      for oldest in "${(@o)idle_order}"; do
        (( idle_count > 4 )) || break
        id=${oldest##* }
        record=${idle_tabs[$id]}
        writer_ws=$(kv_value "$record" herdr_workspace)
        writer_label=$(kv_value "$record" herdr_tab_label)
        writer_pane=$(kv_value "$record" herdr_pane)
        if ! idle_writer_tab "$id" "$writer_ws" "$writer_label" "$writer_pane"; then
          (( --idle_count ))
          continue
        fi
        if close_dispatch_tab "$id" "$writer_ws" "$writer_label" "$writer_pane" >> "$log"; then
          (( --idle_count ))
          with_record_lock "$record" append_record_fields herdr_closed=1
          closed_idle="$closed_idle CLOSED_IDLE $writer_label"
        fi
      done
      rm -f -- "$response"
    fi
  fi
  [[ $agent == pi ]] && real_model=$requested_model
  write_running_record || abort_run 2
  margs=(--model "$model")
  if [[ $agent == codex ]]; then
    margs=(-m "$model" -c "model_reasoning_effort=$effort" -c check_for_update_on_startup=false)
  fi
  run_marker="dispatch-run: $label-$st-$$"
  tab_env=()
  if [[ $mode == read ]]; then
    if [[ $agent == codex ]]; then
      report=$scratch/REPORT.md
      brief="$brief"$'\n\n'"Write your final report to $report (do not create or edit any file in the checkout)."
      tab_env=(--env "TMPDIR=$scratch")
    else
      run_token=$st-$$
      run_marker="dispatch-run: $run_token"
      brief="Return your report in your final message. Do not create or edit any file in the checkout."$'\n\n'"$brief"
    fi
  else
    report=$where/AGENT_REPORT.md
    brief="Work only inside $where (cd there first). Do not read or edit any other directory under $il."$'\n\n'"$brief"$'\n\n'"Write your final closeout report to $report."
    source_excludes=()
    round_path=${round:A}
    if [[ $round_path == "$repo_top/"* ]]; then
      source_excludes=(":(exclude,literal)${round_path#"$repo_top/"}/runs")
    fi
    source_before=$(snapshot "$repo_top" "${source_excludes[@]}") || exit 2
    round_repo=$(git -C "$round" rev-parse --show-toplevel 2>/dev/null)
    [[ -n $round_repo ]] && round_repo=${round_repo:A}
    typeset -A siblings siblings_before skipped_siblings
    snapshot_siblings before
    siblings_before=("${(@kv)siblings}")
  fi
  if [[ $agent == codex && -n ${CODEX_HOME:-} ]]; then
    tab_env+=(--env "CODEX_HOME=${CODEX_HOME:A}")
  elif [[ $agent == pi && $mode == write && -n ${PI_CODING_AGENT_DIR:-} ]]; then
    tab_env+=(--env "PI_CODING_AGENT_DIR=${PI_CODING_AGENT_DIR:A}")
  fi
  brief="$brief"$'\n\n'"$run_marker"
  if [[ $agent == codex ]]; then
    session_root=${CODEX_HOME:-$HOME/.codex}/sessions
    session_glob='rollout-*.jsonl'
  else
    session_root=${PI_CODING_AGENT_DIR:-$HOME/.pi/agent}/sessions/-${where//\//-}--
    session_glob='*.jsonl'
  fi
  json_marker=$(jq -nc --arg marker "$run_marker" '$marker')
  json_marker=${json_marker[2,-2]}
  typeset -F SECONDS
  deadline=$(( SECONDS + tmo ))
  brief_delivered=
  if [[ -z $resume ]]; then
    call_herdr workspace get "$workspace"
    if [[ -n $herdr_error ]] || ! jq -e --argjson home "$home" '
      .result.workspace | .workspace_id == $home.workspace_id and .label == $home.label' "$response" >/dev/null; then
      herdr_error=HERDR_HOME_CHANGED
    else
      herdr_started=$EPOCHREALTIME
      creating_tab=1
      call_herdr tab create --workspace "$workspace" --cwd "$where" --label "$tab_label" --no-focus "${tab_env[@]}"
      read_created_tab
      creating_tab=
      if [[ -n $tab ]]; then write_running_record || abort_run 2; fi
    fi
  fi
  if [[ -n $tab && -z $pane ]]; then
    rc=1; detail=HERDR_TAB_NO_PANE
    [[ -f $response ]] && cat "$response" >> "$log"
  elif [[ -z $tab || ( -z $resume && -n $herdr_error ) ]]; then
    rc=1; detail=HERDR_TAB_CREATE_FAILED
    [[ -n $herdr_error ]] && detail="$detail $herdr_error"
    [[ -f $response ]] && cat "$response" >> "$log"
  elif [[ $agent == pi && $mode == read ]]; then
    brief_file=$scratch/brief.md
    filter_file=$scratch/pi-pane.jq
    pane_script=$scratch/pi-launch.zsh
    events=$base.events.jsonl
    exit_marker=DISPATCH_EXIT:$run_token:
    exit_regex="^${exit_marker}([0-9]+)[[:space:]]*$"
    pane_filter='if .type=="tool_execution_start" then "▶ \(.toolName): \((.args.command // .args.path // (.args|tostring))|gsub("
";" ")|.[0:160])" elif .type=="tool_execution_end" then (if .isError then "  ✗ failed" else empty end) elif .type=="message_end" and .message.role=="assistant" then ([.message.content[]? | select(.type=="text") | .text] | join("") | select(length>0)) else empty end'
    if ! print -r -- "$brief" > "$brief_file"; then
      rc=1; detail=PI_BRIEF_WRITE_FAILED
    elif ! print -r -- "$pane_filter" > "$filter_file" ||
         ! print -rl -- \
           "cd -- ${(q)where} && TMPDIR=${(q)scratch} ${(q)sandbox_bin} -f ${(q)profile} pi -p --no-session --mode json --model ${(q)model} --tools read,bash \"\$(cat ${(q)brief_file})\" < /dev/null | tee ${(q)events} | jq --unbuffered -r -f ${(q)filter_file}" \
           "print -r -- \"${exit_marker}\${pipestatus[1]}\"" > "$pane_script"; then
      rc=1; detail=PI_PANE_SCRIPT_WRITE_FAILED
    else
      call_herdr pane run "$pane" "/bin/zsh -f ${(q)pane_script}"
      integer remaining_ms=$(( (deadline - SECONDS) * 1000 ))
      if [[ -z $herdr_error ]] && (( remaining_ms > 0 )); then
        call_herdr pane wait-output "$pane" --regex "$exit_regex" --timeout "$remaining_ms"
      fi
      if [[ $herdr_error == STALLED ]]; then
        rc=124; detail=STALLED
      elif [[ $herdr_error == timeout ]] || { [[ -z $herdr_error ]] && (( remaining_ms <= 0 )); }; then
        rc=124
        call_herdr pane send-keys "$pane" ctrl+c
      elif [[ -n $herdr_error ]]; then
        rc=1; detail=$herdr_error
      else
        matched_line=$(jq -r '.result.matched_line // empty' "$response")
        if [[ $matched_line =~ $exit_regex ]]; then
          rc=$match[1]
          pane_exited=1
        else
          rc=1; detail=PI_EXIT_STATUS_MISSING
        fi
      fi
    fi
  else
    herdr_error=
    if [[ -z $resume && $agent == codex ]]; then
      if codex_mcp_flags 2>> "$log"; then
        margs+=("${mcp_args[@]}")
        [[ $mode == read ]] && margs+=(-s workspace-write "${scratch_args[@]}")
      else
        herdr_error=CODEX_MCP_LIST_FAILED:$mcp_failure
      fi
    fi
    if [[ -z $resume && -z $herdr_error ]]; then
      if herdr_agent_start_fits "$agent" "${margs[@]}"; then
        call_herdr agent start "$target" --kind "$agent" --pane "$pane" -- "${margs[@]}"
      else
        herdr_error=HERDR_PANE_INPUT_TOO_LONG
      fi
    fi
    if [[ $herdr_error == agent_not_ready || $herdr_error == agent_blocked ]]; then
      for recovery_step in 1 2; do
        call_herdr pane read "$pane" --source visible --lines 40
        # Only the folder-trust menu is answered (owner's choice).
        # Escape in codex means "Back to Agent Command Center", which opened an unrelated live conversation.
        if [[ $agent == codex && -z $herdr_error ]] && grep -qF 'Trust this folder?' "$response"; then
          call_herdr pane send-keys "$pane" Enter
          [[ -z $herdr_error ]] && trust_accepted=TRUST_ACCEPTED
        else
          herdr_error=AGENT_BLOCKED_AT_START
          break
        fi
        startup_wait_retried=
        call_herdr agent wait "$pane" --until idle --timeout 60000
        if [[ $herdr_error == timeout ]]; then
          startup_wait_retried=1
          call_herdr agent wait "$pane" --until idle --timeout 60000
        fi
        if [[ -z $herdr_error ]] && jq -e '.result.agent.agent_status | . == "idle" or . == "done"' "$response" >/dev/null 2>&1; then
          break
        fi
        herdr_error=AGENT_BLOCKED_AT_START
        [[ -n $startup_wait_retried ]] && break
      done
    fi
    if [[ -n $resume ]]; then validate_resume_agent; fi
    integer remaining_ms
    remaining_ms=$(( (deadline - SECONDS) * 1000 ))
    if [[ $herdr_error == timeout ]]; then
      rc=124; detail=NO_REPORT
    elif [[ -n $herdr_error ]]; then
      rc=1; detail=$herdr_error
    elif (( remaining_ms <= 0 )); then
      rc=124; detail=NO_REPORT
    else
      touch "$base.launch" || abort_run 2
      call_herdr agent prompt "$pane" "$brief" --wait --until done --until idle --until blocked --timeout "$remaining_ms"
      [[ -z $herdr_error ]] && brief_delivered=1
      agent_status=$(jq -r '.result.agent.agent_status // empty' "$response" 2>/dev/null)
      if [[ $herdr_error == STALLED ]]; then
        rc=124; detail=STALLED
      elif [[ $herdr_error == timeout ]]; then
        rc=124; detail=NO_REPORT
      elif [[ $herdr_error == agent_blocked || $agent_status == blocked ]]; then
        rc=1; detail=AGENT_BLOCKED
      elif [[ -n $herdr_error ]]; then
        rc=1; detail=$herdr_error
      elif [[ $agent_status != done && $agent_status != idle ]]; then
        rc=1; detail=UNEXPECTED_AGENT_STATUS
      elif ! [[ -f $report && -s $report && $report -nt $base.launch ]]; then
        rc=1; detail=NO_REPORT
      elif ! mv -- "$report" "$out"; then
        rc=1; detail=REPORT_MOVE_FAILED
      fi
    fi
  fi
  if [[ -n $pane ]] && { [[ -n $stalled ]] || { [[ $mode == write ]] && (( rc == 124 || rc == 137 )); }; }; then
    call_herdr pane send-keys "$pane" ctrl+c
    [[ -n $herdr_error ]] && detail="$detail HERDR_INTERRUPT_FAILED"
  fi
  [[ -n $pane ]] && read_herdr_log
  if [[ $mode == read ]]; then
    save_reader_report
    close_herdr_tab
  elif [[ -z $stalled ]] && { (( rc == 124 || rc == 137 )) || [[ -z $resume && $rc != 0 && -z $brief_delivered ]]; }; then
    close_herdr_tab
  fi
  if [[ $agent == codex && -f $base.launch ]]; then
    detected_model=
    if [[ -n $transcript ]] || find_run_transcript; then
      detected_model=$(head -n "$transcript_marker_line" "$transcript" | codex_turn_model)
    fi
    if valid_model "$detected_model"; then real_model=$detected_model; else detail="$detail MODEL_UNVERIFIED"; fi
  fi
  rm -f -- "$base.launch" "$response"
  if [[ $mode == write ]]; then
    source_after=$(snapshot "$repo_top" "${source_excludes[@]}")
    snapshot_siblings after
  fi
fi

if [[ $mode == read && $via == exec ]]; then
  save_reader_report
elif [[ $mode == write && -n $events ]]; then
  extract_pi_report
  if [[ -s $out ]] && (( rc == 124 || rc == 137 )); then detail="$detail PARTIAL_REPORT"; fi
fi

if [[ -n $scratch ]]; then
  rm -rf -- "$scratch" || { rc=1; detail="$detail TMP_CLEANUP_FAILED"; }
fi
if (( rc == 0 )) && [[ ! -s $out ]]; then rc=1; detail="$detail NO_REPORT"; fi
case $rc in
  0) outcome=pass ;;
  124|137) if [[ -z $pane_exited ]]; then outcome=timeout; else outcome=error; fi ;;
  *) outcome=error ;;
esac
note="$note where=$where"
[[ -n $detail ]] && note="$note ${detail# }"
[[ -n $closed_idle ]] && note="$note$closed_idle"
[[ -n $trust_accepted ]] && note="$note $trust_accepted"
[[ -n $mcp_builtin_on ]] && note="$note $mcp_builtin_on"
if [[ -n $scratch && "$(snapshot "$where")" != "$before" ]]; then outcome=error; note="$note EDITED_IN_READ_MODE"; fi
if [[ -n $scratch && $agent == pi && "$(snapshot_pi_state "$pi_state")" != "$pi_before" ]]; then
  outcome=error; note="$note EDITED_PI_STATE"
fi
if [[ -n $branch ]]; then
  if [[ $source_after != "$source_before" ]]; then outcome=error; note="$note EDITED_SOURCE_REPO"; fi
  typeset -Ua sibling_paths
  sibling_paths=(${(k)siblings_before} ${(k)siblings})
  sibling_removed=() sibling_set_changed=()
  for sibling in ${(o)sibling_paths}; do
    if (( ! ${+siblings[$sibling]} )); then
      sibling_removed+=("${sibling:t}")
    elif (( ! ${+siblings_before[$sibling]} )); then
      sibling_set_changed+=("${sibling:t}")
    elif (( ! ${+skipped_siblings[$sibling]} )) && [[ ${siblings_before[$sibling]} != "${siblings[$sibling]}" ]]; then
      outcome=error; note="$note EDITED_SIBLING_REPO ${sibling:t}"
    fi
  done
  if (( ${#sibling_removed} )); then outcome=error; note="$note SIBLING_REMOVED ${(j:,:)sibling_removed}"; fi
  (( ${#sibling_set_changed} )) && note="$note SIBLING_SET_CHANGED ${(j:,:)sibling_set_changed}"
fi
[[ -n $stalled && $outcome != error ]] && outcome=stalled
[[ $real_model != "$requested_model" ]] && note="$note requested=$model"
exit 0
