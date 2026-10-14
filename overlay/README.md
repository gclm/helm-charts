# overlay/ — 转换产物的人工修补层

对 `generated/` 中 chart 的定制放在这里（人工维护，可 PR 评审）。
CI 在每次生成后按本目录对产物应用补丁，人工改动永不丢失。

形式（Phase 4 落地时启用）：

overlay/
└── <app-name>/
    ├── values-patch.yaml    # 值覆盖（镜像 tag、资源、探针等）
    └── patches/*.yaml       # strategic-merge / JSON patch（结构性修改）

阻塞项清单（转换器报告的 42 个）在此逐个消化后移除。
