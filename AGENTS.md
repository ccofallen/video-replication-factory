# 视频复刻工厂发布边界

本仓库维护`video-replication-factory`（视频复刻工厂），版本v1；唯一发布目标为`https://github.com/ccofallen/video-replication-factory`，默认分支main。用户已明确要求改名、重置版本并发布到自己的GitHub。来源记录为`https://github.com/T8mars/video-replacement-skill-factory-T8`，在README、SKILL和ORIGIN中保留直接署名链接。

维护先读SKILL、meta、features、manifest、publish-policy及相关源码/测试。按manifest和明确白名单同步；只暂存核对过的具体文件。提交前运行`python tools/verify_publish.py --staged`，推送前扫描全部待发送提交并核对origin。保留远端现有提交和用户修改，不使用force push。

任何目录和大小写的ROADMAP.MD、凭据、私有账本/配置、任务记录、媒体与生成专属技能均不得进入仓库；不依赖.gitignore代替已跟踪文件和历史检查。原项目作者/资源链接保留在README，来源说明保留在ORIGIN。

每次源码变更更新manifest文件哈希和相应文档；安装或离线验证不启动生产生成。运行时沿用兼容的共享私有账本命名空间，避免改名产生第二份任务调度账本。用户新指令优先。
