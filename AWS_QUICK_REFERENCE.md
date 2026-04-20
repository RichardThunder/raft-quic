# 🔑 AWS 凭据和资源快速参考

## 📋 所需凭据

### AWS IAM 访问密钥

| 项目 | 说明 | 获取方式 |
|------|------|---------|
| **Access Key ID** | 用户标识 | AWS IAM 控制台 |
| **Secret Access Key** | 密钥 (仅显示一次!) | AWS IAM 控制台 |
| **Default Region** | 默认区域 | 自选 (推荐: ap-east-1) |

### 获取步骤 (5 分钟)

```
1. 登录 https://console.aws.amazon.com/
2. 进入 IAM → Users → 你的用户名
3. Security Credentials → Create access key
4. 下载 .csv 文件（保管好！）
5. 运行: aws configure
```

---

## 🏗️ AWS 资源清单

### 同区域部署 (same-region)

```
┌─────────────────────────────────────────────────────┐
│ Hong Kong (ap-east-1): 3 个 t3.micro 实例           │
├─────────────────────────────────────────────────────┤
│ 资源                 数量    成本/小时                │
├─────────────────────────────────────────────────────┤
│ EC2 t3.micro        3     $0.0312                   │
│ Security Groups     3     $0.00                     │
│ SSH Key Pairs       3     $0.00                     │
│ EBS 存储 (8GB)      3     免费 (Free Tier)         │
├─────────────────────────────────────────────────────┤
│ 总计                        $0.0312/小时             │
│                             ~$7.50/天                │
│                             ~$225/月                 │
└─────────────────────────────────────────────────────┘
```

### 跨区域部署 (cross-region)

```
┌─────────────────────────────────────────────────────┐
│ 香港 + 美国东 + 欧洲西: 3 个 t3.micro 实例          │
├─────────────────────────────────────────────────────┤
│ 区域              成本/小时  说明                    │
├─────────────────────────────────────────────────────┤
│ ap-east-1 (HK)   $0.0520   节点 1                   │
│ us-east-1        $0.0104   节点 2                   │
│ eu-west-1        $0.0124   节点 3                   │
├─────────────────────────────────────────────────────┤
│ 总计              $0.0748/小时                       │
│ 跨区域出站流量    $0.01/GB  (重要!)                 │
│ 月度成本          ~$54 (纯计算)                     │
│                   +$20-50 (数据传输)                │
└─────────────────────────────────────────────────────┘
```

---

## 🛠️ 所需工具

| 工具 | 版本要求 | 检查命令 | 安装 |
|------|----------|---------|------|
| **Terraform** | ≥ 1.5 | `terraform -v` | `brew install terraform` |
| **AWS CLI** | v2 | `aws --version` | `brew install awscli` |
| **Go** | ≥ 1.23 | `go version` | `brew install go` |
| **SSH** | 任何 | `ssh -V` | macOS 内置 |
| **Python3** | ≥ 3.7 | `python3 --version` | macOS 内置 |

---

## 📊 每小时成本对比

```
操作                    时间      成本        说明
════════════════════════════════════════════════════════
写入基准 (100 操作)     5 分      $0.004    小规模测试
完整基准 (500 操作)     20 分     $0.010    中等规模
跨区域对比测试          40 分     $0.050    完整测试
24 小时监控             1 天      $0.750    生产验证
````

---

## ✅ 所需权限 (IAM 策略)

最小权限集合:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "RaftQuicEC2",
      "Effect": "Allow",
      "Action": [
        "ec2:RunInstances",
        "ec2:TerminateInstances",
        "ec2:DescribeInstances",
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
        "ec2:CreateTags",
        "ec2:DeleteTags"
      ],
      "Resource": "*"
    }
  ]
}
```

---

## 🚀 快速启动命令

```bash
# 1. 配置 AWS (一次性)
aws configure
# 输入: Access Key ID, Secret Key, Region (ap-east-1), Format (json)

# 2. 验证配置
aws sts get-caller-identity
# 应输出你的 AWS 账户信息

# 3. 部署 (同区域)
./deploy/deploy.sh same-region
# 等待 ~60 秒

# 4. 验证
curl http://<node1_ip>:8001/status

# 5. 运行测试
python3 scripts/benchmark.py \
  --host <node1_ip> \
  --ports 8001,8001,8001 \
  --writes 100 \
  --concurrency 1,4,8

# 6. 清理
./deploy/teardown.sh same-region
```

---

## 📁 配置文件位置

部署后自动生成:

```
deploy/
├── cluster.env                    # ← 节点 IP 和 SSH 密钥路径
├── terraform/same-region/
│   ├── raft-key.pem              # ← SSH 私钥
│   ├── terraform.tfstate          # ← 部署状态
│   └── .terraform/                # ← 缓存
└── terraform/cross-region/
    └── (同样结构)
```

---

## 🔐 凭据安全清单

- [ ] 访问密钥已下载并安全存储
- [ ] `aws configure` 已运行
- [ ] `.aws/credentials` 文件只对你可读 (chmod 600)
- [ ] SSH 密钥 (raft-key.pem) 不在 git 中
- [ ] 不在代码中硬编码凭据
- [ ] 完成测试后立即销毁资源
- [ ] 定期旋转访问密钥

---

## 💰 成本控制

### Free Tier (首 12 个月)

- 750 小时 EC2 t2.micro/t3.micro
- 相当于: **连续 24/7 × 31 天**

### 预算告警

```bash
# 设置月度预算上限
aws budgets create-budget \
  --account-id <your-account-id> \
  --budget BudgetName=raft-quic-monthly,BudgetLimit='{"Amount":"50","Unit":"USD"}',TimeUnit=MONTHLY,BudgetType=COST
```

### 最小化成本

1. **按需部署**: 测试后立即销毁 (`./deploy/teardown.sh`)
2. **选择便宜区域**: ap-east-1 (香港) 比 us-east-1 便宜
3. **使用 Free Tier**: 新账户 12 个月免费
4. **避免 Elastic IP**: 如果未连接则收费

---

## 🔍 故障排除速查

| 问题 | 症状 | 解决方案 |
|------|------|---------|
| 无凭据 | `NoCredentialsError` | 运行 `aws configure` |
| 权限不足 | `UnauthorizedOperation` | 检查 IAM 策略 |
| Terraform 失败 | 初始化错误 | `rm -rf .terraform*` 然后重试 |
| SSH 超时 | 无法连接实例 | 检查安全组、IP 地址 |
| 配额超限 | `InsufficientInstanceCapacity` | 检查 AWS 配额或选择不同区域 |

---

## 📊 预期性能指标

### 同区域 (ap-east-1)

```
写吞吐:      800-900 ops/sec
读吞吐:      1500+ ops/sec
p99 延迟:    <20 ms
选举时间:    <500 ms
网络延迟:    <5 ms
```

### 跨区域 (HK + US + EU)

```
写吞吐:      50-100 ops/sec   (↓ 8-10x)
读吞吐:      100-200 ops/sec  (↓ 10x)
p99 延迟:    1500-2500 ms     (↑ 100x)
选举时间:    2-5 s            (↑ 5-10x)
网络延迟:    150-300 ms
```

---

## 🎯 推荐工作流

### 开发/测试 (最小成本)

```bash
# 成本: ~$0.04
# 时间: 10 分钟

./deploy/deploy.sh same-region
sleep 60
python3 scripts/benchmark.py --writes 50 --concurrency 1,4
./deploy/teardown.sh same-region
```

### 完整基准 (中等成本)

```bash
# 成本: ~$0.15
# 时间: 30 分钟

# 同区域
./deploy/deploy.sh same-region
sleep 60
python3 scripts/benchmark.py --writes 200 --concurrency 1,4,8,16
./deploy/teardown.sh same-region

# 跨区域
./deploy/deploy.sh cross-region
sleep 120
python3 scripts/benchmark.py --writes 50 --concurrency 1,2,4
./deploy/teardown.sh cross-region
```

### 长期监控 (持续成本)

```bash
# 成本: ~$2-3/天
# 时间: 持续运行

# 部署一次
./deploy/deploy.sh same-region

# 定期运行基准测试
0 */6 * * * python3 scripts/benchmark.py --host <ip>

# 月底销毁
./deploy/teardown.sh same-region
```

---

## 📞 支持资源

- AWS IAM: https://docs.aws.amazon.com/iam/
- EC2 文档: https://docs.aws.amazon.com/ec2/
- AWS CLI: https://docs.aws.amazon.com/cli/
- 定价计算器: https://calculator.aws/

---

## ✨ 总结

| 项目 | 需求 |
|------|------|
| **凭据** | AWS 访问密钥 ID + Secret |
| **工具** | Terraform, AWS CLI, Go, SSH |
| **资源** | 3×t3.micro EC2 + 安全组 + SSH 密钥 |
| **成本** | $0.03-0.07/小时 (同-跨区域) |
| **部署时间** | ~60-120 秒 |
| **清理时间** | ~30 秒 |

**推荐**: 同区域测试 (成本低, 延迟低)

---

**最后更新**: 2026-04-19  
**状态**: ✅ 准备就绪
