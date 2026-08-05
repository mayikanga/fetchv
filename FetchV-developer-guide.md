# FetchV 视频解析下载工具开发者指南

> 面向 FetchV.html 和配套 server.py 的开发、运行与部署说明。

## 一句话概述

FetchV 是一个前后端分离的视频解析下载工具：前端提供链接粘贴、视频信息展示、清晰度选择和下载交互，后端使用 FastAPI 调用 yt-dlp 解析媒体信息并下载视频，支持通过 Docker 部署到 Render。

## 项目边界

项目由两部分组成：

- 前端：FetchV.html，负责页面展示、用户交互和 API 请求；
- 后端：server.py，负责 URL 校验、限流、yt-dlp 调用、下载文件管理和临时文件清理。

同目录中的 terms.html 和 privacy.html 是静态法律说明页面，assets/ 保存前端样式，downloads/ 用于本地开发时保存临时下载文件。

## 整体架构

~~~mermaid
flowchart TD
  A["FetchV.html"] --> B["粘贴视频链接"]
  B --> C["POST /api/parse"]
  C --> D["FastAPI + yt-dlp"]
  D --> E["标题、封面、作者、时长、格式列表"]
  E --> A
  A --> F["选择下载格式"]
  F --> G["POST /api/download"]
  G --> H["FastAPI + yt-dlp 下载"]
  H --> I["临时文件目录"]
  I --> J["GET /api/file/{filename}"]
  J --> K["浏览器下载视频"]
~~~

## 目录结构

~~~
项目目录/
├─ FetchV.html               前端单页
├─ server.py                 FastAPI 后端
├─ requirements.txt          Python 依赖
├─ Dockerfile                Docker 构建与启动配置
├─ render.yaml               Render 部署配置
├─ terms.html                服务条款
├─ privacy.html              隐私政策
├─ assets/                   前端静态资源
├─ downloads/                本地临时下载目录
└─ node_modules/             Playwright 等检查依赖
~~~

## 前端模块

页面包含顶部导航、链接输入、解析结果、功能介绍、使用说明、支持平台、FAQ、服务条款和隐私政策等区域。

关键元素：

| 元素 | 作用 |
| --- | --- |
| #video-form | 提交解析请求 |
| #video-url-input | 输入视频链接 |
| #paste-btn | 读取剪贴板 |
| #parse-result | 渲染解析结果和错误 |
| .download-format-btn | 触发指定格式下载 |
| .faq-toggle | 展开或收起 FAQ |
| #mobile-menu-button | 移动端菜单 |
| #lang-menu-button | 语言菜单 |

页面脚本通过 escapeHtml() 转义标题、作者、错误信息和格式标签，避免第三方返回内容直接作为 HTML 插入页面。

## 后端模块

server.py 使用 FastAPI 创建 HTTP 服务，并通过 subprocess 调用 yt-dlp。

主要职责：

- 校验请求 URL；
- 规范化部分抖音分享链接；
- 调用 yt-dlp 获取媒体 JSON；
- 过滤无视频编码或带水印标记的格式；
- 按清晰度和码率整理可下载格式；
- 执行视频下载和音视频合并；
- 保存并返回临时文件；
- 清理过期文件；
- 执行按 IP 的解析和下载限流。

## API 接口

### POST /api/parse

只解析媒体信息，不下载视频。

处理步骤：

1. 检查客户端 IP 的解析频率；
2. 清理过期临时文件；
3. 执行 yt-dlp --dump-single-json --skip-download；
4. 检查视频时长；
5. 过滤视频格式；
6. 按清晰度、直链能力、文件大小和码率排序；
7. 按高度和扩展名去重；
8. 返回最多 6 个格式。

请求：

~~~json
{
  "url": "https://example.com/video"
}
~~~

响应字段：

~~~json
{
  "title": "示例视频",
  "thumbnail": "https://example.com/cover.jpg",
  "duration": 42,
  "uploader": "作者名",
  "formats": [
    {
      "id": "137",
      "height": 1080,
      "width": 1920,
      "ext": "mp4",
      "filesize": 12345678,
      "watermarked": false,
      "direct": true,
      "bitrate": 2000,
      "quality": "1080p"
    }
  ]
}
~~~

### POST /api/download

根据用户选择的 format_id 下载视频。

请求：

~~~json
{
  "url": "https://example.com/video",
  "format_id": "137"
}
~~~

处理步骤：

1. 再次解析媒体信息，避免客户端伪造格式；
2. 检查视频时长和目标格式大小；
3. 使用 yt-dlp 下载，并以 MP4 为目标合并音视频；
4. 生成随机任务 ID，避免文件名冲突；
5. 返回临时文件 URL。

响应：

~~~json
{
  "url": "/api/file/8f2c-example.mp4"
}
~~~

### GET /api/file/{filename}

返回临时下载文件。实现会使用文件名部分去除路径，避免通过路径参数访问下载目录之外的文件。

## 运行时配置

| 环境变量 | 默认值 | 作用 |
| --- | --- | --- |
| FETCHV_DOWNLOAD_DIR | 本地 downloads/ | 下载文件保存目录 |
| FETCHV_COOKIE_FILE | 空 | Netscape Cookie 文件路径 |
| FETCHV_COOKIES_B64 | 空 | Base64 Cookie 内容 |
| FETCHV_DOWNLOAD_TTL_SECONDS | 1800 | 临时文件保留时间 |
| RENDER | 空 | 设置后默认使用 /tmp/fetchv-downloads |
| PORT | 10000 | Uvicorn 监听端口 |

Cookie 只在服务端使用，不通过接口返回给客户端。不要把 Cookie 文件或 FETCHV_COOKIES_B64 提交到 Git。

## 运行限制

当前后端默认限制：

- 每个 IP 每小时最多解析 5 次；
- 每个 IP 每小时最多下载 2 次；
- 视频时长最多 15 分钟；
- 目标文件最大 300 MB；
- 解析命令超时 90 秒；
- 下载命令超时 600 秒；
- 临时文件默认 30 分钟后清理。

限流数据保存在进程内存中，服务重启后会清空；多实例部署时不能视为全局限流方案。

## 快速开始

### 本地运行

要求：

- Python 3.12 或兼容版本；
- yt-dlp 可执行文件在 PATH 中；
- ffmpeg 已安装并可执行；
- 已安装 requirements.txt 中的依赖。

PowerShell：

~~~powershell
Set-Location '<project-root>'
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m uvicorn server:app --host 127.0.0.1 --port 10000
~~~

打开 http://127.0.0.1:10000/。

### Docker 运行

~~~powershell
docker build -t fetchv .
docker run --rm -p 10000:10000 fetchv
~~~

Dockerfile 会安装 ffmpeg，安装 Python 依赖，并用 Uvicorn 启动 FastAPI。镜像中还必须能够找到 yt-dlp。

### Render 部署

render.yaml 配置了 Docker Web Service：

- 服务名为 fetchv；
- 健康检查路径为 /；
- 端口由 PORT 环境变量提供；
- Cookie Secret 使用 FETCHV_COOKIES_B64；
- 容器临时下载目录为 /tmp/fetchv-downloads。

部署前应确认平台允许执行 yt-dlp、网络出口可访问目标平台，并理解免费实例的休眠、临时磁盘和请求超时限制。

## 异常处理

| 场景 | HTTP 状态 | 说明 |
| --- | --- | --- |
| URL 不合法 | 422 | Pydantic 校验失败 |
| 未找到 yt-dlp | 500 | 运行环境缺少依赖 |
| 解析失败 | 422 | 返回 yt-dlp 错误摘要 |
| 超过频率限制 | 429 | 等待限流窗口结束 |
| 视频超过 15 分钟 | 422 | 拒绝处理 |
| 文件超过 300 MB | 422 | 拒绝下载 |
| 下载完成但找不到文件 | 500 | 服务端文件处理异常 |
| 临时文件不存在 | 404 | 文件已过期或地址失效 |

## 安全与合规注意事项

- 不要提交 Cookie 文件、Base64 Cookie 或其他凭证；
- 不要把 Cookie 内容写入日志；
- 下载目录必须是独立临时目录，并设置自动清理；
- 生产环境应使用 Redis 或其他共享存储实现全局限流；
- 应根据目标平台条款、版权和当地法律使用解析下载功能；
- 页面中的“无水印”“完全免费”等文案必须与实际服务能力和部署成本一致；
- 临时下载 URL 不是永久存储链接。

## 测试建议

基础语法检查：

~~~powershell
python -m py_compile server.py
~~~

接口手工检查：

~~~powershell
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:10000/api/parse' -ContentType 'application/json' -Body '{"url":"https://example.com/video"}'
~~~

浏览器验证重点：

- 粘贴按钮能否读取剪贴板；
- 空链接、非法链接和后端错误是否显示可读信息；
- 标题、作者、封面、时长和格式是否正确渲染；
- FAQ、语言菜单和移动端导航是否正常；
- 下载按钮是否提交当前 URL 和 format_id；
- 文件过期后是否正确处理 404。

## 版本与维护信息

- 前端入口：FetchV.html；
- 后端入口：server.py；
- API：/api/parse、/api/download、/api/file/{filename}；
- 容器入口：Uvicorn + FastAPI；
- 项目定位：本地可运行、可部署的视频解析下载演示工具；
- 下载结果：临时文件，不是持久化媒体存储服务。
