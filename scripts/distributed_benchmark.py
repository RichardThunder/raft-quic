#!/usr/bin/env python3
"""
分布式性能测试框架 - TCP vs QUIC 对比

支持:
  • 多种集群规模 (3, 5, 7 节点)
  • 同区域和跨区域部署
  • 系统指标与 Raft 指标采集
  • 详细的性能报告生成

Usage:
    python3 scripts/distributed_benchmark.py \
      --cluster-sizes 3,5,7 \
      --scenarios same-region,cross-region \
      --writes 500 \
      --duration 300 \
      --monitor \
      --out results
"""

import argparse
import csv
import json
import os
import random
import re
import socket
import shlex
import string
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional, Tuple


def _node_sort_key(node_id: str) -> Tuple[int, str]:
    match = re.search(r"(\d+)$", node_id)
    if match:
        return (int(match.group(1)), node_id)
    return (sys.maxsize, node_id)


class AwsClusterManager:
    """管理 AWS 集群部署、服务启动和销毁。"""

    def __init__(
        self,
        cluster_size: int,
        scenario: str,
        terraform_dir: Optional[str] = None,
        name_prefix: str = "",
    ):
        self.cluster_size = cluster_size
        self.scenario = scenario
        self.repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        self.deploy_dir = (
            os.path.abspath(terraform_dir)
            if terraform_dir
            else os.path.join(self.repo_root, "deploy", "terraform", scenario)
        )
        self.cluster_env = os.path.join(
            self.repo_root, "deploy", f"cluster-{scenario}-{cluster_size}.env"
        )
        self.raft_binary = os.path.join(self.repo_root, "raftd-linux-amd64")
        self.tcp_binary = os.path.join(
            self.repo_root, "cmd", "tcp-server", "tcp-server-linux-amd64"
        )
        self.ssh_key_file = os.path.join(self.deploy_dir, "raft-key.pem")
        self.ssh_user = "ec2-user"
        self.nodes: Dict[str, str] = {}
        self.region_labels: List[str] = []
        self.instances: Dict[str, str] = {}
        self.node_regions: Dict[str, str] = {}
        self.name_prefix = name_prefix.strip()
        self.artifact_region = "us-east-1"
        self.artifact_bucket = ""
        self.artifact_keys: List[str] = []

    def deploy(self) -> Dict[str, str]:
        """部署集群并启动 raftd + tcp-server。"""
        print(f"[*] 部署 {self.cluster_size} 节点 {self.scenario} 集群...", flush=True)

        self._ensure_linux_binaries()
        self._terraform_init()
        self._terraform_apply()
        self.nodes = self._parse_terraform_output()

        if not self.nodes:
            print("[!] Terraform 输出未包含节点信息")
            return {}

        if len(self.nodes) != self.cluster_size:
            print(
                f"[!] 节点数不匹配: 期望 {self.cluster_size}, 实际 {len(self.nodes)}",
                flush=True,
            )
            return {}

        self._save_cluster_config(self.nodes)
        artifact_urls = self._prepare_artifacts()
        try:
            self._wait_for_ssm_ready()
            self._start_cluster_services_via_ssm(self.nodes, artifact_urls)
            self._wait_for_cluster_ready(self.nodes)
        finally:
            self._cleanup_artifacts()

        print(f"[+] 集群部署并启动完成: {list(self.nodes.keys())}", flush=True)
        return self.nodes

    def _ensure_linux_binaries(self):
        os.makedirs(os.path.dirname(self.tcp_binary), exist_ok=True)
        self._build_linux_binary_if_needed(self.raft_binary, "./cmd/raftd", "raftd")
        self._build_linux_binary_if_needed(self.tcp_binary, "./cmd/tcp-server", "tcp-server")

    def _build_linux_binary_if_needed(self, binary_path: str, package: str, name: str):
        if self._linux_binary_needs_rebuild(binary_path):
            reason = "缺失" if not os.path.exists(binary_path) else "源码更新"
            print(f"[*] 构建 {name} Linux 二进制 ({reason})...", flush=True)
            self._run_cmd(
                ["go", "build", "-o", binary_path, package],
                cwd=self.repo_root,
                env=self._go_linux_env(),
            )
            return
        print(f"[+] {name} Linux 二进制已是最新", flush=True)

    def _linux_binary_needs_rebuild(self, binary_path: str) -> bool:
        if not os.path.exists(binary_path):
            return True

        binary_mtime = os.path.getmtime(binary_path)
        return self._latest_go_source_mtime() > binary_mtime

    def _latest_go_source_mtime(self) -> float:
        latest_mtime = 0.0
        skip_dirs = {".git", "results"}

        for root, dirs, files in os.walk(self.repo_root):
            dirs[:] = [d for d in dirs if d not in skip_dirs]
            for name in files:
                if not name.endswith(".go"):
                    continue
                path = os.path.join(root, name)
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    continue
                if mtime > latest_mtime:
                    latest_mtime = mtime

        return latest_mtime

    @staticmethod
    def _go_linux_env() -> Dict[str, str]:
        env = os.environ.copy()
        env["GOOS"] = "linux"
        env["GOARCH"] = "amd64"
        return env

    def _terraform_init(self):
        self._run_cmd(
            ["terraform", "init", "-input=false", "-upgrade"],
            cwd=self.deploy_dir,
        )

    def _terraform_apply(self):
        cmd = [
            "terraform",
            "apply",
            "-input=false",
            "-auto-approve",
            f"-var=cluster_size={self.cluster_size}",
        ]
        if self.name_prefix:
            cmd.append(f"-var=name_prefix={self.name_prefix}")
        self._run_cmd(cmd, cwd=self.deploy_dir)

    def _parse_terraform_output(self) -> Dict[str, str]:
        result = self._run_cmd(
            ["terraform", "output", "-json"],
            cwd=self.deploy_dir,
            capture_output=True,
        )
        try:
            output = json.loads(result.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"解析 terraform output 失败: {exc}") from exc

        node_ips = output.get("node_ips", {}).get("value", [])
        node_ids = output.get("node_ids", {}).get("value", [])
        instance_ids = output.get("instance_ids", {}).get("value", [])
        if not node_ids:
            node_ids = [f"node{i}" for i in range(1, len(node_ips) + 1)]

        if len(node_ids) != len(node_ips):
            raise RuntimeError("Terraform 输出 node_ids 与 node_ips 数量不一致")
        if len(instance_ids) != len(node_ids):
            raise RuntimeError("Terraform 输出 instance_ids 缺失或数量不一致，无法使用 SSM 部署")

        key_file = output.get("ssh_key_file", {}).get("value")
        if key_file:
            if not os.path.isabs(key_file):
                key_file = os.path.normpath(os.path.join(self.deploy_dir, key_file))
            self.ssh_key_file = key_file
        ssh_user = output.get("ssh_user", {}).get("value")
        if ssh_user:
            self.ssh_user = ssh_user

        self.region_labels = output.get("region_labels", {}).get("value", [])
        if self.region_labels and len(self.region_labels) != len(node_ids):
            raise RuntimeError("Terraform 输出 region_labels 数量与节点数不一致")

        raw_nodes: Dict[str, str] = {}
        raw_instances: Dict[str, str] = {}
        raw_regions: Dict[str, str] = {}
        for idx, node_id in enumerate(node_ids):
            raw_nodes[node_id] = node_ips[idx]
            raw_instances[node_id] = instance_ids[idx]
            if self.region_labels:
                raw_regions[node_id] = self.region_labels[idx]
            else:
                raw_regions[node_id] = "us-east-1"

        sorted_node_ids = sorted(raw_nodes.keys(), key=_node_sort_key)
        self.instances = {node_id: raw_instances[node_id] for node_id in sorted_node_ids}
        self.node_regions = {node_id: raw_regions[node_id] for node_id in sorted_node_ids}
        self.region_labels = [self.node_regions[node_id] for node_id in sorted_node_ids]

        return {node_id: raw_nodes[node_id] for node_id in sorted_node_ids}

    def _save_cluster_config(self, nodes: Dict[str, str]):
        os.makedirs(os.path.dirname(self.cluster_env), exist_ok=True)
        with open(self.cluster_env, "w", encoding="utf-8") as f:
            f.write(f"SCENARIO={self.scenario}\n")
            f.write(f"CLUSTER_SIZE={self.cluster_size}\n")
            f.write(f"DEPLOYED_AT={datetime.now().isoformat()}\n")
            f.write(f"KEY_FILE={self.ssh_key_file}\n")
            f.write(f"SSH_USER={self.ssh_user}\n")
            if self.region_labels:
                f.write(f"REGION_LABELS={','.join(self.region_labels)}\n")
            for node_id, ip in nodes.items():
                f.write(f"{node_id.upper()}_IP={ip}\n")
                if node_id in self.instances:
                    f.write(f"{node_id.upper()}_INSTANCE_ID={self.instances[node_id]}\n")
                if node_id in self.node_regions:
                    f.write(f"{node_id.upper()}_REGION={self.node_regions[node_id]}\n")
        print(f"[+] 集群配置已保存: {self.cluster_env}", flush=True)

    def _prepare_artifacts(self) -> Dict[str, str]:
        print("[*] 上传二进制到 S3（供 SSM 拉取）...", flush=True)

        account = self._run_cmd(
            ["aws", "sts", "get-caller-identity", "--query", "Account", "--output", "text"],
            capture_output=True,
        ).stdout.strip()
        if not account:
            raise RuntimeError("无法读取 AWS 账号 ID")

        self.artifact_bucket = f"raft-quic-artifacts-{account}-{self.artifact_region}"
        self._ensure_artifact_bucket(self.artifact_bucket)

        suffix = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}-{os.getpid()}-{self.scenario}-{self.cluster_size}"
        raft_key = f"distributed-benchmark/{suffix}/raftd-linux-amd64"
        tcp_key = f"distributed-benchmark/{suffix}/tcp-server-linux-amd64"

        self._run_cmd(
            [
                "aws",
                "s3",
                "cp",
                self.raft_binary,
                f"s3://{self.artifact_bucket}/{raft_key}",
                "--region",
                self.artifact_region,
            ]
        )
        self._run_cmd(
            [
                "aws",
                "s3",
                "cp",
                self.tcp_binary,
                f"s3://{self.artifact_bucket}/{tcp_key}",
                "--region",
                self.artifact_region,
            ]
        )

        raft_url = self._run_cmd(
            [
                "aws",
                "s3",
                "presign",
                f"s3://{self.artifact_bucket}/{raft_key}",
                "--expires-in",
                "7200",
                "--region",
                self.artifact_region,
            ],
            capture_output=True,
        ).stdout.strip()
        tcp_url = self._run_cmd(
            [
                "aws",
                "s3",
                "presign",
                f"s3://{self.artifact_bucket}/{tcp_key}",
                "--expires-in",
                "7200",
                "--region",
                self.artifact_region,
            ],
            capture_output=True,
        ).stdout.strip()

        self.artifact_keys = [raft_key, tcp_key]
        print("[+] 二进制已上传并生成预签名下载链接", flush=True)
        return {"raftd": raft_url, "tcp_server": tcp_url}

    def _ensure_artifact_bucket(self, bucket: str):
        head = self._run_cmd(
            ["aws", "s3api", "head-bucket", "--bucket", bucket, "--region", self.artifact_region],
            capture_output=True,
            check=False,
        )
        if head.returncode == 0:
            return

        create_cmd = [
            "aws",
            "s3api",
            "create-bucket",
            "--bucket",
            bucket,
            "--region",
            self.artifact_region,
        ]
        if self.artifact_region != "us-east-1":
            create_cmd.extend(
                ["--create-bucket-configuration", f"LocationConstraint={self.artifact_region}"]
            )
        self._run_cmd(create_cmd)

    def _cleanup_artifacts(self):
        if not self.artifact_bucket or not self.artifact_keys:
            return
        for key in self.artifact_keys:
            self._run_cmd(
                [
                    "aws",
                    "s3",
                    "rm",
                    f"s3://{self.artifact_bucket}/{key}",
                    "--region",
                    self.artifact_region,
                ],
                check=False,
            )
        self.artifact_keys = []

    def _wait_for_ssm_ready(self, retries: int = 60, wait_s: int = 5):
        for node_id in sorted(self.instances.keys(), key=_node_sort_key):
            instance_id = self.instances[node_id]
            region = self.node_regions.get(node_id, "us-east-1")
            print(f"[*] 等待 SSM 就绪: {node_id} ({instance_id}, {region})", flush=True)

            ready = False
            last_status = ""
            for _ in range(retries):
                result = self._run_cmd(
                    [
                        "aws",
                        "ssm",
                        "describe-instance-information",
                        "--region",
                        region,
                        "--filters",
                        f"Key=InstanceIds,Values={instance_id}",
                        "--query",
                        "InstanceInformationList[0].PingStatus",
                        "--output",
                        "text",
                    ],
                    capture_output=True,
                    check=False,
                )
                if result.returncode == 0:
                    status = result.stdout.strip()
                    if status == "Online":
                        ready = True
                        break
                    last_status = status
                else:
                    if result.stderr:
                        last_status = result.stderr.strip().splitlines()[-1]
                time.sleep(wait_s)

            if not ready:
                detail = f", 最后状态: {last_status}" if last_status else ""
                raise RuntimeError(f"SSM 超时: {node_id} ({instance_id}){detail}")
            print(f"[+] SSM 就绪: {node_id}", flush=True)

    def _start_cluster_services_via_ssm(self, nodes: Dict[str, str], artifacts: Dict[str, str]):
        if not nodes:
            raise RuntimeError("空节点列表，无法启动服务")

        hb_timeout, el_timeout = self._raft_timeouts()
        ordered_nodes = sorted(nodes.items(), key=lambda kv: _node_sort_key(kv[0]))
        bootstrap_id, bootstrap_ip = ordered_nodes[0]

        print(f"[*] 通过 SSM 启动 bootstrap 节点: {bootstrap_id}", flush=True)
        self._start_node_via_ssm(
            node_id=bootstrap_id,
            ip=bootstrap_ip,
            quic_join_http=None,
            tcp_join_http=None,
            heartbeat_timeout=hb_timeout,
            election_timeout=el_timeout,
            artifacts=artifacts,
        )
        time.sleep(5)

        for node_id, ip in ordered_nodes[1:]:
            print(f"[*] 通过 SSM 启动 follower 节点: {node_id}", flush=True)
            self._start_node_via_ssm(
                node_id=node_id,
                ip=ip,
                quic_join_http=f"{bootstrap_ip}:8001",
                tcp_join_http=f"{bootstrap_ip}:9001",
                heartbeat_timeout=hb_timeout,
                election_timeout=el_timeout,
                artifacts=artifacts,
            )

    def _wait_for_cluster_ready(self, nodes: Dict[str, str], timeout_s: int = 90):
        print("[*] 等待 QUIC/TCP 集群状态稳定...", flush=True)
        deadline = time.monotonic() + timeout_s
        protocols = [("quic", 8001), ("tcp", 9001)]
        last_snapshot: Dict[str, Dict[str, int]] = {}
        while time.monotonic() < deadline:
            all_ready = True
            snapshot: Dict[str, Dict[str, int]] = {}
            for protocol, port in protocols:
                reachable = 0
                leaders = 0
                for ip in nodes.values():
                    status = self._fetch_status(ip, port=port)
                    if status is None:
                        continue
                    reachable += 1
                    if status.get("is_leader") or status.get("state") == "Leader":
                        leaders += 1
                snapshot[protocol] = {"reachable": reachable, "leaders": leaders}
                if not (reachable == len(nodes) and leaders >= 1):
                    all_ready = False
            if all_ready:
                print("[+] 集群状态已就绪", flush=True)
                return
            last_snapshot = snapshot
            time.sleep(2)

        details = []
        for protocol, _ in protocols:
            stat = last_snapshot.get(protocol)
            if not stat:
                continue
            details.append(
                f"{protocol}: reachable={stat['reachable']}/{len(nodes)}, leaders={stat['leaders']}"
            )
        detail_msg = "; ".join(details) if details else "无状态数据"
        raise RuntimeError(f"集群未在超时内就绪 ({detail_msg})")

    def _start_node_via_ssm(
        self,
        node_id: str,
        ip: str,
        quic_join_http: Optional[str],
        tcp_join_http: Optional[str],
        heartbeat_timeout: str,
        election_timeout: str,
        artifacts: Dict[str, str],
    ):
        quic_cmd = (
            f"/opt/raft-quic/raftd -id {shlex.quote(node_id)} "
            f"-bind 0.0.0.0:7001 -advertise {shlex.quote(f'{ip}:7001')} "
            f"-http 0.0.0.0:8001 "
            f"-heartbeat-timeout {shlex.quote(heartbeat_timeout)} "
            f"-election-timeout {shlex.quote(election_timeout)}"
        )
        if quic_join_http:
            quic_cmd += f" -join {shlex.quote(quic_join_http)} -join-retries 20"

        tcp_cmd = (
            f"/opt/raft-quic/tcp-server -id {shlex.quote(node_id)} "
            f"-bind 0.0.0.0:9007 -advertise {shlex.quote(f'{ip}:9007')} "
            f"-http 0.0.0.0:9001 "
            f"-heartbeat-timeout {shlex.quote(heartbeat_timeout)} "
            f"-election-timeout {shlex.quote(election_timeout)}"
        )
        if tcp_join_http:
            tcp_cmd += f" -join {shlex.quote(tcp_join_http)} -join-retries 20"

        commands = [
            "set -euo pipefail",
            "sudo mkdir -p /opt/raft-quic",
            "sudo mkdir -p /var/lib/raft-quic/quic /var/lib/raft-quic/tcp",
            f"sudo curl -fsSL {shlex.quote(artifacts['raftd'])} -o /opt/raft-quic/raftd",
            f"sudo curl -fsSL {shlex.quote(artifacts['tcp_server'])} -o /opt/raft-quic/tcp-server",
            "sudo chmod +x /opt/raft-quic/raftd /opt/raft-quic/tcp-server",
            "sudo pkill -f '/opt/raft-quic/raftd' >/dev/null 2>&1 || true",
            "sudo pkill -f '/opt/raft-quic/tcp-server' >/dev/null 2>&1 || true",
            f"sudo nohup {quic_cmd} > /var/log/raftd.log 2>&1 &",
            f"sudo nohup {tcp_cmd} > /var/log/tcp-server.log 2>&1 &",
            "sleep 2",
            "sudo pgrep -f '/opt/raft-quic/raftd' >/dev/null || { echo 'raftd 未成功启动，日志如下:' >&2; sudo tail -n 80 /var/log/raftd.log >&2 || true; exit 1; }",
            "sudo pgrep -f '/opt/raft-quic/tcp-server' >/dev/null || { echo 'tcp-server 未成功启动，日志如下:' >&2; sudo tail -n 80 /var/log/tcp-server.log >&2 || true; exit 1; }",
        ]
        self._run_ssm_commands(node_id, commands)

    def _run_ssm_commands(self, node_id: str, commands: List[str], timeout_s: int = 600):
        instance_id = self.instances.get(node_id)
        if not instance_id:
            raise RuntimeError(f"节点 {node_id} 缺少 instance_id")
        region = self.node_regions.get(node_id, "us-east-1")

        send = self._run_cmd(
            [
                "aws",
                "ssm",
                "send-command",
                "--region",
                region,
                "--instance-ids",
                instance_id,
                "--document-name",
                "AWS-RunShellScript",
                "--comment",
                f"raft-quic-start-{node_id}",
                "--parameters",
                json.dumps({"commands": commands}, ensure_ascii=False),
                "--query",
                "Command.CommandId",
                "--output",
                "text",
            ],
            capture_output=True,
        )
        command_id = send.stdout.strip()
        if not command_id:
            raise RuntimeError(f"无法获取 SSM command_id: {node_id}")

        terminal = {"Success", "Failed", "Cancelled", "TimedOut", "Undeliverable", "Terminated"}
        deadline = time.monotonic() + timeout_s
        last_status = ""

        while time.monotonic() < deadline:
            status_res = self._run_cmd(
                [
                    "aws",
                    "ssm",
                    "get-command-invocation",
                    "--region",
                    region,
                    "--command-id",
                    command_id,
                    "--instance-id",
                    instance_id,
                    "--query",
                    "Status",
                    "--output",
                    "text",
                ],
                capture_output=True,
                check=False,
            )
            if status_res.returncode != 0:
                time.sleep(3)
                continue

            status = status_res.stdout.strip()
            if status:
                last_status = status
            if status in terminal:
                if status != "Success":
                    stderr_res = self._run_cmd(
                        [
                            "aws",
                            "ssm",
                            "get-command-invocation",
                            "--region",
                            region,
                            "--command-id",
                            command_id,
                            "--instance-id",
                            instance_id,
                            "--query",
                            "StandardErrorContent",
                            "--output",
                            "text",
                        ],
                        capture_output=True,
                        check=False,
                    )
                    err = stderr_res.stdout.strip() if stderr_res.returncode == 0 else ""
                    detail = f", stderr: {err}" if err else ""
                    raise RuntimeError(f"SSM 命令失败: {node_id} ({status}){detail}")
                return

            time.sleep(3)

        detail = f", 最后状态: {last_status}" if last_status else ""
        raise RuntimeError(f"SSM 命令超时: {node_id}{detail}")

    def _raft_timeouts(self) -> Tuple[str, str]:
        if self.scenario == "cross-region":
            return ("1s", "2s")
        return ("150ms", "300ms")

    def _fetch_status(self, ip: str, port: int = 8001) -> Optional[Dict]:
        url = f"http://{ip}:{port}/status"
        try:
            with urllib.request.urlopen(url, timeout=3) as resp:
                if resp.status != 200:
                    return None
                return json.loads(resp.read().decode("utf-8"))
        except Exception:
            return None

    def teardown(self):
        """销毁集群。"""
        print(f"[*] 销毁 {self.cluster_size} 节点 {self.scenario} 集群...", flush=True)
        cmd = [
            "terraform",
            "destroy",
            "-input=false",
            "-auto-approve",
            f"-var=cluster_size={self.cluster_size}",
        ]
        if self.name_prefix:
            cmd.append(f"-var=name_prefix={self.name_prefix}")
        self._run_cmd(cmd, cwd=self.deploy_dir, check=False)
        print("[+] 集群已销毁", flush=True)

    def _run_cmd(
        self,
        cmd: List[str],
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        capture_output: bool = False,
        check: bool = True,
    ) -> subprocess.CompletedProcess:
        return subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            check=check,
            text=True,
            capture_output=capture_output,
        )


class MetricsCollector:
    """收集系统与 Raft 指标。"""

    def __init__(
        self,
        nodes: Dict[str, str],
        ssh_key: str,
        ssh_user: str = "ec2-user",
        instances: Optional[Dict[str, str]] = None,
        node_regions: Optional[Dict[str, str]] = None,
    ):
        self.nodes = nodes
        self.ssh_key = ssh_key
        self.ssh_user = ssh_user
        self.instances = instances or {}
        self.node_regions = node_regions or {}
        self.ip_to_node = {ip: node_id for node_id, ip in nodes.items()}
        self.use_ssm = bool(self.instances)

    def collect_baseline(self) -> Dict:
        baseline = {}
        for node_id, ip in self.nodes.items():
            baseline[node_id] = {
                "cpu": self._get_cpu(ip),
                "memory": self._get_memory(ip),
                "network": self._get_network(ip),
                "disk": self._get_disk(ip),
            }
        return baseline

    def collect_raft_metrics(self) -> Dict:
        raft_metrics = {}
        for node_id, ip in self.nodes.items():
            try:
                with urllib.request.urlopen(f"http://{ip}:8001/status", timeout=5) as resp:
                    if resp.status != 200:
                        continue
                    status = json.loads(resp.read().decode("utf-8"))
                    raft_metrics[node_id] = {
                        "is_leader": status.get("is_leader", False),
                        "term": status.get("term", 0),
                        "committed_index": status.get("committed_index", 0),
                        "last_applied": status.get("last_applied", 0),
                    }
            except Exception as exc:
                print(f"[!] 无法收集 {node_id} 的 Raft 指标: {exc}")
        return raft_metrics

    def _ssh_exec(self, ip: str, remote_cmd: str, timeout: int = 5) -> str:
        node_id = self.ip_to_node.get(ip, "")
        if self.use_ssm and node_id in self.instances:
            return self._ssm_exec(node_id, remote_cmd, timeout=timeout)

        cmd = [
            "ssh",
            "-i",
            self.ssh_key,
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ConnectTimeout=3",
            f"{self.ssh_user}@{ip}",
            remote_cmd,
        ]
        result = subprocess.run(cmd, text=True, capture_output=True, timeout=timeout)
        return result.stdout.strip() if result.returncode == 0 else ""

    def _ssm_exec(self, node_id: str, remote_cmd: str, timeout: int = 15) -> str:
        instance_id = self.instances.get(node_id)
        if not instance_id:
            return ""
        region = self.node_regions.get(node_id, "us-east-1")

        send = subprocess.run(
            [
                "aws",
                "ssm",
                "send-command",
                "--region",
                region,
                "--instance-ids",
                instance_id,
                "--document-name",
                "AWS-RunShellScript",
                "--parameters",
                json.dumps({"commands": [remote_cmd]}),
                "--query",
                "Command.CommandId",
                "--output",
                "text",
            ],
            text=True,
            capture_output=True,
        )
        if send.returncode != 0:
            return ""
        command_id = send.stdout.strip()
        if not command_id:
            return ""

        deadline = time.time() + max(timeout, 5)
        terminal = {"Success", "Failed", "Cancelled", "TimedOut", "Undeliverable", "Terminated"}
        while time.time() < deadline:
            inv = subprocess.run(
                [
                    "aws",
                    "ssm",
                    "get-command-invocation",
                    "--region",
                    region,
                    "--command-id",
                    command_id,
                    "--instance-id",
                    instance_id,
                    "--query",
                    "[Status,StandardOutputContent]",
                    "--output",
                    "json",
                ],
                text=True,
                capture_output=True,
            )
            if inv.returncode != 0:
                time.sleep(1)
                continue
            try:
                status, stdout = json.loads(inv.stdout)
            except Exception:
                time.sleep(1)
                continue
            if status in terminal:
                if status == "Success":
                    return (stdout or "").strip()
                return ""
            time.sleep(1)
        return ""

    def _get_cpu(self, ip: str) -> float:
        output = self._ssh_exec(ip, "top -bn1 | grep Cpu | awk '{print $2}'")
        try:
            return float(output.rstrip("%")) if output else 0.0
        except ValueError:
            return 0.0

    def _get_memory(self, ip: str) -> Dict[str, float]:
        output = self._ssh_exec(ip, "free -h | grep Mem | awk '{print $3, $2}'")
        try:
            used, total = output.split()
            return {
                "used_gb": float(used.rstrip("G")),
                "total_gb": float(total.rstrip("G")),
            }
        except Exception:
            return {"used_gb": 0.0, "total_gb": 0.0}

    def _get_network(self, ip: str) -> Dict[str, float]:
        output = self._ssh_exec(ip, "cat /proc/net/dev | grep eth0")
        try:
            parts = output.split()
            return {"rx_bytes": float(parts[1]), "tx_bytes": float(parts[9])}
        except Exception:
            return {"rx_bytes": 0.0, "tx_bytes": 0.0}

    def _get_disk(self, ip: str) -> Dict[str, float]:
        output = self._ssh_exec(ip, "df -h / | tail -1 | awk '{print $3, $2}'")
        try:
            used, total = output.split()
            return {
                "used_gb": float(used.rstrip("G")),
                "total_gb": float(total.rstrip("G")),
            }
        except Exception:
            return {"used_gb": 0.0, "total_gb": 0.0}


class DistributedBenchmark:
    """分布式基准测试执行器。"""

    def __init__(self, nodes: Dict[str, str], cluster_size: int, scenario: str):
        self.nodes = nodes
        self.cluster_size = cluster_size
        self.scenario = scenario
        self.leader_ips: Dict[str, Optional[str]] = {"quic": None, "tcp": None}

    @staticmethod
    def _port_for_protocol(protocol: str) -> int:
        if protocol == "quic":
            return 8001
        if protocol == "tcp":
            return 9001
        raise ValueError(f"unsupported protocol: {protocol}")

    @staticmethod
    def _extract_leader_ip(body: str) -> Optional[str]:
        match = re.search(r"leader is\s+([^\s]+)", body or "")
        if not match:
            return None
        addr = match.group(1).strip()
        if not addr:
            return None
        if ":" in addr:
            host = addr.rsplit(":", 1)[0]
            if host.startswith("[") and host.endswith("]"):
                host = host[1:-1]
            return host or None
        return addr

    def _current_target_ip(self, protocol: str, fallback_ip: str) -> str:
        return self.leader_ips.get(protocol) or fallback_ip

    def run_benchmark(self, writes: int, duration: int, protocol: str = "quic") -> Dict:
        print(
            f"\n[*] 运行 {protocol.upper()} 基准测试 ({self.cluster_size} 节点, {self.scenario})...",
            flush=True,
        )

        if not self._find_leader(protocol=protocol, retries=45, wait_s=1.0, allow_fallback=True):
            print("[!] 无法找到 leader，跳过该轮", flush=True)
            return {}

        target_ip = self._current_target_ip(protocol, next(iter(self.nodes.values())))
        benchmark_data = self._run_write_benchmark(writes, protocol, target_ip)
        latency_data = self._run_latency_benchmark(duration, protocol, target_ip)
        read_data = self._run_read_benchmark(max(writes // 2, 1), protocol, target_ip)

        return {
            "protocol": protocol,
            "cluster_size": self.cluster_size,
            "scenario": self.scenario,
            "write_throughput": benchmark_data.get("throughput", 0),
            "write_p50_ms": latency_data.get("p50", 0),
            "write_p95_ms": latency_data.get("p95", 0),
            "write_p99_ms": latency_data.get("p99", 0),
            "read_throughput": read_data.get("throughput", 0),
            "write_errors": benchmark_data.get("errors", 0),
            "write_error_503": benchmark_data.get("error_503", 0),
            "write_error_500": benchmark_data.get("error_500", 0),
            "write_error_timeout": benchmark_data.get("error_timeout", 0),
            "write_error_other": benchmark_data.get("error_other", 0),
            "write_retries": benchmark_data.get("retries", 0),
            "write_retry_recovered": benchmark_data.get("retry_recovered", 0),
            "read_errors": read_data.get("errors", 0),
            "timestamp": datetime.now().isoformat(),
        }

    def _find_leader(
        self,
        protocol: str,
        retries: int = 30,
        wait_s: float = 1.0,
        allow_fallback: bool = True,
    ) -> bool:
        port = self._port_for_protocol(protocol)
        for _ in range(retries):
            for node_id, ip in self.nodes.items():
                status, _, body = self._http_request("GET", ip, port, "/status", None, timeout=3)
                if status != 200 or not body:
                    continue
                try:
                    payload = json.loads(body)
                except json.JSONDecodeError:
                    continue
                if payload.get("is_leader") or payload.get("state") == "Leader":
                    if self.leader_ips.get(protocol) != ip:
                        print(f"[+] 发现 {protocol.upper()} leader: {node_id} ({ip})", flush=True)
                    self.leader_ips[protocol] = ip
                    return True
            time.sleep(wait_s)

        if allow_fallback and self.nodes:
            fallback = next(iter(self.nodes.values()))
            self.leader_ips[protocol] = fallback
            print(f"[!] 未检测到 {protocol.upper()} leader，回退到首节点: {fallback}", flush=True)
            return True
        return False

    def _run_write_benchmark(self, writes: int, protocol: str, ip: str) -> Dict:
        port = self._port_for_protocol(protocol)
        latencies: List[float] = []
        errors = 0
        error_503 = 0
        error_500 = 0
        error_timeout = 0
        error_other = 0
        retries = 0
        retry_recovered = 0
        start = time.monotonic()
        max_attempts = 4

        for i in range(writes):
            key = f"bench_{protocol}_{i}"
            value = "".join(random.choices(string.ascii_letters + string.digits, k=32))
            request_ip = self._current_target_ip(protocol, ip)
            recovered = False

            for attempt in range(max_attempts):
                status, elapsed_ms, body, error_kind = self._http_request_detailed(
                    "POST",
                    request_ip,
                    port,
                    "/set",
                    {"key": key, "value": value},
                    timeout=10,
                )

                if status == 200:
                    latencies.append(elapsed_ms)
                    if recovered:
                        retry_recovered += 1
                    break

                if attempt == max_attempts - 1:
                    errors += 1
                    if status == 503:
                        error_503 += 1
                    elif status == 500:
                        error_500 += 1
                    elif error_kind == "timeout":
                        error_timeout += 1
                    else:
                        error_other += 1
                    break

                redirect_ip = self._extract_leader_ip(body)
                if redirect_ip:
                    self.leader_ips[protocol] = redirect_ip
                    request_ip = redirect_ip

                retries += 1
                recovered = True
                self._find_leader(protocol=protocol, retries=25, wait_s=0.3, allow_fallback=False)
                refreshed_ip = self.leader_ips.get(protocol)
                if refreshed_ip:
                    request_ip = refreshed_ip
                time.sleep(min(0.5, 0.1*(attempt + 1)))

        elapsed = time.monotonic() - start
        return {
            "throughput": len(latencies) / elapsed if elapsed > 0 else 0,
            "latencies": latencies,
            "errors": errors,
            "error_503": error_503,
            "error_500": error_500,
            "error_timeout": error_timeout,
            "error_other": error_other,
            "retries": retries,
            "retry_recovered": retry_recovered,
        }

    def _run_latency_benchmark(self, duration: int, protocol: str, ip: str) -> Dict:
        port = self._port_for_protocol(protocol)
        latencies: List[float] = []
        start = time.monotonic()

        while time.monotonic() - start < duration:
            key = f"latency_{protocol}_{int(time.time() * 1000)}"
            request_ip = self._current_target_ip(protocol, ip)
            status, elapsed_ms, body, error_kind = self._http_request_detailed(
                "POST",
                request_ip,
                port,
                "/set",
                {"key": key, "value": "test_value"},
                timeout=10,
            )
            if status == 200:
                latencies.append(elapsed_ms)
            else:
                redirect_ip = self._extract_leader_ip(body)
                if redirect_ip:
                    self.leader_ips[protocol] = redirect_ip
                if status == 503 or error_kind:
                    self._find_leader(
                        protocol=protocol,
                        retries=12,
                        wait_s=0.25,
                        allow_fallback=False,
                    )
            time.sleep(0.1)

        if not latencies:
            return {"p50": 0, "p95": 0, "p99": 0}

        latencies.sort()
        return {
            "p50": self._percentile(latencies, 0.50),
            "p95": self._percentile(latencies, 0.95),
            "p99": self._percentile(latencies, 0.99),
        }

    def _run_read_benchmark(self, reads: int, protocol: str, ip: str) -> Dict:
        port = self._port_for_protocol(protocol)
        seed_keys = [f"read_key_{i}" for i in range(min(10, reads))]
        for key in seed_keys:
            request_ip = self._current_target_ip(protocol, ip)
            for _ in range(3):
                status, _, body, error_kind = self._http_request_detailed(
                    "POST",
                    request_ip,
                    port,
                    "/set",
                    {"key": key, "value": "seed_value"},
                    timeout=10,
                )
                if status == 200:
                    break
                redirect_ip = self._extract_leader_ip(body)
                if redirect_ip:
                    self.leader_ips[protocol] = redirect_ip
                if status == 503 or error_kind:
                    self._find_leader(
                        protocol=protocol,
                        retries=10,
                        wait_s=0.2,
                        allow_fallback=False,
                    )
                    request_ip = self._current_target_ip(protocol, ip)

        latencies: List[float] = []
        errors = 0
        start = time.monotonic()

        if not seed_keys:
            seed_keys = ["read_key_0"]

        for i in range(reads):
            key = seed_keys[i % len(seed_keys)]
            request_ip = self._current_target_ip(protocol, ip)
            status, elapsed_ms, body, error_kind = self._http_request_detailed(
                "GET",
                request_ip,
                port,
                "/get",
                {"key": key},
                timeout=10,
            )
            if status in (200, 404):
                latencies.append(elapsed_ms)
            else:
                errors += 1
                redirect_ip = self._extract_leader_ip(body)
                if redirect_ip:
                    self.leader_ips[protocol] = redirect_ip
                if status == 503 or error_kind:
                    self._find_leader(
                        protocol=protocol,
                        retries=10,
                        wait_s=0.2,
                        allow_fallback=False,
                    )

        elapsed = time.monotonic() - start
        return {
            "throughput": len(latencies) / elapsed if elapsed > 0 else 0,
            "latencies": latencies,
            "errors": errors,
        }

    @staticmethod
    def _percentile(values: List[float], ratio: float) -> float:
        idx = min(int((len(values) - 1) * ratio), len(values) - 1)
        return values[idx]

    @staticmethod
    def _http_request(
        method: str,
        ip: str,
        port: int,
        path: str,
        params: Optional[Dict[str, str]] = None,
        timeout: int = 10,
    ) -> Tuple[Optional[int], float, str]:
        status, elapsed_ms, body, _ = DistributedBenchmark._http_request_detailed(
            method=method,
            ip=ip,
            port=port,
            path=path,
            params=params,
            timeout=timeout,
        )
        return (status, elapsed_ms, body)

    @staticmethod
    def _http_request_detailed(
        method: str,
        ip: str,
        port: int,
        path: str,
        params: Optional[Dict[str, str]] = None,
        timeout: int = 10,
    ) -> Tuple[Optional[int], float, str, str]:
        query = urllib.parse.urlencode(params or {})
        url = f"http://{ip}:{port}{path}"
        if query:
            url = f"{url}?{query}"
        req = urllib.request.Request(url=url, method=method)

        start = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                status = resp.getcode()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="ignore")
            status = exc.code
            elapsed_ms = (time.perf_counter() - start) * 1000
            return (status, elapsed_ms, body, "")
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start) * 1000
            error_kind = "timeout" if DistributedBenchmark._is_timeout_error(exc) else "request"
            return (None, elapsed_ms, "", error_kind)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return (status, elapsed_ms, body, "")

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return True
        if isinstance(exc, urllib.error.URLError):
            reason = exc.reason
            return isinstance(reason, (TimeoutError, socket.timeout))
        return False


def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--cluster-sizes",
        default="3,5,7",
        help="comma-separated cluster sizes to test",
    )
    parser.add_argument(
        "--scenarios",
        default="same-region,cross-region",
        help="comma-separated deployment scenarios",
    )
    parser.add_argument(
        "--writes",
        type=int,
        default=500,
        help="number of writes per benchmark",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=300,
        help="benchmark duration in seconds",
    )
    parser.add_argument(
        "--monitor",
        action="store_true",
        help="collect detailed system metrics",
    )
    parser.add_argument(
        "--ssh-key",
        default="deploy/terraform/same-region/raft-key.pem",
        help="SSH key path for metric collection (used with --skip-deploy)",
    )
    parser.add_argument(
        "--terraform-dir",
        default="",
        help="override terraform scenario directory (for isolated parallel runs)",
    )
    parser.add_argument(
        "--name-prefix",
        default="",
        help="resource name prefix to avoid collisions across parallel runs",
    )
    parser.add_argument("--out", default="results", help="output directory")
    parser.add_argument(
        "--skip-deploy",
        action="store_true",
        help="skip cluster deployment (use existing)",
    )
    parser.add_argument("--skip-tcp", action="store_true", help="skip TCP benchmarks")
    parser.add_argument("--skip-quic", action="store_true", help="skip QUIC benchmarks")

    args = parser.parse_args()

    cluster_sizes = [int(c.strip()) for c in args.cluster_sizes.split(",") if c.strip()]
    scenarios = [s.strip() for s in args.scenarios.split(",") if s.strip()]
    if any(size < 3 for size in cluster_sizes):
        raise SystemExit("cluster size must be >= 3")
    if args.skip_tcp and args.skip_quic:
        raise SystemExit("cannot skip both tcp and quic benchmarks")
    if args.terraform_dir and len(scenarios) != 1:
        raise SystemExit("--terraform-dir requires exactly one scenario")

    os.makedirs(args.out, exist_ok=True)

    all_results: List[Dict] = []

    print("=" * 80)
    print("分布式性能测试框架 - TCP vs QUIC 对比")
    print("=" * 80)
    print(f"集群规模: {cluster_sizes}")
    print(f"场景: {scenarios}")
    print(f"写操作: {args.writes}")
    print(f"监控: {'启用' if args.monitor else '禁用'}")
    print("=" * 80)

    for scenario in scenarios:
        for cluster_size in cluster_sizes:
            manager = AwsClusterManager(
                cluster_size,
                scenario,
                terraform_dir=args.terraform_dir or None,
                name_prefix=args.name_prefix,
            )
            collector = None
            try:
                if not args.skip_deploy:
                    nodes = manager.deploy()
                else:
                    env_kv = _load_env_file(manager.cluster_env)
                    nodes = _load_nodes_from_env(env_kv)
                    manager.instances = _load_instances_from_env(env_kv)
                    manager.node_regions = _load_regions_from_env(env_kv)
                    manager.ssh_key_file = env_kv.get("KEY_FILE", args.ssh_key)
                    manager.ssh_user = env_kv.get("SSH_USER", "ec2-user")

                if not nodes:
                    print(f"[!] 无法获取 {cluster_size} 节点 {scenario} 集群信息", flush=True)
                    continue

                if args.monitor:
                    collector = MetricsCollector(
                        nodes,
                        manager.ssh_key_file,
                        manager.ssh_user,
                        manager.instances,
                        manager.node_regions,
                    )
                    collector.collect_baseline()
                    print("[+] 基线指标已收集", flush=True)

                benchmark = DistributedBenchmark(nodes, cluster_size, scenario)

                if not args.skip_quic:
                    quic_result = benchmark.run_benchmark(args.writes, args.duration, "quic")
                    if quic_result:
                        all_results.append(quic_result)

                if not args.skip_tcp:
                    tcp_result = benchmark.run_benchmark(args.writes, args.duration, "tcp")
                    if tcp_result:
                        all_results.append(tcp_result)

                if collector is not None:
                    collector.collect_raft_metrics()
                    print("[+] Raft 指标已收集", flush=True)

            except Exception as exc:
                print(f"[!] 测试失败: {exc}", flush=True)
            finally:
                if not args.skip_deploy:
                    manager.teardown()

    _save_results(all_results, args.out)
    _generate_report(all_results, args.out)

    print(f"\n[+] 所有测试完成，结果保存到 {args.out}", flush=True)


def _load_env_file(config_file: str) -> Dict[str, str]:
    env = {}
    if not os.path.exists(config_file):
        return env
    with open(config_file, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k] = v
    return env


def _load_nodes_from_env(env: Dict[str, str]) -> Dict[str, str]:
    nodes = {}
    for key, value in env.items():
        if key.endswith("_IP"):
            node_id = key[:-3].lower()
            nodes[node_id] = value
    return dict(sorted(nodes.items(), key=lambda kv: _node_sort_key(kv[0])))


def _load_instances_from_env(env: Dict[str, str]) -> Dict[str, str]:
    instances = {}
    for key, value in env.items():
        if key.endswith("_INSTANCE_ID"):
            node_id = key[: -len("_INSTANCE_ID")].lower()
            instances[node_id] = value
    return dict(sorted(instances.items(), key=lambda kv: _node_sort_key(kv[0])))


def _load_regions_from_env(env: Dict[str, str]) -> Dict[str, str]:
    regions = {}
    for key, value in env.items():
        if key.endswith("_REGION"):
            node_id = key[: -len("_REGION")].lower()
            regions[node_id] = value
    return dict(sorted(regions.items(), key=lambda kv: _node_sort_key(kv[0])))


def _save_results(results: List[Dict], output_dir: str):
    if not results:
        print("[!] 无可保存结果", flush=True)
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = os.path.join(output_dir, f"distributed_benchmark_{ts}.csv")

    fieldnames = [
        "protocol",
        "cluster_size",
        "scenario",
        "write_throughput",
        "write_p50_ms",
        "write_p95_ms",
        "write_p99_ms",
        "read_throughput",
        "write_errors",
        "write_error_503",
        "write_error_500",
        "write_error_timeout",
        "write_error_other",
        "write_retries",
        "write_retry_recovered",
        "read_errors",
        "timestamp",
    ]

    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in results:
            writer.writerow(row)

    print(f"[+] 结果保存到 {csv_path}", flush=True)


def _generate_report(results: List[Dict], output_dir: str):
    if not results:
        print("[!] 无可生成报告的数据", flush=True)
        return

    grouped: Dict[Tuple[str, str], List[Dict]] = {}
    for row in results:
        key = (row["protocol"], row["scenario"])
        grouped.setdefault(key, []).append(row)

    summary: List[str] = []
    summary.append("# 分布式性能测试报告\n")
    summary.append(f"生成时间: {datetime.now().isoformat()}\n\n")

    for (protocol, scenario), rows in sorted(grouped.items()):
        summary.append(f"## {protocol.upper()} - {scenario}\n\n")
        summary.append(
            "| 集群规模 | 写吞吐(ops/s) | 写p99(ms) | 读吞吐(ops/s) | 写错误 | 503 | 500 | 超时 |\n"
        )
        summary.append("|---------|-------------|---------|---------------|-------|-----|-----|------|\n")

        for row in sorted(rows, key=lambda x: x["cluster_size"]):
            summary.append(
                f"| {row['cluster_size']} | {row['write_throughput']:.1f} | "
                f"{row['write_p99_ms']:.2f} | {row['read_throughput']:.1f} | "
                f"{row.get('write_errors', 0)} | "
                f"{row.get('write_error_503', 0)} | "
                f"{row.get('write_error_500', 0)} | "
                f"{row.get('write_error_timeout', 0)} |\n"
            )
        summary.append("\n")

    summary.append("## TCP vs QUIC 对比\n\n")
    same_region_quic = [
        r for r in results if r["protocol"] == "quic" and r["scenario"] == "same-region"
    ]
    same_region_tcp = [
        r for r in results if r["protocol"] == "tcp" and r["scenario"] == "same-region"
    ]

    if same_region_quic and same_region_tcp:
        for quic_row in same_region_quic:
            tcp_row = next(
                (t for t in same_region_tcp if t["cluster_size"] == quic_row["cluster_size"]),
                None,
            )
            if not tcp_row:
                continue
            tput_ratio = (
                quic_row["write_throughput"] / tcp_row["write_throughput"]
                if tcp_row["write_throughput"] > 0
                else 0
            )
            latency_ratio = (
                quic_row["write_p99_ms"] / tcp_row["write_p99_ms"]
                if tcp_row["write_p99_ms"] > 0
                else 0
            )

            summary.append(f"### {quic_row['cluster_size']} 节点\n")
            summary.append(f"- QUIC 吞吐: {quic_row['write_throughput']:.1f} ops/s\n")
            summary.append(f"- TCP 吞吐: {tcp_row['write_throughput']:.1f} ops/s\n")
            summary.append(f"- 吞吐比 (QUIC/TCP): {tput_ratio:.2f}x\n")
            summary.append(f"- QUIC p99: {quic_row['write_p99_ms']:.2f} ms\n")
            summary.append(f"- TCP p99: {tcp_row['write_p99_ms']:.2f} ms\n")
            summary.append(f"- 延迟比 (QUIC/TCP): {latency_ratio:.2f}x\n\n")

    report_path = os.path.join(output_dir, "distributed_benchmark_report.md")
    with open(report_path, "w", encoding="utf-8") as f:
        f.writelines(summary)
    print(f"[+] 报告保存到 {report_path}", flush=True)


if __name__ == "__main__":
    main()
