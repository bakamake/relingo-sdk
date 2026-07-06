# Relingo API 参考

本文档描述 `bob-relingo` 插件所使用的 Relingo 后端接口。基础域名为 `https://api.relingo.net`，所有接口均使用 `POST` 方法，载荷与响应均为 JSON。

## 通用约定

### 请求头

| 字段 | 是否必填 | 说明 |
| --- | --- | --- |
| `Content-Type` | 是 | `application/json` |
| `User-Agent` | 是 | 固定为 `Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/110.0.0.0 Safari/537.36` |
| `x-relingo-token` | 否 | 已登录后由 `/api/loginByCode` 颁发，调用除登录外的接口时必填 |
| `x-relingo-lang` | 否 | 用户当前界面语言，例如 `en`、`zh-CN` |

### 响应结构

```json
{
  "code": 0,
  "message": "ok",
  "data": {}
}
```

`code` 为 `0` 表示成功；非零值表示业务错误，`message` 给出错误描述。鉴权失败、Token 过期等错误同样以非零 `code` 返回。

### 变量约定

下文中出现的占位符含义如下，使用前请替换为实际值。

| 变量 | 含义 |
| --- | --- |
| `EMAIL` | 登录邮箱 |
| `CODE` | 邮件验证码 |
| `TOKEN` | 登录后获得的访问令牌 |
| `LANG` | 界面语言（用于 `x-relingo-lang`） |
| `TO_LANG` | 翻译目标语言 |
| `STRANGE_BOOK` | 生词本 ID |
| `MASTERED_BOOK` | 已掌握词本 ID |
| `BOOK_ID` | 自定义词本 ID |
| `WORD` | 待查询或更新的单词 |
| `TEXT` | 待翻译段落 |
| `PROVIDER_ID` | 段落翻译所使用的翻译引擎 ID |

## 接口列表

| 序号 | 端点 | 鉴权 | 用途 |
| --- | --- | --- | --- |
| 1 | `/api/authorization` | 否 | 发送邮件验证码 |
| 2 | `/api/loginByCode` | 否 | 验证码登录并获取 Token |
| 3 | `/api/getUserInfo` | 是 | 获取用户信息，刷新 Token |
| 4 | `/api/getUserConfig` | 是 | 获取用户配置、词本 ID |
| 5 | `/api/parseContent3` | 是 | 在个人词本中查询单词 |
| 6 | `/api/lookupDict2` | 是 | 在官方词库中查询单词 |
| 7 | `/api/submitVocabulary` | 是 | 标记单词为已掌握 |
| 8 | `/api/removeVocabularyWords` | 是 | 标记单词为遗忘（移回生词本） |
| 9 | `/api/translateParagraph` | 是 | 段落翻译 |

---

## 1. `/api/authorization`

发送登录验证码到指定邮箱。

- 方法：`POST`
- 鉴权：否

请求体：

```json
{ "email": "EMAIL" }
```

响应：

```json
{ "code": 0, "message": "ok" }
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `email` | string | 接收验证码的邮箱地址 |

---

## 2. `/api/loginByCode`

通过邮件验证码登录，返回访问 Token 与过期时间。

- 方法：`POST`
- 鉴权：否

请求体：

```json
{
  "email": "EMAIL",
  "code": "CODE"
}
```

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "name": "username",
    "token": "TOKEN",
    "expiredAt": 1893456000000
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `email` | string | 登录邮箱 |
| `code` | string | 邮件中收到的 6 位验证码 |
| `data.name` | string | 用户名 |
| `data.token` | string | 后续接口所需的访问令牌 |
| `data.expiredAt` | number | Token 过期时间（Unix 毫秒） |

---

## 3. `/api/getUserInfo`

获取当前用户信息，并刷新 Token 的有效期。

- 方法：`POST`
- 鉴权：是

请求体：

```json
{}
```

请求头额外字段：`x-relingo-token: TOKEN`、`x-relingo-lang: LANG`

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "token": "TOKEN"
  }
}
```

---

## 4. `/api/getUserConfig`

获取用户配置以及词本 ID。返回的 `config.langBooks` 中包含生词本、已掌握词本与用户自建词本。

- 方法：`POST`
- 鉴权：是

请求体：

```json
{}
```

请求头额外字段：`x-relingo-token: TOKEN`、`x-relingo-lang: LANG`

响应（节选）：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "config": {
      "langBooks": {
        "en": [
          { "_id": "STRANGE_BOOK",   "name": "strange",  "active": true  },
          { "_id": "MASTERED_BOOK",  "name": "mastered", "active": true  }
        ]
      }
    }
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `config.langBooks.<lang>[]._id` | string | 词本 ID |
| `config.langBooks.<lang>[].name` | string | 词本名称，`strange` 为生词本，`mastered` 为已掌握词本 |
| `config.langBooks.<lang>[].active` | boolean | 是否处于激活状态 |

`getUserConfig` 必须在登录后立即调用，以获取生词本、已掌握词本及用户自定义词本的 ID。

---

## 5. `/api/parseContent3`

在用户的个人词本（生词本 + 自定义词本）中查询指定单词。

- 方法：`POST`
- 鉴权：是

请求体：

```json
{
  "to": "TO_LANG",
  "words": ["WORD"],
  "vocabulary": ["STRANGE_BOOK", "BOOK_ID"],
  "definition": false
}
```

请求头额外字段：`x-relingo-token: TOKEN`、`x-relingo-lang: LANG`

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": {
    "words": [
      {
        "word": "WORD",
        "phonetic": "/wɜːrd/",
        "translations": [{ "translation": "释义" }],
        "examples": []
      }
    ]
  }
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `to` | string | 翻译目标语言 |
| `words` | string[] | 待查询的单词列表 |
| `vocabulary` | string[] | 要检索的词本 ID 列表，通常包含生词本与用户激活的自定义词本 |
| `definition` | boolean | 是否返回详细释义 |

若单词不在指定词本中，`data.words` 为空数组。

---

## 6. `/api/lookupDict2`

在 Relingo 官方词库中查询指定单词。

- 方法：`POST`
- 鉴权：是

请求体：

```json
{
  "to": "TO_LANG",
  "words": ["WORD"]
}
```

请求头额外字段：`x-relingo-token: TOKEN`、`x-relingo-lang: LANG`

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": [
    {
      "word": "WORD",
      "phonetic": "/wɜːrd/",
      "translations": [{ "translation": "释义" }],
      "examples": []
    }
  ]
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `to` | string | 翻译目标语言 |
| `words` | string[] | 待查询的单词列表 |

若单词不在官方词库中，`data` 为空数组。

---

## 7. `/api/submitVocabulary`

将单词标记为已掌握，写入已掌握词本。

- 方法：`POST`
- 鉴权：是

请求体：

```json
{
  "id": "MASTERED_BOOK",
  "type": "mastered",
  "words": ["WORD"]
}
```

请求头额外字段：`x-relingo-token: TOKEN`、`x-relingo-lang: LANG`

响应：

```json
{ "code": 0, "message": "ok" }
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 已掌握词本 ID |
| `type` | string | 固定为 `mastered` |
| `words` | string[] | 待标记为已掌握的单词列表 |

---

## 8. `/api/removeVocabularyWords`

将已掌握的单词标记为遗忘，从已掌握词本移回生词本。

- 方法：`POST`
- 鉴权：是

请求体：

```json
{
  "id": "MASTERED_BOOK",
  "type": "strange",
  "words": ["WORD"]
}
```

请求头额外字段：`x-relingo-token: TOKEN`、`x-relingo-lang: LANG`

响应：

```json
{ "code": 0, "message": "ok" }
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | string | 已掌握词本 ID（操作源词本） |
| `type` | string | 固定为 `strange`，表示移回生词本 |
| `words` | string[] | 待标记为遗忘的单词列表 |

---

## 9. `/api/translateParagraph`

调用指定翻译引擎翻译整段文本。

- 方法：`POST`
- 鉴权：是

请求体：

```json
{
  "text": "TEXT",
  "to": "TO_LANG",
  "providerId": "PROVIDER_ID"
}
```

请求头额外字段：`x-relingo-token: TOKEN`、`x-relingo-lang: LANG`

响应：

```json
{
  "code": 0,
  "message": "ok",
  "data": "翻译结果"
}
```

字段说明：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `text` | string | 待翻译文本 |
| `to` | string | 翻译目标语言 |
| `providerId` | string | 翻译引擎标识，由前端配置决定 |

服务器直接以字符串形式返回翻译结果，调用方需按换行符拆分段落。

---

## 错误码

| `code` | 含义 | 建议处理 |
| --- | --- | --- |
| `0` | 成功 | — |
| 非零 | 业务错误 | 读取 `message`，提示用户 |
| Token 失效 | 鉴权失败 | 重新调用 `/api/loginByCode` |
| 网络异常 | 请求未到达 | 检查网络与代理设置 |

## 端到端流程

```text
1. 调用 /api/authorization   发送验证码到邮箱
2. 调用 /api/loginByCode     使用验证码换取 TOKEN
3. 调用 /api/getUserConfig   取得 STRANGE_BOOK / MASTERED_BOOK / 自定义词本 ID
4. 调用 /api/parseContent3   在个人词本中查词
   若未命中，调用 /api/lookupDict2 在官方词库中查词
5. 根据用户操作：
   - 标记掌握：/api/submitVocabulary
   - 标记遗忘：/api/removeVocabularyWords
6. 段落翻译：/api/translateParagraph
```

## curl 示例

```bash
# 1. 发送验证码
curl -X POST https://api.relingo.net/api/authorization \
  -H "Content-Type: application/json" \
  -H "User-Agent: Mozilla/5.0" \
  -d '{"email":"EMAIL"}'

# 2. 验证码登录
curl -X POST https://api.relingo.net/api/loginByCode \
  -H "Content-Type: application/json" \
  -H "User-Agent: Mozilla/5.0" \
  -d '{"email":"EMAIL","code":"CODE"}'

# 3. 获取用户配置（取得词本 ID）
curl -X POST https://api.relingo.net/api/getUserConfig \
  -H "Content-Type: application/json" \
  -H "x-relingo-token: TOKEN" \
  -H "x-relingo-lang: LANG" \
  -d '{}'

# 4. 查询个人词本
curl -X POST https://api.relingo.net/api/parseContent3 \
  -H "Content-Type: application/json" \
  -H "x-relingo-token: TOKEN" \
  -H "x-relingo-lang: LANG" \
  -d '{"to":"TO_LANG","words":["WORD"],"vocabulary":["STRANGE_BOOK"],"definition":false}'

# 5. 查询官方词库
curl -X POST https://api.relingo.net/api/lookupDict2 \
  -H "Content-Type: application/json" \
  -H "x-relingo-token: TOKEN" \
  -H "x-relingo-lang: LANG" \
  -d '{"to":"TO_LANG","words":["WORD"]}'

# 6. 标记掌握
curl -X POST https://api.relingo.net/api/submitVocabulary \
  -H "Content-Type: application/json" \
  -H "x-relingo-token: TOKEN" \
  -H "x-relingo-lang: LANG" \
  -d '{"id":"MASTERED_BOOK","type":"mastered","words":["WORD"]}'

# 7. 标记遗忘
curl -X POST https://api.relingo.net/api/removeVocabularyWords \
  -H "Content-Type: application/json" \
  -H "x-relingo-token: TOKEN" \
  -H "x-relingo-lang: LANG" \
  -d '{"id":"MASTERED_BOOK","type":"strange","words":["WORD"]}'

# 8. 段落翻译
curl -X POST https://api.relingo.net/api/translateParagraph \
  -H "Content-Type: application/json" \
  -H "x-relingo-token: TOKEN" \
  -H "x-relingo-lang: LANG" \
  -d '{"text":"TEXT","to":"TO_LANG","providerId":"PROVIDER_ID"}'
```
