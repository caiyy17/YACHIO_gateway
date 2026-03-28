# YACHIYO Gateway - 消息格式参考

## 架构

```
Bilibili 直播间
    ↓ (WebSocket, 通过 blivedm)
blivechat (端口 12450)
    ↓ (WebSocket /api/chat)
YACHIYO Gateway (端口 8080)
    ↓ (HTTP POST /send)
Unity ExternalMessageReceiver (端口 7890)
    ↓
ProcessingPipeline → WebSocketClientModule → YACHIYO Server
```

## Blivechat → Gateway (WebSocket)

所有消息格式: `{"cmd": <int>, "data": <array|dict>}`

### CMD 2: ADD_TEXT (弹幕)

data 为**数组**（为节省带宽）:

| 索引 | 字段 | 类型 | 说明 |
|------|------|------|------|
| 0 | avatarUrl | string | 用户头像 URL |
| 1 | timestamp | int | Unix 时间戳（秒） |
| 2 | authorName | string | 用户名 |
| 3 | authorType | int | 0=普通用户, 1=会员, 2=房管, 3=主播 |
| 4 | content | string | 弹幕文本 |
| 5 | privilegeType | int | 0=无, 1=总督, 2=提督, 3=舰长 |
| 6 | isGiftDanmaku | int | 0/1 是否礼物弹幕 |
| 7 | authorLevel | int | 用户等级 (1-60) |
| 8 | isNewbie | int | 0/1 是否新用户 |
| 9 | isMobileVerified | int | 0/1 是否手机验证 |
| 10 | medalLevel | int | 粉丝勋章等级 |
| 11 | id | string | 消息 UUID |
| 12 | translation | string | 自动翻译文本 |
| 13 | contentType | int | 0=文字, 1=表情 |
| 14 | contentTypeParams | array | 表情时为 [url] |
| 15 | textEmoticons | array | 已废弃 |
| 16 | uid | string | 用户 ID |
| 17 | medalName | string | 粉丝勋章名称 |
| 18 | isMirror | int | 0/1 是否镜像转发 |

### CMD 3: ADD_GIFT (礼物)

data 为**字典**:

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 消息 UUID |
| avatarUrl | string | 用户头像 URL |
| timestamp | int | Unix 时间戳 |
| authorName | string | 用户名 |
| totalCoin | int | 付费礼物金瓜子价值 |
| totalFreeCoin | int | 免费礼物银瓜子价值 |
| giftName | string | 礼物名称 |
| num | int | 礼物数量 |
| giftId | int | 礼物 ID |
| giftIconUrl | string | 礼物图标 URL |
| uid | string | 用户 ID |
| privilegeType | int | 大航海等级 |
| medalLevel | int | 粉丝勋章等级 |
| medalName | string | 粉丝勋章名称 |

### CMD 4: ADD_MEMBER (上舰)

data 为**字典**:

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | 消息 UUID |
| avatarUrl | string | 用户头像 URL |
| timestamp | int | Unix 时间戳 |
| authorName | string | 用户名 |
| privilegeType | int | 1=总督, 2=提督, 3=舰长 |
| num | int | 购买数量 |
| unit | string | 时间单位 |
| total_coin | int | 总花费金瓜子 |
| uid | string | 用户 ID |
| medalLevel | int | 粉丝勋章等级 |
| medalName | string | 粉丝勋章名称 |

### CMD 5: ADD_SUPER_CHAT (醒目留言)

data 为**字典**:

| 字段 | 类型 | 说明 |
|------|------|------|
| id | string | SC ID |
| avatarUrl | string | 用户头像 URL |
| timestamp | int | Unix 时间戳 |
| authorName | string | 用户名 |
| price | int | SC 价格（元） |
| content | string | SC 文本内容 |
| translation | string | 自动翻译文本 |
| uid | string | 用户 ID |
| privilegeType | int | 大航海等级 |
| medalLevel | int | 粉丝勋章等级 |
| medalName | string | 粉丝勋章名称 |

### CMD 0: HEARTBEAT (心跳)

每 10 秒发送一次，无需处理。

## Gateway → Unity (HTTP POST)

端点: `POST http://localhost:7890/send`

请求体为 **YYMessage**:

```json
{
  "signal": "",
  "content": "{\"text\": \"弹幕内容\", \"author\": \"用户名\", \"type\": \"danmaku\", \"destination\": 0}",
  "destination": 0
}
```

### YYMessage 字段

| 字段 | 类型 | 说明 |
|------|------|------|
| signal | string | 控制信号（通常为空） |
| content | string | **JSON 字符串**，包含实际载荷 |
| destination | int | Pipeline 模块索引。-2=下一个模块, -1=跳到输出 |

### content 载荷（content 内的 JSON 字符串）

弹幕:
```json
{
  "text": "弹幕文本",
  "author": "用户名",
  "type": "danmaku",
  "destination": 0
}
```

礼物:
```json
{
  "text": "辣条 x3",
  "author": "用户名",
  "type": "gift",
  "gift_name": "辣条",
  "num": 3,
  "total_coin": 1000,
  "destination": 0
}
```

醒目留言:
```json
{
  "text": "SC 文本",
  "author": "用户名",
  "type": "superchat",
  "price": 30,
  "destination": 0
}
```

注意: content 内部的 `destination` 用于**服务端**路由。
YYMessage 层级的 `destination` 用于 **Unity Pipeline** 模块路由。
