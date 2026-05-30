<div align="center">
  <img src="docs/logo.png" alt="OmniVoice Logo" width="120" />
  <h1>OmniVoice Studio</h1>
  <h3>开源版 ElevenLabs 替代品</h3>
  <p>实时听写、零样本语音克隆、电影级视频配音——全部在桌面端完成。<br/>开源、无需 API 密钥、完全本地运行。<b>支持 646 种语言。</b></p>

  <p>
    <a href="https://github.com/debpalash/OmniVoice-Studio/stargazers"><img src="https://img.shields.io/github/stars/debpalash/OmniVoice-Studio?style=flat-square&color=f59e0b" alt="Star" /></a>
    <a href="https://github.com/debpalash/OmniVoice-Studio/releases/latest"><img src="https://img.shields.io/github/v/release/debpalash/OmniVoice-Studio?style=flat-square&color=10b981" alt="版本" /></a>
    <a href="LICENSE"><img src="https://img.shields.io/badge/license-FSL--1.1--ALv2-blue?style=flat-square" alt="许可证" /></a>
    <a href="https://github.com/debpalash/OmniVoice-Studio/issues"><img src="https://img.shields.io/github/issues/debpalash/OmniVoice-Studio?style=flat-square&color=ef4444" alt="Issues" /></a>
    <a href="https://discord.gg/bzQavDfVV9"><img src="https://img.shields.io/badge/Discord-加入社区-5865F2?style=flat-square&logo=discord&logoColor=white" alt="Discord" /></a>
  </p>

  <p>
    <a href="#快速开始">快速开始</a> ·
    <a href="#功能">功能</a> ·
    <a href="#为什么选择-omnivoice-studio">为什么选择 OmniVoice Studio？</a> ·
    <a href="#tts-引擎">TTS 引擎</a> ·
    <a href="#参与贡献">参与贡献</a> ·
    <a href="https://discord.gg/bzQavDfVV9">Discord</a> ·
    <a href="README.md"><strong>English</strong></a>
  </p>

  <p>
    <a href="https://github.com/debpalash/OmniVoice-Studio/releases/download/v0.2.7/OmniVoice.Studio_0.2.7_aarch64.dmg"><img src="https://img.shields.io/badge/macOS-DMG_(Apple_Silicon)-000?style=for-the-badge&logo=apple&logoColor=white" alt="下载 macOS DMG" /></a>
    <a href="https://github.com/debpalash/OmniVoice-Studio/releases/download/v0.2.7/OmniVoice.Studio_0.2.7_x64_en-US.msi"><img src="https://img.shields.io/badge/Windows-MSI_(x64)-0078D4?style=for-the-badge&logo=windows&logoColor=white" alt="下载 Windows MSI" /></a>
    <a href="https://github.com/debpalash/OmniVoice-Studio/releases/download/v0.2.7/OmniVoice.Studio_0.2.7_amd64.AppImage"><img src="https://img.shields.io/badge/Linux-AppImage_(x64)-FCC624?style=for-the-badge&logo=linux&logoColor=black" alt="下载 Linux AppImage" /></a>
    <a href="https://github.com/debpalash/OmniVoice-Studio/releases/download/v0.2.7/OmniVoice.Studio_0.2.7_amd64.deb"><img src="https://img.shields.io/badge/Debian-.deb-A81D33?style=for-the-badge&logo=debian&logoColor=white" alt="下载 Debian .deb" /></a>
  </p>
</div>

<br/>

<div align="center">
  <img src=".github/assets/social-preview.png" alt="OmniVoice Studio — 开源版 ElevenLabs 替代品" width="100%"/>
</div>

> [!WARNING]
> **OmniVoice Studio 正处于活跃 Beta 阶段。** 各版本之间可能出现不兼容。如需最新功能和修复，建议克隆仓库并从源码运行，而非使用预构建安装程序。欢迎提交 Bug 报告和 PR——[提交 Issue](https://github.com/debpalash/OmniVoice-Studio/issues) 或 [加入 Discord](https://discord.gg/bzQavDfVV9)。

<br/>

## 功能

<table>
<tr>
  <td align="center" width="33%">
    <h3>🎙️ 语音克隆</h3>
    <p>3 秒音频 → 复制任何声音。<br/><b>646 种语言</b>，零样本。</p>
  </td>
  <td align="center" width="33%">
    <h3>🎨 声音设计</h3>
    <p>性别、年龄、口音、音高、语速、<br/>情感、方言——<b>随心调节</b>。</p>
  </td>
  <td align="center" width="33%">
    <h3>🎬 视频配音</h3>
    <p>YouTube 链接或文件 → 转录 →<br/>翻译 → 重新配音 → <b>MP4</b>。</p>
  </td>
</tr>
<tr>
  <td align="center" valign="top">
    <h3>⌨️ 听写工具</h3>
    <p>从<b>任何应用</b>中按 <code>⌘+⇧+Space</code>。<br/>转录、自动粘贴、无痕消失。</p>
  </td>
  <td align="center" valign="top">
    <h3>🔊 人声分离</h3>
    <p>基于 Demucs。从背景音乐中<br/>分离人声，<b>保留背景音</b>。</p>
  </td>
  <td align="center" valign="top">
    <h3>👥 说话人分离</h3>
    <p>Pyannote + WhisperX。<br/><b>自动识别</b>谁说了什么。</p>
  </td>
</tr>
<tr>
  <td align="center" valign="top">
    <h3>📦 批量队列</h3>
    <p>一次拖入 <b>50 个视频</b>，然后离开。<br/>每个任务有进度条。</p>
  </td>
  <td align="center" valign="top">
    <h3>🤖 MCP 服务器</h3>
    <p>从 <b>Claude</b>、Cursor 或<br/>任何 MCP 客户端使用 OmniVoice。</p>
  </td>
  <td align="center" valign="top">
    <h3>🛡️ AI 水印</h3>
    <p>AudioSeal（Meta）。<b>不可见</b>，<br/>能抵抗压缩。</p>
  </td>
</tr>
<tr>
  <td align="center" valign="top">
    <h3>🔐 完全本地</h3>
    <p>无需密钥、云端、账号。<br/><b>仅限你的设备</b>。</p>
  </td>
  <td align="center" valign="top">
    <h3>⚡ GPU 自动检测</h3>
    <p>CUDA · MPS · ROCm · CPU。<br/>显存 ≤8 GB？<b>自动卸载</b>。</p>
  </td>
  <td align="center" valign="top">
    <h3>🧩 可扩展</h3>
    <p>继承 <code>TTSBackend</code>，<br/>约 <b>50 行代码</b>添加任意引擎。</p>
  </td>
</tr>
</table>

---

## 快速开始

选择你的方式——从零安装到完整开发者环境：

<table>
<tr>
<td width="33%" align="center">
<h3>🖥️ 桌面应用</h3>
<sub><b>最简单</b> · 约 2 分钟 · 无需依赖</sub>
<br/><br/>
<a href="https://github.com/debpalash/OmniVoice-Studio/releases/latest"><img src="https://img.shields.io/badge/下载-安装包-10b981?style=for-the-badge&logo=github&logoColor=white" alt="下载"/></a>
<br/><br/>
<sub>macOS DMG · Windows MSI · Linux AppImage/deb<br/>首次启动自动引导 Python + 模型下载。</sub>
</td>
<td width="33%" align="center">
<h3>🐳 Docker</h3>
<sub><b>一条命令</b> · 约 3 分钟 · 需 Docker</sub>
<br/><br/>
<code>docker pull ghcr.io/debpalash/omnivoice-studio</code>
<br/><br/>
<sub>来自 GHCR 的预构建镜像。<br/>支持 CPU + NVIDIA GPU。</sub>
</td>
<td width="33%" align="center">
<h3>⚡ 源码运行</h3>
<sub><b>完全控制</b> · 约 5 分钟 · 需 Bun + Python</sub>
<br/><br/>
<code>git clone → bun install → bun run dev</code>
<br/><br/>
<sub>热重载，完整代码访问。<br/>贡献者的最佳选择。</sub>
</td>
</tr>
</table>

---

### 🖥️ 方式 1 — 桌面应用

预构建安装程序（约 6–8 MB）在 [**Releases**](https://github.com/debpalash/OmniVoice-Studio/releases/latest) 页面。下载、安装、启动。应用会自动引导 Python 环境并下载模型——开屏画面会显示进度。

<details>
<summary><b>macOS — "应用已损坏，无法打开"</b></summary>
<br/>

macOS 会隔离从 App Store 外下载的应用。拖入 `/Applications` 后执行：

```bash
xattr -cr /Applications/OmniVoice\ Studio.app
```

之后正常打开即可。一次性修复。
</details>

<details>
<summary><b>Windows — 首次启动需 5–10 分钟</b></summary>
<br/>

应用首次运行时会引导 Python 虚拟环境、安装依赖并下载 ffmpeg。开屏画面会显示每一步的进度。后续启动仅需数秒。
</details>

<details>
<summary><b>Linux — AppImage 需要 FUSE</b></summary>
<br/>

如果没有 FUSE，可使用 `.deb` 包或解压运行：

```bash
chmod +x OmniVoice.Studio_*.AppImage
./OmniVoice.Studio_*.AppImage --appimage-extract-and-run
```
</details>

<details>
<summary><b>Linux — Fedora 44 / Ubuntu 24.04 白屏</b></summary>
<br/>

部分新发行版自带的 WebKit/GTK 版本存在合成问题。尝试：

```bash
WEBKIT_DISABLE_COMPOSITING_MODE=1 ./OmniVoice.Studio_*.AppImage
```

如果仍然无效，请改用 `.deb` 包或从源码运行。
</details>

<details>
<summary><b>防火墙内 / 俄罗斯地区安装失败</b></summary>
<br/>

桌面应用首次启动时会从 GitHub 下载 Python。如果你的网络屏蔽了 GitHub：

1. 从 [python.org](https://python.org/downloads/) 手动安装 Python 3.11
2. 启动前设置 `UV_PYTHON_PREFERENCE=system`，或从源码运行 `bun run dev`
3. PyPI 镜像：设置 `UV_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/`
</details>

---

### 🐳 方式 2 — Docker

从 **GitHub Container Registry** 拉取预构建镜像：

```bash
docker pull ghcr.io/debpalash/omnivoice-studio:latest
```

**运行：**

```bash
# CPU 模式
docker run -d --name omnivoice \
  -p 127.0.0.1:3900:3900 \
  -v omnivoice-data:/app/omnivoice_data \
  ghcr.io/debpalash/omnivoice-studio:latest

# NVIDIA GPU 模式
docker run -d --name omnivoice --gpus all \
  -p 127.0.0.1:3900:3900 \
  -v omnivoice-data:/app/omnivoice_data \
  ghcr.io/debpalash/omnivoice-studio:latest
```

**或使用 Docker Compose：**

```bash
# CPU
docker compose -f deploy/docker-compose.yml up -d

# GPU
docker compose -f deploy/docker-compose.yml --profile gpu up -d
```

健康检查通过后打开 [localhost:3900](http://localhost:3900)。首次运行下载约 4 GB 模型权重——进度在 `docker compose logs -f` 中查看。

<details>
<summary><b>从源码构建而非拉取</b></summary>
<br/>

```bash
docker compose -f deploy/docker-compose.yml up --build -d
```
</details>

> **网络访问：** 容器仅绑定 `127.0.0.1`。如需暴露到局域网，将端口映射改为 `"0.0.0.0:3900:3900"`。OmniVoice 没有内置认证——请将其置于反向代理之后并添加认证（Caddy `basic_auth`、nginx + htpasswd、Tailscale 等）。

---

### ⚡ 方式 3 — 源码运行

```bash
git clone https://github.com/debpalash/OmniVoice-Studio.git && cd OmniVoice-Studio
bun install && bun run dev
```

打开 [localhost:3901](http://localhost:3901) 开始克隆声音。前端和后端均启用热重载。

```bash
bun run desktop    # 从源码构建原生桌面应用
```

| 服务 | 地址 | 技术栈 |
|---------|-----|-------|
| **后端** | `localhost:3900` | FastAPI · 97 个端点 · WhisperX · Demucs · OmniVoice |
| **前端** | `localhost:3901` | React · Vite · 波形时间线 · 毛玻璃 UI |
| **API 文档** | [`localhost:3900/docs`](http://localhost:3900/docs) | Scalar — 交互式 API 参考 |

> [!NOTE]
> 首次运行下载模型权重（约 2.4 GB）。无需账号。如需加速下载，可选在环境中设置 `HF_TOKEN=hf_...`（[在此获取免费 Token](https://huggingface.co/settings/tokens)）。
>
> **遇到问题？** 加入我们的 [Discord](https://discord.gg/bzQavDfVV9) 获取安装帮助和故障排查。

---

## 截图

<table>
  <tr>
    <td align="center" width="50%">
      <img src="docs/screenshot-clone.png" alt="语音克隆" width="100%"/>
      <br/><b>语音克隆</b><br/>
      <sub>拖入 3 秒音频 → 复制任何声音。646 种语言，零样本。</sub>
    </td>
    <td align="center" width="50%">
      <img src="docs/screenshot-design.png" alt="声音设计" width="100%"/>
      <br/><b>声音设计</b><br/>
      <sub>从头构建新声音——性别、年龄、口音、音高、风格。</sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="docs/screenshot-dub.png" alt="视频配音" width="100%"/>
      <br/><b>视频配音</b><br/>
      <sub>上传或粘贴 YouTube 链接。转录、翻译、重新配音、导出。</sub>
    </td>
    <td align="center">
      <img src="docs/screenshot-gallery.png" alt="声音库" width="100%"/>
      <br/><b>声音库</b><br/>
      <sub>搜索 YouTube、浏览分类、下载片段、构建你的收藏。</sub>
    </td>
  </tr>
  <tr>
    <td align="center">
      <img src="docs/screenshot-settings.png" alt="设置 — 模型" width="100%"/>
      <br/><b>设置 → 模型</b><br/>
      <sub>15 个模型。一键安装。自动检测你的平台（CUDA / MPS / CPU）。</sub>
    </td>
    <td align="center">
      <img src="docs/screenshot-libraryprojects.png" alt="项目" width="100%"/>
      <br/><b>项目</b><br/>
      <sub>配音项目、声音配置、生成历史、导出——全部可搜索。</sub>
    </td>
  </tr>
  <tr>
    <td align="center" colspan="2">
      <img src="docs/screenshot-logs.png" alt="设置 — 日志" width="100%"/>
      <br/><b>设置 → 日志</b><br/>
      <sub>实时后端、前端和 Tauri 运行时日志。筛选、刷新、清除。</sub>
    </td>
  </tr>
</table>

---

## 为什么选择 OmniVoice Studio？

ElevenLabs 收费 **$5–$330/月**，并在其服务器上处理你的音频。OmniVoice Studio **在你的硬件上运行，没有使用限制。**

| | **ElevenLabs** | **OmniVoice Studio** |
|---|---|---|
| **价格** | $5–$330/月，按字符计费 | 个人免费 · [商业许可证](#许可证) 面向企业 |
| **语音克隆** | ✅ 3 秒音频 | ✅ 3 秒音频，零样本 |
| **声音设计** | ✅ 性别、年龄 | ✅ 性别、年龄、口音、音高、风格、方言 |
| **语言** | 32 | **646** |
| **视频配音** | ✅ 仅云端 | ✅ 完全本地 |
| **数据隐私** | 音频发送到云端 | **数据不离开你的设备** |
| **API 密钥** | 需要 | 不需要 |
| **GPU 支持** | 不适用（云端） | CUDA · Apple Silicon · ROCm · CPU |
| **桌面应用** | ❌ | ✅ macOS · Windows · Linux |
| **可定制** | ❌ 闭源 | ✅ 可 Fork、扩展、发布 |

OmniVoice Studio 为你提供专业级 AI 工具，无需订阅或依赖云端。

---

## 系统要求

| | **最低配置** | **推荐配置** |
|---|---|---|
| **操作系统** | Windows 10, macOS 12+, Ubuntu 20.04+ | 任意现代 64 位操作系统 |
| **内存** | 8 GB | 16 GB+ |
| **显存（GPU）** | 4 GB（自动将 TTS 卸载到 CPU） | 8 GB+（NVIDIA RTX 3060+） |
| **硬盘** | 10 GB 可用空间（模型 + 缓存） | 20 GB+ SSD |
| **Python** | 3.10+（由 `uv` 管理） | 3.11–3.12 |
| **GPU** | 可选——CPU 可用 | NVIDIA CUDA · Apple Silicon MPS · AMD ROCm |

> [!TIP]
> 对于显存 **≤8 GB** 的 GPU，OmniVoice 会在转录期间自动将 TTS 卸载到 CPU——无需配置。不需要专用 GPU；整个流程可在 CPU 上运行（只是速度较慢）。

### TTS 引擎

OmniVoice 配备多引擎 TTS 后端。默认引擎（OmniVoice）始终可用；其他引擎可选装并自动检测。在 **设置 → TTS 引擎** 中切换引擎，或通过 `OMNIVOICE_TTS_BACKEND` 环境变量设置。

| 引擎 | 语言 | 克隆 | 指令 | Linux | macOS ARM | Windows | 许可证 |
|--------|:---------:|:-----:|:--------:|:-----:|:---------:|:-------:|:-------:|
| **OmniVoice**（默认） | 600+ | ✅ | ✅ | ✅ CUDA/CPU | ✅ MPS | ✅ CUDA/CPU | 内置 |
| **CosyVoice 3** | 9 + 18 种方言 | ✅ | ✅ | ✅ CUDA/CPU | ✅ MPS | ✅ CUDA/CPU | Apache-2.0 |
| **MLX-Audio**（Kokoro, Qwen3-TTS, CSM, Dia 等） | 多语言 | 因引擎而异 | 因引擎而异 | ❌ | ✅ 原生 | ❌ | 因引擎而异 |
| **VoxCPM2** | 30 | ✅ | ✅ | ✅ CUDA/CPU | ✅ MPS | ✅ CUDA/CPU | Apache-2.0 |
| **MOSS-TTS-Nano** | 20 | ✅ | ❌ | ✅ CUDA/CPU | ✅ CPU | ✅ CUDA/CPU | Apache-2.0 |
| **KittenTTS** | 英语 | ❌ | ❌ | ✅ CPU | ✅ CPU | ✅ CPU | MIT |

> **CUDA** = GPU 加速 · **MPS** = Apple Silicon Metal · **CPU** = 随处可运行，大模型较慢 · KittenTTS 和 MOSS-TTS-Nano 可在 CPU 上实时运行 · MLX-Audio 仅限 Apple Silicon。

---

## 架构

```
┌─────────────────────────────────────────────────┐
│                  前端 (React)                     │
│  DubTab · VoicePreview · BatchQueue · Gallery    │
├─────────────────────────────────────────────────┤
│                 后端 (FastAPI)                    │
│  97 个 API 端点 · SSE 流式 · SQLite              │
├──────────┬──────────┬──────────┬────────────────┤
│ WhisperX │  Demucs  │OmniVoice │   Pyannote     │
│  语音识别 │  音源分离 │  TTS    │  说话人分离    │
└──────────┴──────────┴──────────┴────────────────┘
        CUDA / MPS / ROCm / CPU（自动检测）
```

---

## 路线图

### ✅ 已发布

| 分类 | 功能 |
|----------|----------|
| **配音** | 完整流水线（转录→翻译→合成→封装）、场景感知分割、唇同步评分、流式 TTS |
| **声音** | 零样本克隆、声音设计、A/B 比较、声音预览控件、带收藏/标签的声音库 |
| **音频** | Demucs 人声分离、逐段增益、选择性轨道导出、SRT/VTT/MP3 导出 |
| **多语言** | 多语言批量选择器、批量配音队列（顺序 GPU 执行） |
| **说话人分离** | Pyannote 机器学习分离、自动说话人克隆提取、逐说话人声音分配 |
| **基础设施** | Docker 部署、CUDA/MPS/ROCm 自动检测、cuDNN 8 兼容、显存感知模型卸载 |
| **AI 溯源** | AudioSeal 不可见水印（类似 SynthID）、视频徽标叠加、水印检测 API |
| **用户体验** | 撤销/重做、键盘快捷键、拖放、会话持久化、毛玻璃设计系统 |
| **实时事件** | WebSocket 事件总线——数据变更时即时刷新侧边栏、指数退避重连 |
| **状态管理** | Zustand 状态管理迁移——`uiSlice`、`pillSlice`、`dubSlice`、`generateSlice`、`prefsSlice`、`glossarySlice` |
| **桌面** | 跨平台 Tauri 安装程序（macOS DMG、Windows MSI、Linux deb/AppImage）、自动更新基础设施 |
| **Windows 加固** | 跨平台日志路径、Triton 兼容方案、HF 符号链接绕过、300 秒健康检查超时 |
| **听写** | 全局系统热键（`⌘+⇧+Space`）、无边框浮动控件、WebSocket 流式语音识别、自动粘贴 |
| **批量流水线** | 完整批量 TTS：提取 → 转录 → 翻译 → 生成 → 混音 → 导出，带实时进度追踪 |

### 🔜 即将推出

- 🎬 **唇同步 v2** — 使用 wav2lip 进行视觉语音时间对齐
- 📖 **有声书编辑器** — 按章节感知的长篇叙述
- 🌐 **在线演示** — 无需安装即可体验 OmniVoice
- 🔌 **插件市场** — 社区贡献的 TTS 引擎和特效

---

## 参与贡献

我们欢迎各种形式的贡献——Bug 修复、新的 TTS 引擎适配器、UI 改进、文档和翻译。

- 📖 阅读 **[贡献指南](CONTRIBUTING.md)** 了解设置、代码风格和 PR 工作流
- 🐛 浏览 [good first issues](https://github.com/debpalash/OmniVoice-Studio/labels/good%20first%20issue)
- 💬 加入我们的 [Discord](https://discord.gg/bzQavDfVV9) 讨论创意或寻求帮助

---

## 常见问题

<details>
<summary><b>真的能和 ElevenLabs 一样好吗？</b></summary>
<br/>
在语音克隆和配音方面，是的——OmniVoice 使用最先进的扩散 TTS 模型，支持 646 种语言（ElevenLabs 仅支持 32 种）。在大多数用例下质量相当。ElevenLabs 的优势在于其完善的云 API 和预制声音库。OmniVoice 在隐私、成本、语言覆盖和可定制性方面胜出。
</details>

<details>
<summary><b>能在 Apple Silicon（M1/M2/M3/M4）上运行吗？</b></summary>
<br/>
可以。MPS 加速会被自动检测。在 Apple 硬件上，MLX 优化的 Whisper 模型可提供更快的转录速度。
</details>

<details>
<summary><b>需要多少显存？</b></summary>
<br/>
<b>最低 4 GB。</b> 显存 ≤8 GB 时，TTS 模型会在转录期间自动卸载到 CPU。8 GB 以上时，所有组件同时在 GPU 上运行。没有 GPU？CPU 模式也能用——只是速度较慢（TTS 约慢 3 倍）。
</details>

<details>
<summary><b>可以用于商业用途吗？</b></summary>
<br/>
个人、教育、内部团队和非商业用途在 <a href="https://fsl.software/">FSL-1.1-ALv2</a> 下免费。在 OmniVoice Studio 基础上构建竞争产品或服务需要商业许可证——参见<a href="#许可证">许可证</a>。定价方案即将推出。每个版本在发布两年后自动转换为 Apache 2.0。
</details>

<details>
<summary><b>支持哪些语言？</b></summary>
<br/>
通过 OmniVoice 模型的 TTS 支持 646 种语言。转录（WhisperX）支持 99 种语言。翻译覆盖范围取决于目标语言对。
</details>

<details>
<summary><b>可以添加自己的 TTS 引擎吗？</b></summary>
<br/>
可以。OmniVoice 使用<b>内置后端注册表</b>。约 50 行代码即可添加引擎：在 <code>backend/services/tts_backend.py</code> 中继承 <code>TTSBackend</code>，然后将其添加到底部的 <code>_REGISTRY</code> 字典中。内置六个引擎：OmniVoice、CosyVoice、MLX-Audio（14+ 子引擎）、VoxCPM2、MOSS-TTS-Nano 和 KittenTTS。详情请参见 <a href="#tts-引擎">TTS 引擎</a>部分。
</details>

---

## 许可证

OmniVoice Studio 在 [**Functional Source License (FSL-1.1-ALv2)**](https://fsl.software/) 下提供源码。

**免费**用于个人、教育、研究、内部团队和非商业用途。每个版本在**发布两年后自动转换为 Apache 2.0**。

**商业/企业**用户在 OmniVoice Studio 基础上构建竞争产品或服务需要商业许可证。**定价方案即将推出。** 在此期间如有疑问，请发送邮件至 **OmniVoice@palash.dev**。

参见 [`LICENSE`](LICENSE) 查看完整条款。

---

## 致谢

OmniVoice Studio 建立在优秀的开源工作之上：

| 项目 | 作用 |
|---------|------|
| [**OmniVoice (k2-fsa)**](https://github.com/k2-fsa/OmniVoice) | 零样本扩散 TTS 引擎——核心语音合成模型 |
| [**WhisperX**](https://github.com/m-bain/whisperX) | 词级别语音识别和时间对齐 |
| [**Demucs (Meta)**](https://github.com/facebookresearch/demucs) | 音乐源分离，用于人声隔离 |
| [**Pyannote**](https://github.com/pyannote/pyannote-audio) | 说话人分离——谁说了什么 |
| [**CTranslate2**](https://github.com/OpenNMT/CTranslate2) | CPU 和 GPU 上的优化 Transformer 推理 |
| [**AudioSeal (Meta)**](https://github.com/facebookresearch/audioseal) | AI 溯源的不可见神经音频水印 |
| [**Tauri**](https://tauri.app) | 原生桌面应用框架 |

---

<div align="center">

<br/>

如果你读到了这里，你是我们想要的人。<br/>
**[⭐ 给这个仓库点个 Star](https://github.com/debpalash/OmniVoice-Studio)**，让更多人能找到它。

<br/>

  <a href="https://star-history.com/#debpalash/OmniVoice-Studio&Date">
    <picture>
      <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=debpalash/OmniVoice-Studio&type=Date&theme=dark" />
      <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=debpalash/OmniVoice-Studio&type=Date" />
      <img alt="Star 历史" src="https://api.star-history.com/svg?repos=debpalash/OmniVoice-Studio&type=Date&theme=dark" width="600" />
    </picture>
  </a>
</div>
