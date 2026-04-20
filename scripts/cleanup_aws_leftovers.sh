#!/usr/bin/env bash

set -euo pipefail

# 清理 raft-quic 残留 AWS 资源（跨区域）
#
# 默认 dry-run，只打印将删除的资源。
# 真正执行删除请加 --yes。
#
# 示例:
#   bash scripts/cleanup_aws_leftovers.sh
#   bash scripts/cleanup_aws_leftovers.sh --yes
#   bash scripts/cleanup_aws_leftovers.sh --yes --regions us-east-1,us-west-2,eu-west-1

DRY_RUN=true
REGIONS_CSV=""
PROFILE=""
NAME_TOKEN="raft-quic"
PROJECT_TAG="raft-quic"
CLEAN_S3=true
PARSED_LIST=()
UNIQUE_LIST=()
RESOLVED_REGIONS=()

usage() {
  cat <<'EOF'
Usage: bash scripts/cleanup_aws_leftovers.sh [options]

Options:
  --yes                 Execute deletion (default is dry-run)
  --regions <csv>       Regions to clean, e.g. us-east-1,us-west-2
  --profile <name>      AWS profile name
  --name-token <text>   Name contains filter (default: raft-quic)
  --project-tag <tag>   Tag filter Project=<tag> (default: raft-quic)
  --no-s3               Skip S3 artifact cleanup
  -h, --help            Show this help
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes)
      DRY_RUN=false
      shift
      ;;
    --regions)
      REGIONS_CSV="$2"
      shift 2
      ;;
    --profile)
      PROFILE="$2"
      shift 2
      ;;
    --name-token)
      NAME_TOKEN="$2"
      shift 2
      ;;
    --project-tag)
      PROJECT_TAG="$2"
      shift 2
      ;;
    --no-s3)
      CLEAN_S3=false
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if ! command -v aws >/dev/null 2>&1; then
  echo "[ERROR] aws CLI not found" >&2
  exit 1
fi

AWS_CMD=(aws)
if [[ -n "$PROFILE" ]]; then
  AWS_CMD+=(--profile "$PROFILE")
fi

log() { echo "[*] $*"; }
warn() { echo "[!] $*" >&2; }

aws_cli() {
  "${AWS_CMD[@]}" "$@"
}

run_or_print() {
  if $DRY_RUN; then
    echo "[dry-run] aws $*"
    return 0
  fi
  aws_cli "$@"
}

parse_text_list() {
  local text="$1"
  local item
  PARSED_LIST=()
  if [[ -z "$text" || "$text" == "None" ]]; then
    return 0
  fi
  # shellcheck disable=SC2206
  local raw=($text)
  for item in "${raw[@]}"; do
    [[ -z "$item" || "$item" == "None" ]] && continue
    PARSED_LIST+=("$item")
  done
}

unique_list() {
  local item existing found
  UNIQUE_LIST=()
  for item in "$@"; do
    [[ -z "$item" ]] && continue
    found=false
  for existing in "${UNIQUE_LIST[@]-}"; do
      if [[ "$existing" == "$item" ]]; then
        found=true
        break
      fi
    done
    if ! $found; then
      UNIQUE_LIST+=("$item")
    fi
  done
}

resolve_regions() {
  RESOLVED_REGIONS=()
  if [[ -n "$REGIONS_CSV" ]]; then
    IFS=',' read -r -a RESOLVED_REGIONS <<<"$REGIONS_CSV"
    return 0
  fi

  local text
  text="$(aws_cli ec2 describe-regions --query 'Regions[].RegionName' --output text)"
  parse_text_list "$text"
  RESOLVED_REGIONS=("${PARSED_LIST[@]-}")
}

terminate_instances_in_region() {
  local region="$1"
  local by_project_text by_name_text
  local by_project=()
  local by_name=()
  local merged=()
  local ids=()

  by_project_text="$(aws_cli ec2 describe-instances \
    --region "$region" \
    --filters \
      "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down" \
      "Name=tag:Project,Values=${PROJECT_TAG}" \
    --query "Reservations[].Instances[].InstanceId" \
    --output text || true)"
  parse_text_list "$by_project_text"
  by_project=("${PARSED_LIST[@]-}")

  by_name_text="$(aws_cli ec2 describe-instances \
    --region "$region" \
    --filters \
      "Name=instance-state-name,Values=pending,running,stopping,stopped,shutting-down" \
      "Name=tag:Name,Values=*${NAME_TOKEN}*" \
    --query "Reservations[].Instances[].InstanceId" \
    --output text || true)"
  parse_text_list "$by_name_text"
  by_name=("${PARSED_LIST[@]-}")

  merged=("${by_project[@]-}" "${by_name[@]-}")
  unique_list "${merged[@]-}"
  ids=("${UNIQUE_LIST[@]-}")

  if [[ ${#ids[@]} -eq 0 ]]; then
    log "[$region] no matching EC2 instances"
    return 0
  fi

  log "[$region] terminate instances: ${ids[*]}"
  run_or_print ec2 terminate-instances --region "$region" --instance-ids "${ids[@]}" >/dev/null

  if ! $DRY_RUN; then
    log "[$region] waiting instances terminated..."
    aws_cli ec2 wait instance-terminated --region "$region" --instance-ids "${ids[@]}" || \
      warn "[$region] wait instance-terminated returned non-zero"
  fi
}

delete_sg_in_region() {
  local region="$1"
  local sg_text
  local sg_ids=()
  local remaining=()
  local pass sg

  sg_text="$(aws_cli ec2 describe-security-groups \
    --region "$region" \
    --filters "Name=group-name,Values=*${NAME_TOKEN}*" \
    --query "SecurityGroups[?GroupName!='default'].GroupId" \
    --output text || true)"
  parse_text_list "$sg_text"
  sg_ids=("${PARSED_LIST[@]-}")

  if [[ ${#sg_ids[@]} -eq 0 ]]; then
    log "[$region] no matching security groups"
    return 0
  fi

  log "[$region] delete security groups: ${sg_ids[*]}"

  if $DRY_RUN; then
    for sg in "${sg_ids[@]-}"; do
      run_or_print ec2 delete-security-group --region "$region" --group-id "$sg"
    done
    return 0
  fi

  remaining=("${sg_ids[@]-}")
  for pass in 1 2 3; do
    [[ ${#remaining[@]} -eq 0 ]] && break
    local next=()
    for sg in "${remaining[@]-}"; do
      if aws_cli ec2 delete-security-group --region "$region" --group-id "$sg" >/dev/null 2>&1; then
        log "[$region] deleted sg $sg"
      else
        next+=("$sg")
      fi
    done
    remaining=("${next[@]-}")
    [[ ${#remaining[@]} -eq 0 ]] && break
    warn "[$region] sg still in use (pass $pass): ${remaining[*]}"
    sleep 5
  done

  if [[ ${#remaining[@]} -gt 0 ]]; then
    warn "[$region] could not delete some security groups: ${remaining[*]}"
  fi
}

delete_key_pairs_in_region() {
  local region="$1"
  local kp_text
  local kp_names=()
  local kp

  kp_text="$(aws_cli ec2 describe-key-pairs \
    --region "$region" \
    --query "KeyPairs[?contains(KeyName, '${NAME_TOKEN}')].KeyName" \
    --output text || true)"
  parse_text_list "$kp_text"
  kp_names=("${PARSED_LIST[@]-}")

  if [[ ${#kp_names[@]} -eq 0 ]]; then
    log "[$region] no matching key pairs"
    return 0
  fi

  log "[$region] delete key pairs: ${kp_names[*]}"
  for kp in "${kp_names[@]-}"; do
    run_or_print ec2 delete-key-pair --region "$region" --key-name "$kp" >/dev/null
  done
}

cleanup_iam_global() {
  local profile_text role_text
  local profiles=()
  local roles=()
  local p r

  profile_text="$(aws_cli iam list-instance-profiles \
    --query "InstanceProfiles[?contains(InstanceProfileName, '${NAME_TOKEN}')].InstanceProfileName" \
    --output text || true)"
  parse_text_list "$profile_text"
  profiles=("${PARSED_LIST[@]-}")

  role_text="$(aws_cli iam list-roles \
    --query "Roles[?contains(RoleName, '${NAME_TOKEN}')].RoleName" \
    --output text || true)"
  parse_text_list "$role_text"
  roles=("${PARSED_LIST[@]-}")

  if [[ ${#profiles[@]} -eq 0 && ${#roles[@]} -eq 0 ]]; then
    log "[iam] no matching roles/profiles"
    return 0
  fi

  if [[ ${#profiles[@]} -gt 0 ]]; then
    log "[iam] cleanup instance profiles: ${profiles[*]}"
  fi
  for p in "${profiles[@]-}"; do
    local role_names_text role_names=()
    role_names_text="$(aws_cli iam get-instance-profile \
      --instance-profile-name "$p" \
      --query "InstanceProfile.Roles[].RoleName" \
      --output text 2>/dev/null || true)"
    parse_text_list "$role_names_text"
    role_names=("${PARSED_LIST[@]-}")
    for r in "${role_names[@]-}"; do
      run_or_print iam remove-role-from-instance-profile \
        --instance-profile-name "$p" \
        --role-name "$r" >/dev/null || true
    done
    run_or_print iam delete-instance-profile --instance-profile-name "$p" >/dev/null || true
  done

  if [[ ${#roles[@]} -gt 0 ]]; then
    log "[iam] cleanup roles: ${roles[*]}"
  fi
  for r in "${roles[@]-}"; do
    local attached_text inline_text attached=() inline=() arn pol

    attached_text="$(aws_cli iam list-attached-role-policies \
      --role-name "$r" \
      --query "AttachedPolicies[].PolicyArn" \
      --output text 2>/dev/null || true)"
    parse_text_list "$attached_text"
    attached=("${PARSED_LIST[@]-}")
    for arn in "${attached[@]-}"; do
      run_or_print iam detach-role-policy --role-name "$r" --policy-arn "$arn" >/dev/null || true
    done

    inline_text="$(aws_cli iam list-role-policies \
      --role-name "$r" \
      --query "PolicyNames[]" \
      --output text 2>/dev/null || true)"
    parse_text_list "$inline_text"
    inline=("${PARSED_LIST[@]-}")
    for pol in "${inline[@]-}"; do
      run_or_print iam delete-role-policy --role-name "$r" --policy-name "$pol" >/dev/null || true
    done

    run_or_print iam delete-role --role-name "$r" >/dev/null || true
  done
}

cleanup_s3_artifacts() {
  local buckets_text buckets=()
  local b

  buckets_text="$(aws_cli s3api list-buckets \
    --query "Buckets[?starts_with(Name, 'raft-quic-artifacts-')].Name" \
    --output text || true)"
  parse_text_list "$buckets_text"
  buckets=("${PARSED_LIST[@]-}")

  if [[ ${#buckets[@]} -eq 0 ]]; then
    log "[s3] no artifact buckets found"
    return 0
  fi

  for b in "${buckets[@]-}"; do
    log "[s3] cleanup prefix distributed-benchmark/ in $b"
    if $DRY_RUN; then
      echo "[dry-run] aws s3 rm s3://$b/distributed-benchmark --recursive --only-show-errors"
    else
      aws_cli s3 rm "s3://$b/distributed-benchmark" --recursive --only-show-errors >/dev/null || \
        warn "[s3] failed to clean bucket $b"
    fi
  done
}

main() {
  local regions=()
  resolve_regions
  regions=("${RESOLVED_REGIONS[@]-}")
  if [[ ${#regions[@]} -eq 0 ]]; then
    echo "[ERROR] no regions resolved" >&2
    exit 1
  fi

  if $DRY_RUN; then
    log "mode: dry-run (no resources will be deleted)"
  else
    log "mode: APPLY (resources will be deleted)"
  fi

  log "regions: ${regions[*]}"
  log "filters: name contains '${NAME_TOKEN}', Project tag '${PROJECT_TAG}'"

  local region
  for region in "${regions[@]-}"; do
    log "========== region: $region =========="
    terminate_instances_in_region "$region"
    delete_sg_in_region "$region"
    delete_key_pairs_in_region "$region"
  done

  log "========== global: IAM =========="
  cleanup_iam_global

  if $CLEAN_S3; then
    log "========== global: S3 artifacts =========="
    cleanup_s3_artifacts
  fi

  log "cleanup completed"
}

main
