# my-skills

自定义 Hermes Agent skills，通过 fork 仓库跨设备同步。

**仓库地址：** https://github.com/gm4leejun-stack/hermes-agent（`my-skills/` 目录）

---

## 包含的 Skills

| Skill | 路径 | 功能 |
|-------|------|------|
| smart-reminder | `productivity/smart-reminder` | 智能提醒助手，语义识别自然语言，自动推理最佳提醒时机 |
| cronjob-reminder | `productivity/cronjob-reminder` | 定时提醒任务创建规范，避免 prompt 误导子代理 |
| apple-reminders | `apple/apple-reminders` | 通过 `remindctl` 管理 Apple Reminders，支持 iCloud 同步 |

---

## 安装（新机器）

### 前提条件

- 已安装 Hermes Agent（`~/.hermes/hermes-agent/` 存在）
- 已配置 git

### 步骤

```bash
# 1. 进入 hermes-agent 目录
cd ~/.hermes/hermes-agent

# 2. 添加 fork remote
git remote add fork https://github.com/gm4leejun-stack/hermes-agent.git

# 3. 拉取代码
git fetch fork
git merge fork/main

# 4. 安装 skills（创建软链接到 ~/.hermes/skills/）
bash my-skills/install.sh

# 5. 重启 gateway 使 skills 生效
hermes gateway restart
```

安装完成后，skills 以软链接方式挂载，后续 `git pull` 即可同步更新，无需重新安装。

---

## 更新已安装的机器

```bash
cd ~/.hermes/hermes-agent
git fetch fork
git merge fork/main
# 软链接已生效，无需重新运行 install.sh
hermes gateway restart
```

---

## 开发工作流（在本机修改 skill）

```bash
# 1. 修改 skill 文件
vim ~/.hermes/hermes-agent/my-skills/productivity/smart-reminder/SKILL.md

# 2. 提交并推送
cd ~/.hermes/hermes-agent
git add my-skills/
git commit -m "feat(skills): 更新 smart-reminder 规则"
git push fork main

# 3. 其他机器同步
git fetch fork && git merge fork/main
```

---

## 新增 Skill

```bash
# 1. 创建目录和 SKILL.md
mkdir -p ~/.hermes/hermes-agent/my-skills/<category>/<skill-name>
vim ~/.hermes/hermes-agent/my-skills/<category>/<skill-name>/SKILL.md

# 2. 在 install.sh 中添加一行
# install_skill "$SCRIPT_DIR/<category>/<skill-name>" "$SKILLS_DIR/<category>/<skill-name>"

# 3. 在本机手动链接（无需重新运行 install.sh）
ln -s ~/.hermes/hermes-agent/my-skills/<category>/<skill-name> ~/.hermes/skills/<category>/<skill-name>

# 4. 提交推送
git add my-skills/
git commit -m "feat(skills): 新增 <skill-name>"
git push fork main
```

---

## 一键同步到另一台机器（通过 Tailscale）

```bash
ssh lijunsheng@lijunshengdemac-mini.tail4a18de.ts.net \
  'cd ~/.hermes/hermes-agent && git fetch fork && git merge fork/main && hermes gateway restart'
```
