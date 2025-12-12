# 配置文件说明

这个目录包含项目的所有配置文件。

## 文件说明

- `global_settings.yaml` - 全局默认配置，适用于所有试卷
- `exam_*.yaml` - 具体试卷的配置文件，会覆盖全局配置

## 如何创建新试卷配置

1. 复制 `exam_gd_2025.yaml` 作为模板
2. 修改 `exam_info` 部分：
   - `id`: 试卷唯一标识（英文）
   - `name`: 试卷全称（中文）
   - `description`: 简要描述
3. 如需自定义参数，添加相应配置项覆盖全局设置

## 配置继承规则

```
全局配置 (global_settings.yaml)
    ↓ 被覆盖
具体试卷配置 (exam_*.yaml)
    ↓ 被覆盖
命令行参数
```

## 示例

```bash
# 使用默认配置处理试卷
python manage.py process --config config/exam_gd_2025.yaml input.pdf

# 临时覆盖某个配置
python manage.py process --config config/exam_gd_2025.yaml --skip-existing false input.pdf
```
