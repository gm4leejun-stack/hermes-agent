# my-skills

自定义 Hermes skills，跨设备同步通过 fork 仓库管理。

## 目录结构

```
my-skills/
├── productivity/
│   ├── smart-reminder/     # 智能提醒助手（语义识别+智能推理）
│   └── cronjob-reminder/   # 定时提醒任务创建规范
└── apple/
    └── apple-reminders/    # Apple Reminders via remindctl
```

## 同步到新机器

```bash
# 1. 拉取 fork 仓库
cd ~/.hermes/hermes-agent
git remote add fork https://github.com/gm4leejun-stack/hermes-agent.git
git fetch fork && git merge fork/main

# 2. 安装 skills
bash my-skills/install.sh
```
