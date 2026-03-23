# Prism 棱镜查词

> 一个浮动在桌面上的英文词汇查询小工具，支持中文释义、网络俚语、文化背景与语气分析。

A lightweight floating desktop widget for looking up English words — with Chinese translation, slang/internet context, cultural background, and tone analysis. Powered by OpenAI API.

---

## 截图 / Screenshots

![Prism截图](screenshots/image_slay.png)

---

## 下载 / Download

**Windows 用户：** 前往 [Releases](../../releases) 页面下载 `Prism_Setup_x.x.x.exe`，双击安装即可使用，无需安装 Python。

**Windows users:** Go to the [Releases](../../releases) page and download `Prism_Setup_x.x.x.exe`. No Python installation required.

---

## 使用说明 / Usage

1. 首次启动时，程序会弹出设置窗口，要求输入你自己的 **OpenAI API Key**
2. 前往 [platform.openai.com](https://platform.openai.com) 注册并获取 API Key
3. 将 Key 粘贴到输入框，点击确认即可开始使用
4. 在搜索框中输入英文单词或短句（最多 200 字符），按回车查询

> **注意：本项目不提供 API Key，用户需自行申请。**
> 查询会消耗你自己 OpenAI 账户的 Token 额度。

---

## 功能 / Features

- 中文翻译
- 网络 · 俚语解释 + 文化背景
- 语气分析（讽刺 / 正式 / 友好等）
- 拼写纠错提示
- 非英文输入检测
- 浮动窗口，始终置顶
- iOS 26 Liquid Glass 风格 UI
- Windows 11 原生亚克力模糊

---

## 本地开发 / Local Development

```bash
# 安装依赖
pip install -r requirements.txt

# 运行
python main.py
```

### 打包 .exe / Build .exe

```bash
pip install pyinstaller
pyinstaller Prism.spec
# 输出在 dist/Prism.exe
```

### 打包安装程序 / Build Installer

需要安装 [Inno Setup 6+](https://jrsoftware.org/isinfo.php)，然后：

```bash
# 先构建 exe
pyinstaller Prism.spec
# 再构建安装包
iscc installer.iss
# 输出在 installer_output/Prism_Setup_1.1.0.exe
```

---

## 隐私说明 / Privacy

- API Key 保存在本地 `%APPDATA%\Prism\config.json`（安装版）或程序目录下的 `config.json`（开发模式），不会上传
- 查询内容直接发送至 OpenAI API，不经过任何中间服务器
