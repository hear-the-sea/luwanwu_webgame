# 游戏资源图片目录

此目录用于存放游戏中的物品和门客图片资源。

## 目录结构

```
data/images/
├── items/          # 物品图片
│   ├── wood_pack.png
│   ├── magnifier.png
│   └── ...
├── guests/         # 门客头像
│   ├── zhao_yun.png
│   ├── huang_yueying.png
│   └── ...
└── README.md       # 本说明文件
```

## 使用方法

### 1. 准备图片文件

将图片文件放入对应的目录：
- **物品图片**：放在 `items/` 目录下
- **门客头像**：放在 `guests/` 目录下

**推荐规格：**
- 物品图片：96x96 像素或更大（正方形）
- 门客头像：128x128 像素或更大（正方形）
- 格式：PNG（推荐）、JPG、GIF
- 文件大小：单个文件不超过 2MB

### 2. 在 YAML 配置文件中引用

#### 物品图片配置示例

编辑 `data/item_templates.yaml`：

```yaml
items:
  - key: starter_wood_pack
    name: 木材补给
    description: 提供基础木材补给。
    effect_type: resource_pack
    effect_payload:
      wood: 1000
    image: wood_pack.png  # 图片文件名（相对于 data/images/items/）
```

#### 门客头像配置示例

编辑 `data/guest_templates.yaml`：

```yaml
heroes:
  green:
    - key: hero_zhao_yun
      name: 赵云
      archetype: military
      flavor: 常胜将军，悍勇善战。
      default_gender: male
      default_morality: 75
      avatar: zhao_yun.png  # 头像文件名（相对于 data/images/guests/）
```

### 3. 导入数据

运行管理命令导入配置（图片会自动加载）：

```bash
# 导入物品模板（包含图片）
python manage.py load_item_templates

# 导入门客模板（包含头像）
python manage.py load_guest_templates
```

## 工作原理

1. **配置阶段**：在 YAML 文件中指定图片文件名
2. **导入阶段**：运行管理命令时，脚本会：
   - 从 `data/images/{items|guests}/` 读取原始图片
   - 将图片复制到 `media/{items|guests}/` 目录
   - 在数据库中记录图片路径
3. **显示阶段**：前端模板自动显示图片

## 注意事项

1. **文件命名**：
   - 使用英文字母、数字、下划线和连字符
   - 避免使用中文和特殊字符
   - 示例：`zhao_yun.png`、`wood-pack.png`

2. **图片优化**：
   - 建议压缩图片以减小文件大小
   - 使用在线工具如 TinyPNG 进行压缩

3. **版权合规**：
   - 确保使用的图片有合法授权
   - 避免侵犯他人版权

4. **备份**：
   - 定期备份 `data/images/` 目录
   - 版本控制时建议将原始图片纳入 Git 管理

## 示例工作流

```bash
# 1. 准备图片
cp ~/Downloads/zhao_yun.png data/images/guests/

# 2. 编辑 YAML 配置
vim data/guest_templates.yaml
# 添加 avatar: zhao_yun.png

# 3. 导入配置
python manage.py load_guest_templates

# 4. 启动服务器查看效果
python manage.py runserver
```

## 故障排查

### 图片没有显示？

1. 检查图片文件是否存在于正确的目录
2. 检查 YAML 配置中的文件名是否正确（区分大小写）
3. 检查导入命令的输出，查看是否有错误信息
4. 确认 Django 的 `MEDIA_URL` 和 `MEDIA_ROOT` 配置正确

### 导入时提示 "Image not found"？

- 确认图片文件路径：`data/images/{items|guests}/文件名.png`
- 检查文件名拼写是否正确
- 确认文件扩展名是否正确（.png、.jpg 等）

### 图片显示但样式不对？

- 检查浏览器控制台是否有 CSS 错误
- 清除浏览器缓存
- 检查图片原始尺寸是否符合推荐规格
