# 🚀 AWS 分布式性能测试完整指南

本指南说明如何在 AWS 上部署 Raft-over-QUIC 集群并运行分布式性能测试。

---

## 📋 前置条件

### 1. 本地工具安装

```bash
# macOS
brew install terraform aws-cli

# 或手动安装
# - Terraform ≥ 1.5: https://www.terraform.io/downloads
# - AWS CLI v2: https://aws.amazon.com/cli/
# - Go ≥ 1.23 (已有)

# 验证安装
terraform -v
aws --version
go version
```

### 2. AWS 账户设置

需要一个有效的 AWS 账户（如果没有，创建免费套餐账户）

---

## 🔑 AWS 凭据配置

### 方案 A：使用 AWS CLI（推荐）

```bash
# 1. 配置凭据
aws configure

# 提示输入以下信息：
AWS Access Key ID [None]: YOUR_ACCESS_KEY
AWS Secret Access Key [None]: YOUR_SECRET_KEY
Default region name [None]: ap-east-1          # 或其他区域
Default output format [None]: json
```

### 方案 B：使用环境变量

```bash
export AWS_ACCESS_KEY_ID="your_access_key"
export AWS_SECRET_ACCESS_KEY="your_secret_key"
export AWS_DEFAULT_REGION="ap-east-1"
```

### 方案 C：使用 IAM 角色（生产环境）

如果在 EC2 上运行脚本，使用 IAM 实例角色避免硬编码凭据。

### 获取 AWS 凭据

1. 登录 [AWS 控制台](https://console.aws.amazon.com/)
2. 进入 **IAM** → **用户** → 你的用户名
3. **安全凭证** → **创建访问密钥**
4. 下载 `.csv` 文件（保存安全位置）

**所需权限** (IAM 策略):
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:TerminateInstances",
        "ec2:DescribeInstances",
        "ec2:DescribeInstanceStatus",
        "ec2:CreateSecurityGroup",
        "ec2:DeleteSecurityGroup",
        "ec2:AuthorizeSecurityGroupIngress",
        "ec2:RevokeSecurityGroupIngress",
        "ec2:CreateKeyPair",
        "ec2:DeleteKeyPair",
        "ec2:ImportKeyPair",
        "ec2:DescribeKeyPairs",
        "ec2:DescribeImages",
        "ec2:DescribeSecurityGroups",
        "ec2:DescribeTags",
        "ec2:CreateTags",
        "ec2:DeleteTags"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## 🏗️ AWS 资源清单

### 按场景分类

#### 同区域部署 (same-region)

```
香港 (ap-east-1):
├── EC2 t3.micro × 3 节点
├── 安全组 × 3
├── SSH 密钥对 × 3
└── 弹性 IP (可选)

预计成本: $0.04/小时 × 3 = $0.12/小时
          = $2.88/天 (运行 24 小时)
          = $86.40/月
```

#### 跨区域部署 (cross-region)

```
香港 (ap-east-1):     node1 (t3.micro)
美国东 (us-east-1):   node2 (t3.micro)
欧洲西 (eu-west-1):   node3 (t3.micro)

预计成本: 
  - ap-east-1:  $0.0520/小时
  - us-east-1:  $0.0104/小时
  - eu-west-1:  $0.0124/小时
  总计: $0.0748/小时
      = $1.80/天
      = $53.96/月
```

### 每个节点的资源详情

| 资源 | 规格 | 成本 |
|------|------|------|
| **EC2 实例** | t3.micro (1 vCPU, 1 GB RAM) | $0.0104/h |
| **存储** | 8 GB EBS gp3 | 免费 (Free Tier) |
| **数据传输** | 出站仅收费 | $0.01/GB |
| **安全组** | 无成本 | — |
| **密钥对** | 无成本 | — |
| **弹性 IP** | 如果分配但未使用 | $0.005/h |

---

## 📦 部署步骤

### Step 1: 配置 AWS 凭据

```bash
aws configure
# 输入 Access Key ID, Secret Access Key, 区域, 输出格式
```

### Step 2: 验证凭据

```bash
aws sts get-caller-identity
# 输出应显示你的 AWS 账户信息
```

### Step 3: 构建二进制文件

```bash
cd /Users/richard/code/raft-quic
GOOS=linux GOARCH=amd64 go build -o raftd-linux-amd64 ./cmd/raftd
```

### Step 4: 部署集群

#### 同区域 (Low Latency)

```bash
./deploy/deploy.sh same-region

# 输出示例:
# [INFO]   Scenario : same-region
# [INFO]   HB timeout: 150ms  |  Election timeout: 300ms
# [OK]     Binary: ./raftd-linux-amd64  (13M)
# [INFO]   Initialising Terraform...
# [INFO]   Applying (this takes ~60 s for EC2 to boot)...
# [OK]     Cluster deployed!
# [OK]     Nodes: 
#          node1: 18.162.100.50 (ap-east-1a)
#          node2: 18.162.100.51 (ap-east-1b)
#          node3: 18.162.100.52 (ap-east-1c)
```

#### 跨区域 (High Latency Test)

```bash
./deploy/deploy.sh cross-region

# Raft timeouts 自动调整为:
# - Heartbeat: 1s
# - Election: 2s
# (因为跨区域 RTT 150-300ms)
```

### Step 5: 验证部署

```bash
# 查看生成的配置
cat deploy/cluster.env

# 测试 SSH 连接
ssh -i deploy/terraform/same-region/raft-key.pem \
    ec2-user@<node1_ip> \
    "ps aux | grep raftd"

# 验证集群健康
curl http://<node1_ip>:8001/status
curl http://<node2_ip>:8001/status
curl http://<node3_ip>:8001/status
```

---

## 📊 运行性能测试

### Step 1: 等待集群稳定

集群需要 30-60 秒进行 leader 选举。

```bash
# 检查 leader
curl http://<node1_ip>:8001/leader
# 输出应显示某个节点作为 leader
```

### Step 2: 运行基准测试

```bash
cd /Users/richard/code/raft-quic

# 使用 AWS 节点运行基准测试
python3 scripts/benchmark.py \
  --host <node1_ip> \
  --ports 8001,8001,8001 \
  --writes 200 \
  --concurrency 1,4,8,16 \
  --out test_results

# 或使用现有的 AWS 基准脚本
python3 scripts/benchmark_aws.py \
  --env deploy/cluster.env \
  --compare \
  --same-env deploy/cluster-same.env \
  --cross-env deploy/cluster-cross.env
```

### Step 3: 生成报告

```bash
# 生成可视化
python3 scripts/visualize_svg.py --output test_results

# 生成 HTML 报告
python3 scripts/generate_report.py \
  --benchmark test_results/benchmark_*.csv \
  --output test_results/aws_report.html

# 查看报告
open test_results/aws_report.html
```

---

## 💰 成本估算

### 同区域测试 (1 小时)

```
3 × t3.micro @ $0.0104/h = $0.0312
数据传输 (出站 ~100 MB) = ~$0.001
总计: ~$0.035 (~3 分）
```

### 跨区域测试 (1 小时)

```
跨区域出站流量更多 (跨境数据传输)
数据传输: ~$0.01/GB (跨区域)
总计: ~$0.085 (~8 分）
```

### 月度成本 (24/7 运行)

| 场景 | 月成本 |
|------|--------|
| 同区域 | ~$90 |
| 跨区域 | ~$54 |
| 开发 (按需) | $1-5 |

**节省成本的方法**:
- 使用 **Free Tier** (首 12 个月)
- 按需部署测试后销毁 (**立即销毁**)
- 使用 **Reserved Instances** (生产环保)
- 使用 **Spot Instances** (临时)

---

## 🧹 清理资源

### 销毁集群

```bash
# 销毁同区域集群
./deploy/teardown.sh same-region

# 销毁跨区域集群
./deploy/teardown.sh cross-region

# 验证销毁
aws ec2 describe-instances \
  --filters "Name=tag:Project,Values=raft-quic" \
  --query 'Reservations[].Instances[].State.Name'
# 应返回空或 "terminated"
```

### 删除 SSH 密钥

```bash
# AWS 控制台删除密钥对
aws ec2 delete-key-pair --key-name raft-quic-same

# 本地文件
rm -f deploy/terraform/*/raft-key.pem
```

### 验证完全清理

```bash
# 检查残留安全组
aws ec2 describe-security-groups \
  --filters "Name=group-name,Values=raft-quic-*" \
  --query 'SecurityGroups[].GroupId'

# 手动删除（如有）
aws ec2 delete-security-group --group-id sg-xxxxx
```

---

## 🔍 故障排除

### 问题 1: "No credentials found"

```bash
# 检查凭据
aws configure list

# 重新配置
aws configure

# 或设置环境变量
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
```

### 问题 2: Terraform 初始化失败

```bash
# 清理 Terraform 缓存
rm -rf deploy/terraform/same-region/.terraform*
rm -rf deploy/terraform/cross-region/.terraform*

# 重试
cd deploy/terraform/same-region
terraform init -upgrade
```

### 问题 3: EC2 实例无法启动

```bash
# 检查 AWS 配额
aws service-quotas list-service-quotas \
  --service-code ec2 \
  --query 'ServiceQuotas[?contains(QuotaName, `Running On-Demand`)]'

# 检查区域可用性
aws ec2 describe-instance-types \
  --instance-types t3.micro \
  --query 'InstanceTypes[].SupportedArchitectures'
```

### 问题 4: SSH 连接超时

```bash
# 验证安全组
aws ec2 describe-security-groups \
  --group-names "raft-quic-node1" \
  --query 'SecurityGroups[].IpPermissions'

# 检查公网 IP
aws ec2 describe-instances \
  --filters "Name=tag:Node,Values=node1" \
  --query 'Reservations[].Instances[].PublicIpAddress'

# 测试 SSH 连接
ssh -i deploy/terraform/same-region/raft-key.pem \
    -vvv ec2-user@<IP>
```

---

## 📈 性能测试指南

### 同区域 vs 跨区域对比

| 指标 | 同区域 | 跨区域 | 预期差异 |
|------|--------|--------|----------|
| 延迟 (p50) | <5ms | 150-300ms | 30-60x |
| 吞吐量 | 846 ops/s | 50-100 ops/s | 8-16x |
| Leader 选举 | 300ms | 2-3s | 6-10x |
| 网络成本 | 低 | 高 | 数倍 |

### 推荐测试计划

```bash
# 第 1 步: 同区域基准 (20 分钟)
./deploy/deploy.sh same-region
python3 scripts/benchmark.py --writes 500 --concurrency 1,4,8
./deploy/teardown.sh same-region

# 第 2 步: 跨区域基准 (20 分钟)
./deploy/deploy.sh cross-region
python3 scripts/benchmark.py --writes 100 --concurrency 1,2,4
./deploy/teardown.sh cross-region

# 总成本: ~$0.50
# 总时间: 40 分钟 + 15 分钟部署/清理
```

---

## 📊 生成报告

### 对比报告

```bash
python3 scripts/benchmark_aws.py --compare \
  --same-env deploy/cluster-same.env \
  --cross-env deploy/cluster-cross.env

# 输出:
# Same-Region Performance:
#   Throughput: 846 ops/s
#   p99 Latency: 18.3 ms
#
# Cross-Region Performance:
#   Throughput: 68 ops/s
#   p99 Latency: 2400 ms
#
# Difference: 12.4x throughput degradation
```

### HTML 报告

```bash
python3 scripts/generate_report.py \
  --benchmark test_results/benchmark_aws.csv \
  --output test_results/aws_comparison_report.html

open test_results/aws_comparison_report.html
```

---

## 🔒 安全最佳实践

### 1. 保护 AWS 凭据

```bash
# ❌ 不要在 git 中提交凭据
echo "AWS_ACCESS_KEY_ID=" > .env
git add .gitignore && git commit -m "Add .env to gitignore"

# ✅ 使用环境变量
export AWS_ACCESS_KEY_ID="..."

# ✅ 使用 IAM 角色 (EC2)
# 分配角色到 EC2 实例，不使用凭据
```

### 2. 限制安全组

```bash
# ❌ 当前: 允许所有 IP (0.0.0.0/0)
# ✅ 改进: 限制到你的 IP
aws ec2 authorize-security-group-ingress \
  --group-id sg-xxxxx \
  --protocol tcp \
  --port 22 \
  --cidr YOUR_IP/32
```

### 3. 旋转密钥

```bash
# 定期更换 AWS 访问密钥
aws iam create-access-key --user-name YOUR_USER
aws iam delete-access-key --user-name YOUR_USER --access-key-id OLD_KEY
```

### 4. 监控成本

```bash
# 启用 AWS Cost Explorer
# 或使用 AWS CLI 查询
aws ce get-cost-and-usage \
  --time-period Start=2026-04-01,End=2026-04-30 \
  --granularity DAILY \
  --metrics BlendedCost
```

---

## 📚 参考资源

- AWS EC2 文档: https://docs.aws.amazon.com/ec2/
- Terraform AWS: https://registry.terraform.io/providers/hashicorp/aws/latest
- AWS CLI 参考: https://docs.aws.amazon.com/cli/
- 免费套餐: https://aws.amazon.com/free/

---

## ✅ 部署检查清单

- [ ] 安装了 Terraform ≥ 1.5
- [ ] 安装了 AWS CLI v2
- [ ] 创建了 AWS IAM 用户和访问密钥
- [ ] 配置了 AWS 凭据 (`aws configure`)
- [ ] 验证了凭据 (`aws sts get-caller-identity`)
- [ ] 构建了 Linux 二进制文件
- [ ] 有足够的 AWS 账户配额
- [ ] 了解了预期成本
- [ ] 准备好销毁资源的计划

---

## 🚀 快速命令

```bash
# 全自动部署和测试
./deploy/deploy.sh same-region
sleep 60  # 等待集群启动
python3 scripts/benchmark.py --writes 100 --concurrency 1,4,8
python3 scripts/generate_report.py --output test_results/aws_report.html
./deploy/teardown.sh same-region

# 总耗时: ~10 分钟
# 成本: ~$0.02
```

---

**创建时间**: 2026-04-19  
**版本**: 1.0  
**状态**: 准备就绪 ✅
