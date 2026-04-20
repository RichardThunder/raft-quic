# 🔑 如何获取 AWS Access Key + Secret Key

完整的分步指南，包括安全建议。

---

## 📋 前置条件

你需要：
- ✅ AWS 账户（免费或付费）
- ✅ 可以访问互联网的浏览器
- ✅ 账户的登录邮箱和密码

**如果没有 AWS 账户**：
1. 访问 https://aws.amazon.com/
2. 点击 "Create an AWS Account"
3. 按步骤创建账户（可选择 Free Tier）

---

## 🚀 获取访问密钥的 3 种方法

### 方法 1：根账户密钥（❌ 不推荐 - 仅用于应急）

根账户有完全的 AWS 权限，不应日常使用。

**只在必要时使用（如创建 IAM 用户时）**

---

### 方法 2：IAM 用户密钥（✅ 推荐）

创建一个有限权限的 IAM 用户，更安全。

#### Step 1: 登录 AWS 控制台

```
访问: https://console.aws.amazon.com/
输入: 
  - 邮箱 (AWS 账户邮箱)
  - 密码
```

![登录](https://docs.aws.amazon.com/images/console/latest/userguide/images/console-signin.png)

#### Step 2: 进入 IAM 控制台

选项 A：搜索方式
```
1. 点击顶部搜索框
2. 输入 "IAM"
3. 点击 "IAM" 服务
```

选项 B：服务菜单
```
1. 点击左上角 "Services"
2. 搜索 "IAM"
3. 点击 "IAM"
```

#### Step 3: 创建 IAM 用户

```
1. 左侧菜单 → "Users"
2. 点击 "Create user" 按钮
3. 用户名输入: "raft-quic-test" (或自定义)
4. 勾选 "Provide user access to AWS Management Console" (可选)
5. 点击 "Next"
```

**用户名示例**:
```
raft-quic-test
raft-benchmark
dev-raft
```

#### Step 4: 设置权限

```
1. 选择 "Attach policies directly"
2. 搜索并选中:
   □ AmazonEC2FullAccess (开发用)
   或
   □ 自定义策略 (生产用)
3. 点击 "Next"
```

**权限策略** (选择一个):

**开发版** (简单):
- `AmazonEC2FullAccess` ✅

**生产版** (最小权限):
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

#### Step 5: 创建访问密钥

创建用户后：

```
1. 用户列表找到你创建的用户
2. 点击用户名进入详情页
3. 选项卡 "Security credentials"
4. 向下滚动到 "Access keys"
5. 点击 "Create access key"
6. 选择用途:
   - "Local code development" (开发/测试)
   - "Other" (其他)
7. 点击 "Next"
8. （可选）添加标签描述用途
9. 点击 "Create access key"
```

#### Step 6: 保存凭据（非常重要！）

**你将看到**:
```
Access key ID:     AKIAIOSFODNN7EXAMPLE
Secret access key: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
```

⚠️ **重要**: Secret access key 仅显示一次！

**立即**:
1. ✅ 下载 `.csv` 文件 → 安全保管
2. ✅ 或复制两个密钥 → 保存到密码管理器
3. ❌ 不要在 Slack/邮件/代码中分享

---

## 🔐 配置本地凭据

### 方法 A：使用 `aws configure`（推荐）

```bash
aws configure

# 会依次提示输入：
AWS Access Key ID [None]: AKIAIOSFODNN7EXAMPLE
AWS Secret Access Key [None]: wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
Default region name [None]: ap-east-1
Default output format [None]: json
```

**验证配置**:
```bash
aws sts get-caller-identity

# 应输出：
{
    "UserId": "AIDACL6I5234EXAMPLE:user",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/raft-quic-test"
}
```

凭据存储位置:
```
~/.aws/credentials
~/.aws/config
```

### 方法 B：使用环境变量

```bash
export AWS_ACCESS_KEY_ID="AKIAIOSFODNN7EXAMPLE"
export AWS_SECRET_ACCESS_KEY="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
export AWS_DEFAULT_REGION="ap-east-1"

# 验证
aws sts get-caller-identity
```

### 方法 C：编辑配置文件

```bash
# 创建或编辑凭据文件
nano ~/.aws/credentials

# 内容：
[default]
aws_access_key_id = AKIAIOSFODNN7EXAMPLE
aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY

# 编辑配置文件
nano ~/.aws/config

# 内容：
[default]
region = ap-east-1
output = json
```

权限设置:
```bash
chmod 600 ~/.aws/credentials
chmod 600 ~/.aws/config
```

---

## 🔍 验证凭据

### 测试 1: 检查身份

```bash
aws sts get-caller-identity

# 输出示例：
{
    "UserId": "AIDACL6I5234EXAMPLE:user",
    "Account": "123456789012",
    "Arn": "arn:aws:iam::123456789012:user/raft-quic-test"
}
```

### 测试 2: 列出 EC2 实例

```bash
aws ec2 describe-instances

# 如果没有实例，输出：
{
    "Reservations": []
}
```

### 测试 3: 检查权限

```bash
aws ec2 describe-instance-types \
  --instance-types t3.micro \
  --region ap-east-1

# 应成功返回 t3.micro 的配置信息
```

---

## 🚀 现在你可以部署了

验证凭据成功后：

```bash
cd /Users/richard/code/raft-quic

# 部署集群
./deploy/deploy.sh same-region

# 或
./deploy/deploy.sh cross-region
```

---

## 🔒 安全最佳实践

### 保护你的凭据

✅ **DO**:
- 保管好 AWS 凭据文件
- 定期旋转访问密钥
- 为不同用途创建不同用户
- 使用 IAM 角色（生产环境）
- 启用 MFA（多因素认证）

❌ **DON'T**:
- 在代码中硬编码凭据
- 在 Git 仓库中提交凭据
- 在 Slack/邮件中分享凭据
- 使用根账户凭据进行开发
- 在公开仓库中包含 `.aws/credentials`

### `.gitignore` 配置

```bash
# .gitignore
.aws/
.env
*.pem
*.key
credentials.json
```

### 凭据轮转

```bash
# 创建新密钥
aws iam create-access-key --user-name raft-quic-test

# 删除旧密钥
aws iam delete-access-key \
  --user-name raft-quic-test \
  --access-key-id AKIAIOSFODNN7EXAMPLE

# 更新本地配置
aws configure
```

---

## 🔄 密钥失泄露怎么办

### 紧急响应

```bash
# 1. 立即禁用被泄露的密钥
aws iam update-access-key-status \
  --user-name raft-quic-test \
  --access-key-id AKIAIOSFODNN7EXAMPLE \
  --status Inactive

# 2. 创建新密钥
aws iam create-access-key --user-name raft-quic-test

# 3. 更新本地配置
aws configure

# 4. 删除旧密钥
aws iam delete-access-key \
  --user-name raft-quic-test \
  --access-key-id AKIAIOSFODNN7EXAMPLE
```

---

## 📊 故障排除

### 问题 1: "InvalidUserID.NotFound"

```
错误: InvalidUserID.NotFound - User: arn:aws:iam::...
原因: IAM 用户不存在或权限不足
解决: 
  1. 检查用户是否创建
  2. 检查 IAM 权限
  3. 使用根账户重新创建
```

### 问题 2: "UnauthorizedOperation"

```
错误: User: arn:aws:iam::... is not authorized to perform ec2:RunInstances
原因: IAM 权限不足
解决:
  1. 添加 AmazonEC2FullAccess 权限
  2. 或添加自定义策略
  3. 稍等 1-2 分钟生效
```

### 问题 3: "InvalidClientTokenId"

```
错误: InvalidClientTokenId - The provided token is malformed or otherwise invalid
原因: Access Key 不正确或过期
解决:
  1. 检查 Access Key 拼写
  2. 创建新的访问密钥
  3. 删除过期的密钥
```

### 问题 4: "ExpiredTokenException"

```
错误: The provided token has expired
原因: 临时凭证过期
解决:
  1. 对于 IAM 用户：无需担心（不会过期）
  2. 对于临时凭证：使用 STS 刷新
```

---

## 📋 检查清单

在使用凭据前，确认：

- [ ] 创建了 AWS 账户
- [ ] 创建了 IAM 用户（推荐，不是根账户）
- [ ] 分配了 EC2 权限
- [ ] 生成了访问密钥
- [ ] 安全保管了 Secret Key
- [ ] 运行了 `aws configure`
- [ ] 验证了 `aws sts get-caller-identity`
- [ ] 验证了 `aws ec2 describe-instances`
- [ ] 更新了 `.gitignore`

---

## 🎯 常见用例

### 用例 1: 开发/测试（推荐）

```
创建 IAM 用户：
  名称: dev-raft
  权限: AmazonEC2FullAccess
  MFA: 可选

凭据使用期: 项目期间
凭据轮转: 每 90 天
```

### 用例 2: 生产环境

```
创建 IAM 用户：
  名称: raft-prod
  权限: 自定义最小权限
  MFA: 必需！

凭据使用期: 6 个月
凭据轮转: 每 30 天
```

### 用例 3: CI/CD 流程

```
创建 IAM 用户：
  名称: github-actions-raft
  权限: 仅允许必需的 EC2 操作
  MFA: N/A (仅用于自动化)

凭据: 存储在 GitHub Secrets
凭据轮转: 每 30 天
```

---

## 📚 参考资源

- AWS 文档: https://docs.aws.amazon.com/iam/
- 创建 IAM 用户: https://docs.aws.amazon.com/IAM/latest/UserGuide/id_users_create.html
- 访问密钥: https://docs.aws.amazon.com/IAM/latest/UserGuide/id_credentials_access-keys.html
- 最佳实践: https://docs.aws.amazon.com/IAM/latest/UserGuide/best-practices.html

---

## ✅ 总结

**获取 AWS 凭据的步骤**:

1. ✅ 创建 AWS 账户 (免费)
2. ✅ 创建 IAM 用户 (推荐)
3. ✅ 添加 EC2 权限
4. ✅ 生成访问密钥
5. ✅ 安全保管 Secret Key
6. ✅ 本地运行 `aws configure`
7. ✅ 验证 `aws sts get-caller-identity`

**总耗时**: 10-15 分钟

**安全等级**: ⭐⭐⭐⭐⭐

---

现在你可以运行:
```bash
./deploy/deploy.sh same-region
```

🚀 开始 AWS 分布式性能测试！

---

**创建时间**: 2026-04-19  
**版本**: 1.0  
**状态**: ✅ 完整就绪
